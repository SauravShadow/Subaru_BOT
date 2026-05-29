"""
operations_sidecar.py — Shadow Garden Operations Center
Phoenix administrative sidecar running directly on the host machine.
Binds to Port 3030, reverse-proxies to Port 3031, and self-heals virtual-company container.
"""
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import List

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import HTMLResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PhoenixSidecar")

app = FastAPI(title="Shadow Garden Operations")

WORK_DIR = Path(__file__).parent.resolve()
TGPT_BIN = str(WORK_DIR / "tgpt")

# Shared connection pooling client
client = httpx.AsyncClient()

# WebSocket connections tracking
active_sockets: List[WebSocket] = []

# Status State
build_status = "ONLINE"  # ONLINE, BUILDING, HEALING, OFFLINE, ERROR
last_logs: List[str] = []

# ── Port / subdomain registry ─────────────────────────────────────────────────
PORT_REGISTRY_FILE = WORK_DIR / "PORT_REGISTRY.json"

def _load_port_registry() -> dict:
    try:
        if PORT_REGISTRY_FILE.exists():
            import json as _j
            return _j.loads(PORT_REGISTRY_FILE.read_text())
    except Exception:
        pass
    return {"ports": {}, "subdomains": {}, "reserved_ports": [], "next_suggested_port": 8300}

def _save_port_registry(reg: dict) -> None:
    import json as _j
    PORT_REGISTRY_FILE.write_text(_j.dumps(reg, indent=2))

def _register_port(port: int, service: str, subdomain: str = "", note: str = "") -> None:
    reg = _load_port_registry()
    reg["ports"][str(port)] = {"subdomain": subdomain, "service": service, "note": note}
    if subdomain:
        reg["subdomains"][subdomain] = port
    # Advance next_suggested_port if needed
    suggested = reg.get("next_suggested_port", 8300)
    if port >= suggested:
        reg["next_suggested_port"] = port + 100
    _save_port_registry(reg)

def _unregister_port(port: int, subdomain: str = "") -> None:
    reg = _load_port_registry()
    reg["ports"].pop(str(port), None)
    if subdomain:
        reg["subdomains"].pop(subdomain, None)
    _save_port_registry(reg)

def _port_available(port: int) -> tuple[bool, str]:
    """Returns (available, reason). False means taken."""
    reg = _load_port_registry()
    if port in reg.get("reserved_ports", []):
        return False, f"Port {port} is a reserved system port"
    entry = reg["ports"].get(str(port))
    if entry:
        return False, f"Port {port} already used by '{entry['service']}' ({entry.get('note','')})"
    return True, ""

def _subdomain_available(sub: str) -> tuple[bool, str]:
    """Returns (available, reason)."""
    reg = _load_port_registry()
    port = reg["subdomains"].get(sub)
    if port:
        entry = reg["ports"].get(str(port), {})
        return False, f"Subdomain '{sub}.saurav-info.xyz' already points to port {port} ({entry.get('service','')})"
    return True, ""

def _suggest_next_port() -> int:
    reg = _load_port_registry()
    candidate = reg.get("next_suggested_port", 8300)
    used = {int(p) for p in reg["ports"]}
    while candidate in used:
        candidate += 100
    return candidate

# ── Persistent service registry ───────────────────────────────────────────────
SERVICE_REGISTRY_FILE = WORK_DIR / "service_registry.json"

def _load_registry() -> dict:
    try:
        if SERVICE_REGISTRY_FILE.exists():
            import json as _j
            return _j.loads(SERVICE_REGISTRY_FILE.read_text())
    except Exception:
        pass
    return {}

def _save_registry(reg: dict) -> None:
    import json as _j
    SERVICE_REGISTRY_FILE.write_text(_j.dumps(reg, indent=2))

# name → {cwd, cmd, port (optional)}
_service_registry: dict = _load_registry()

# ── Helper for Socket Broadcast ───────────────────────────────────────────────

async def broadcast(msg_obj: dict):
    global last_logs
    logger.info(f"[Broadcast] {msg_obj}")
    if msg_obj.get("type") == "log":
        last_logs.append(msg_obj["text"])
        if len(last_logs) > 500:
            last_logs = last_logs[-500:]
            
    for ws in list(active_sockets):
        try:
            await ws.send_json(msg_obj)
        except Exception:
            pass

    if msg_obj.get("type") == "reload" or msg_obj.get("status") == "ONLINE":
        logger.info("Closing all DevOps WebSockets since container is now ONLINE.")
        for ws in list(active_sockets):
            try:
                await ws.close()
            except Exception:
                pass
        active_sockets.clear()

# ── Host-Side Python Workspace Tools ──────────────────────────────────────────

async def _host_bash(cmd: str) -> str:
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(WORK_DIR),
        )
        stdout, stderr = await proc.communicate()
        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        result = []
        if out:
            result.append(out)
        if err:
            result.append(f"[stderr]\n{err}")
        return "\n".join(result) if result else "[Empty Output]"
    except Exception as e:
        return f"Error: {e}"


def _host_read(path_str: str) -> str:
    try:
        path_str = path_str.strip()
        if path_str.startswith("/workspace/"):
            path_str = path_str[len("/workspace/"):]
        elif path_str.startswith("workspace/"):
            path_str = path_str[len("workspace/"):]
        if path_str.startswith("/app/"):
            path_str = path_str[len("/app/"):]
        elif path_str.startswith("app/"):
            path_str = path_str[len("app/"):]
            
        p = (WORK_DIR / path_str).resolve()
        if not str(p).startswith(str(WORK_DIR.resolve())):
            return f"Error: Permission denied. Path '{path_str}' is outside."
        if not p.exists():
            return f"Error: File '{path_str}' does not exist."
        if p.is_dir():
            return f"Error: '{path_str}' is a directory."
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error: {e}"


def _host_write(path_str: str, content: str) -> str:
    try:
        path_str = path_str.strip()
        if path_str.startswith("/workspace/"):
            path_str = path_str[len("/workspace/"):]
        elif path_str.startswith("workspace/"):
            path_str = path_str[len("workspace/"):]
        if path_str.startswith("/app/"):
            path_str = path_str[len("/app/"):]
        elif path_str.startswith("app/"):
            path_str = path_str[len("app/"):]
            
        p = (WORK_DIR / path_str).resolve()
        if not str(p).startswith(str(WORK_DIR.resolve())):
            return f"Error: Permission denied."
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to '{path_str}'."
    except Exception as e:
        return f"Error: {e}"


def _host_edit(path_str: str, target: str, replacement: str) -> str:
    try:
        path_str = path_str.strip()
        if path_str.startswith("/workspace/"):
            path_str = path_str[len("/workspace/"):]
        elif path_str.startswith("workspace/"):
            path_str = path_str[len("workspace/"):]
        if path_str.startswith("/app/"):
            path_str = path_str[len("/app/"):]
        elif path_str.startswith("app/"):
            path_str = path_str[len("app/"):]
            
        p = (WORK_DIR / path_str).resolve()
        if not str(p).startswith(str(WORK_DIR.resolve())):
            return f"Error: Permission denied."
        if not p.exists():
            return f"Error: File '{path_str}' does not exist."
        content = p.read_text(encoding="utf-8", errors="replace")
        if target not in content:
            return f"Error: Target text not found in '{path_str}'."
        new_content = content.replace(target, replacement, 1)
        p.write_text(new_content, encoding="utf-8")
        return f"Successfully edited '{path_str}'."
    except Exception as e:
        return f"Error: {e}"


def _sanitize_error_log(log: str, max_chars: int = 3000) -> str:
    """
    Strip patterns that could be misread as tool calls by the LLM,
    preventing prompt injection via crafted error output.
    """
    safe = re.sub(r'\[(BASH|READ|WRITE|EDIT|DONE):[^\]]*\]', r'[\1:REDACTED]', log)
    return safe[:max_chars]


def _parse_tool_call(text: str):
    m = re.search(r'\[DONE:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "done", {"summary": m.group(1).strip()}
    m = re.search(r'\[BASH:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "bash", {"cmd": m.group(1).strip()}
    m = re.search(r'\[READ:\s*(.*?)\]', text, re.DOTALL)
    if m:
        return "read", {"path": m.group(1).strip()}
    m = re.search(r'\[WRITE:\s*(.*?)\]', text, re.DOTALL)
    if m:
        path = m.group(1).strip()
        code_m = re.search(r'```(?:\w+)?\n(.*?)```', text[m.end():], re.DOTALL)
        content = code_m.group(1) if code_m else text[m.end():].strip()
        return "write", {"path": path, "content": content}
    m = re.search(r'\[EDIT:\s*(.*?)\]', text, re.DOTALL)
    if m:
        path = m.group(1).strip()
        rest = text[m.end():]
        target_m = re.search(r'TARGET:\s*```(?:\w+)?\n(.*?)```', rest, re.DOTALL)
        replacement_m = re.search(r'REPLACEMENT:\s*```(?:\w+)?\n(.*?)```', rest, re.DOTALL)
        if target_m and replacement_m:
            return "edit", {"path": path, "target": target_m.group(1), "replacement": replacement_m.group(1)}
    return None, None

# ── Self-Healing Loop Agent ───────────────────────────────────────────────────

async def run_healing_agent(error_log: str):
    """Host-side tool calling agent utilizing tgpt and free CLI providers to self-heal code."""
    error_log = _sanitize_error_log(error_log)
    await broadcast({"type": "status", "status": "HEALING"})
    await broadcast({"type": "log", "text": "Phoenix Healing Agent Activated..."})
    
    system_prompt = f"""You are the Phoenix SRE Operations Agent at Shadow Garden.
The docker-compose container build failed due to a compile or syntax error inside the files.
Your goal is to inspect the error traceback, read the workspace code, fix the code bug, and exit.

You have access to the local workspace file system tools. Call one tool EXACTLY and then STOP immediately, waiting for output:
1. Execute command: [BASH: pytest]
2. Read a file: [READ: web_cli.py]
3. Write/Overwrite a file: [WRITE: app/test.py] followed by code blocks
4. Edit a block in a file: [EDIT: web_cli.py] followed by TARGET and REPLACEMENT blocks
5. Finish task: [DONE: short summary of fix]

ERROR TRACEBACK:
{error_log}

Start by reading the file containing the error and finding the faulty line."""

    history = []
    current_prompt = "Find and fix the error reported in the traceback."
    max_turns = 8
    
    for turn in range(max_turns):
        if turn > 0:
            await asyncio.sleep(2.0)
            
        hist_str = "\n".join(f"{'User' if h['role']=='user' else 'Agent'}: {h['content']}" for h in history[-6:])
        full_input = f"{system_prompt}\n\nHistory:\n{hist_str}\n\nUser: {current_prompt}\n\nAgent:"
        
        # Call tgpt CLI in subprocess (fallback seq)
        providers = ["sky", "pollinations", "isou"]
        success = False
        turn_text = ""
        
        for p in providers:
            proc = await asyncio.create_subprocess_exec(
                TGPT_BIN, "-q", "--provider", p,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(WORK_DIR),
            )
            proc.stdin.write(full_input.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
            
            turn_text = ""
            while True:
                chunk = await proc.stdout.read(1024)
                if not chunk:
                    break
                turn_text += chunk.decode(errors="replace")
                
            await proc.wait()
            
            is_error = proc.returncode != 0 or "statuscode: 429" in turn_text.lower() or not turn_text.strip()
            if not is_error:
                success = True
                break
                
        if not success:
            await broadcast({"type": "log", "text": "Healing Agent hit rate limits on all providers. Aborting loop."})
            break
            
        await broadcast({"type": "log", "text": f"Agent reasoning:\n{turn_text}"})
        
        tool_type, tool_args = _parse_tool_call(turn_text)
        if not tool_type:
            break
            
        if tool_type == "done":
            summary = tool_args.get("summary", "Healed.")
            await broadcast({"type": "log", "text": f"✓ Healing Complete: {summary}"})
            break
            
        # Execute tool locally on host
        tool_result = ""
        if tool_type == "bash":
            cmd = tool_args["cmd"]
            await broadcast({"type": "log", "text": f"↗ [Tool Exec] BASH: `{cmd}`"})
            tool_result = await _host_bash(cmd)
        elif tool_type == "read":
            path = tool_args["path"]
            await broadcast({"type": "log", "text": f"↗ [Tool Exec] READ: `{path}`"})
            tool_result = _host_read(path)
        elif tool_type == "write":
            path = tool_args["path"]
            content = tool_args["content"]
            await broadcast({"type": "log", "text": f"↗ [Tool Exec] WRITE: `{path}`"})
            tool_result = _host_write(path, content)
        elif tool_type == "edit":
            path = tool_args["path"]
            target = tool_args["target"]
            replacement = tool_args["replacement"]
            await broadcast({"type": "log", "text": f"↗ [Tool Exec] EDIT: `{path}`"})
            tool_result = _host_edit(path, target, replacement)
            
        await broadcast({"type": "log", "text": f"[Tool Output]:\n{tool_result}\n"})
        history.append({"role": "assistant", "content": turn_text})
        history.append({"role": "user", "content": f"Tool output: {tool_result}"})
        current_prompt = f"Tool '{tool_type}' executed with output: {tool_result}. Proceed to next step."

# ── Rebuild Orchestration Task ───────────────────────────────────────────────

async def run_compose_rebuild():
    """Runs compose build and up, and calls healing loop if compilation fails."""
    global build_status
    build_status = "BUILDING"
    await broadcast({"type": "status", "status": "BUILDING"})
    await broadcast({"type": "log", "text": "=== Initiating Container Rebuild ==="})
    
    max_build_attempts = 3
    
    for attempt in range(max_build_attempts):
        await broadcast({"type": "log", "text": f"Attempt {attempt + 1} of {max_build_attempts} — Building..."})
        
        # 1. Spawn docker compose build
        proc = await asyncio.create_subprocess_shell(
            "docker compose build",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(WORK_DIR),
        )
        
        # Stream build logs in real time
        async def stream_output(stream, label):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if text:
                    await broadcast({"type": "log", "text": f"[{label}] {text}"})
                    
        await asyncio.gather(
            stream_output(proc.stdout, "compose"),
            stream_output(proc.stderr, "compose-err")
        )
        await proc.wait()
        
        if proc.returncode == 0:
            # 2. Rebuild passed! Start container
            await broadcast({"type": "log", "text": "Build passed! Recreating containers..."})
            up_proc = await asyncio.create_subprocess_shell(
                "docker compose down && docker compose up -d",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(WORK_DIR),
            )
            _, err_bytes = await up_proc.communicate()
            err_text = err_bytes.decode(errors="replace").strip()
            
            if up_proc.returncode == 0:
                # Poll container health on port 3031
                await broadcast({"type": "log", "text": "Container started! Verifying health on Port 3031..."})
                container_healthy = False
                for check in range(10):
                    await asyncio.sleep(1.0)
                    try:
                        res = await client.get("http://127.0.0.1:3031/api/capabilities", timeout=1.0)
                        if res.status_code == 200:
                            container_healthy = True
                            break
                    except Exception:
                        pass
                
                if container_healthy:
                    build_status = "ONLINE"
                    await broadcast({"type": "status", "status": "ONLINE"})
                    await broadcast({"type": "log", "text": "🎉 Success! Container is ONLINE and healthy."})
                    await broadcast({"type": "reload"})  # Trigger browser reload to switch back to chat UI
                    return
                else:
                    await broadcast({"type": "log", "text": "✗ Health check failed — fetching container logs…"})
                    logs_proc = await asyncio.create_subprocess_shell(
                        "docker compose logs --tail=100 virtual-company",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(WORK_DIR),
                    )
                    stdout_bytes, _ = await logs_proc.communicate()
                    logs_text = stdout_bytes.decode(errors="replace").strip() or \
                                "Container health check timed out. No logs found."

                    await broadcast({"type": "log", "text": f"Diagnostics:\n{logs_text}"})
                    await run_healing_agent(logs_text)

                    # Python files are volume-mounted — no rebuild needed after a fix.
                    # Just restart the container so uvicorn picks up the corrected file.
                    await broadcast({"type": "log", "text": "Restarting container after Python fix…"})
                    restart_proc = await asyncio.create_subprocess_shell(
                        "docker compose restart virtual-company",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(WORK_DIR),
                    )
                    await restart_proc.communicate()

                    # Re-poll health after restart
                    container_healthy = False
                    for check in range(10):
                        await asyncio.sleep(1.5)
                        try:
                            res = await client.get("http://127.0.0.1:3031/api/capabilities", timeout=1.0)
                            if res.status_code == 200:
                                container_healthy = True
                                break
                        except Exception:
                            pass

                    if container_healthy:
                        build_status = "ONLINE"
                        await broadcast({"type": "status", "status": "ONLINE"})
                        await broadcast({"type": "log", "text": "🎉 Success! Container recovered after Python fix."})
                        await broadcast({"type": "reload"})
                        return
                    # If still unhealthy, fall through to next build attempt
            else:
                await broadcast({"type": "log", "text": f"Error starting container: {err_text}"})
                await run_healing_agent(err_text)
        else:
            # Rebuild failed! Get error log from stderr
            await broadcast({"type": "log", "text": "✗ Build failed! Triggering SRE Healing Loop..."})
            
            # Check all Python files in the mounted app directory
            compile_proc = await asyncio.create_subprocess_shell(
                "python3 -m compileall -q app/ 2>&1 || true",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(WORK_DIR),
            )
            out_bytes, _ = await compile_proc.communicate()
            compile_err = out_bytes.decode(errors="replace").strip()

            if not compile_err:
                compile_err = "Docker build failed (no Python syntax errors detected). Check Dockerfile or requirements.txt."
                
            await broadcast({"type": "log", "text": f"Captured Error Diagnostics:\n{compile_err}"})
            await run_healing_agent(compile_err)
            
    build_status = "ERROR"
    await broadcast({"type": "status", "status": "ERROR"})
    await broadcast({"type": "log", "text": "✗ Rebuild attempts exhausted. Container remains in ERROR state. Manual intervention required."})

# ── API Routes ────────────────────────────────────────────────────────────────

async def api_trigger_rebuild():
    if build_status in ("BUILDING", "HEALING"):
        return {"status": "already_running", "message": f"Orchestrator currently busy in state: {build_status}"}
    asyncio.create_task(run_compose_rebuild())
    return {"status": "ok", "message": "Phoenix Self-Healing Rebuild initiated."}


async def api_get_status():
    return {"status": build_status}


async def _tmux_session_alive(name: str) -> bool:
    """Return True if a tmux session with this name is running."""
    proc = await asyncio.create_subprocess_shell(
        f"tmux has-session -t {name} 2>/dev/null && echo yes || echo no",
        stdout=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    return out.decode().strip() == "yes"


async def _launch_in_tmux(name: str, cwd: str, cmd: str) -> bool:
    """Kill any stale session and start a fresh one. Returns True on success."""
    await asyncio.create_subprocess_shell(f"tmux kill-session -t {name} 2>/dev/null || true")
    await asyncio.sleep(0.2)

    req = Path(cwd) / "requirements.txt"
    if req.exists():
        install = await asyncio.create_subprocess_shell(
            "pip install -q -r requirements.txt --break-system-packages",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await install.communicate()

    tmux_cmd = f"tmux new-session -d -s {name} 'cd {cwd} && {cmd} 2>&1 | tee /tmp/{name}.log'"
    proc = await asyncio.create_subprocess_shell(
        tmux_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        logger.error("Failed to start %s: %s", name, err.decode().strip())
        return False
    return True


async def _service_watchdog():
    """Every 30 s, restart any registered service whose tmux session has died."""
    await asyncio.sleep(15)  # initial grace period on startup
    while True:
        for name, info in list(_service_registry.items()):
            if not await _tmux_session_alive(name):
                logger.warning("Service '%s' is down — restarting…", name)
                await broadcast({"type": "log", "text": f"⚠ Service '{name}' was down. Auto-restarting…"})
                ok = await _launch_in_tmux(name, info["cwd"], info["cmd"])
                if ok:
                    await broadcast({"type": "log", "text": f"✓ Service '{name}' restarted."})
                else:
                    await broadcast({"type": "log", "text": f"✗ Failed to restart '{name}'."})
        await asyncio.sleep(30)


def _normalize_cwd(cwd: str) -> str:
    """Translate container-internal paths to host paths so workers don't need to know the difference."""
    # /workspace/ inside container → /home/subaru/projects/ on host
    if cwd.startswith("/workspace/"):
        cwd = "/home/subaru/projects/" + cwd[len("/workspace/"):]
    elif cwd == "/workspace":
        cwd = "/home/subaru/projects"
    # /app/ inside container → /home/subaru/projects/virtual-company/ on host
    if cwd.startswith("/app/"):
        cwd = str(WORK_DIR) + "/" + cwd[len("/app/"):]
    elif cwd == "/app":
        cwd = str(WORK_DIR)
    return cwd


async def _port_in_use(port: int) -> bool:
    proc = await asyncio.create_subprocess_shell(
        f"ss -tlnp 'sport = :{port}' 2>/dev/null | grep -q ':{port}' && echo yes || echo no",
        stdout=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    return out.decode().strip() == "yes"


async def api_start_service(body: dict):
    """
    Launch a persistent background service on the HOST via tmux and register
    it so the watchdog keeps it alive across crashes and sidecar restarts.
    Body: {"name": "expense-planner", "cwd": "/workspace/…", "cmd": "python3 -m http.server 8100"}
    Container paths (/workspace/, /app/) are auto-translated to host paths.
    """
    name = body.get("name", "").strip()
    cwd  = _normalize_cwd(body.get("cwd",  "").strip())
    cmd  = body.get("cmd",  "").strip()
    port = body.get("port")

    if not name or not cwd or not cmd:
        return {"ok": False, "error": "name, cwd, and cmd are required"}

    # Validate cwd exists on host
    if not Path(cwd).exists():
        return {"ok": False, "error": f"Directory not found on host: {cwd}"}

    # Check port conflict against both registry and live sockets
    if port:
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = None
        if port:
            # 1. Check PORT_REGISTRY (includes Cloudflare-mapped ports the sidecar didn't start)
            available, reason = _port_available(port)
            existing_svc = next((n for n, info in _service_registry.items() if info.get("port") == port), None)
            if not available and (not existing_svc or existing_svc != name):
                suggested = _suggest_next_port()
                return {"ok": False, "error": f"{reason}. Try port {suggested} instead."}
            # 2. Check if actually in use on the OS
            if await _port_in_use(port):
                existing = next((n for n, info in _service_registry.items() if info.get("port") == port), None)
                if existing and existing != name:
                    suggested = _suggest_next_port()
                    return {"ok": False, "error": f"Port {port} is already bound by '{existing}'. Try port {suggested} instead."}

    ok = await _launch_in_tmux(name, cwd, cmd)
    if not ok:
        return {"ok": False, "error": f"tmux failed to start '{name}'"}

    # Persist to service registry (watchdog) and port registry (collision prevention)
    _service_registry[name] = {"cwd": cwd, "cmd": cmd, "port": port}
    _save_registry(_service_registry)
    if port:
        _register_port(port, service=name, note=f"cwd:{cwd}")

    await asyncio.sleep(2)
    await broadcast({"type": "log", "text": f"[start-service] '{name}' started and registered — logs at /tmp/{name}.log"})
    logger.info("Service '%s' started and persisted in registry", name)
    return {
        "ok":      True,
        "name":    name,
        "cwd":     cwd,
        "cmd":     cmd,
        "log":     f"/tmp/{name}.log",
        "message": f"Service '{name}' started. Logs: /tmp/{name}.log",
    }


async def api_stop_service(body: dict):
    """Kill a service and remove it from the watchdog registry."""
    name = body.get("name", "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}

    # Remove from service registry and port registry
    if name in _service_registry:
        info = _service_registry.pop(name)
        _save_registry(_service_registry)
        if info.get("port"):
            _unregister_port(info["port"])

    proc = await asyncio.create_subprocess_shell(
        f"tmux kill-session -t {name} 2>/dev/null && echo killed || echo not_found",
        stdout=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    return {"ok": True, "result": out.decode().strip()}


async def api_list_services():
    """List registered services and their live status."""
    result = []
    for name, info in _service_registry.items():
        alive = await _tmux_session_alive(name)
        result.append({"name": name, "cwd": info["cwd"], "cmd": info["cmd"],
                        "port": info.get("port"), "alive": alive})
    return {"services": result}


async def api_port_registry():
    """Return full port/subdomain registry — use this before picking a port."""
    return _load_port_registry()


async def api_check_port(port: int):
    """Check if a port is available. Returns {available, reason, suggested_alternative}."""
    avail, reason = _port_available(port)
    return {"port": port, "available": avail, "reason": reason,
            "suggested_alternative": _suggest_next_port() if not avail else None}


async def api_check_subdomain(subdomain: str):
    """Check if a subdomain is available. Returns {available, reason}."""
    avail, reason = _subdomain_available(subdomain)
    return {"subdomain": subdomain, "available": avail, "reason": reason}


async def api_register_subdomain(body: dict):
    """Manually register a subdomain→port mapping (e.g. after adding a Cloudflare rule)."""
    port = body.get("port")
    subdomain = body.get("subdomain", "").strip()
    service = body.get("service", subdomain)
    note = body.get("note", "")
    if not port or not subdomain:
        return {"ok": False, "error": "port and subdomain required"}
    _register_port(int(port), service=service, subdomain=subdomain, note=note)
    return {"ok": True, "message": f"Registered {subdomain}.saurav-info.xyz → port {port}"}


# ── HTTP Reverse Proxy ────────────────────────────────────────────────────────

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def transparent_http_proxy(request: Request, path: str):
    global build_status

    # Intercept SRE Sidecar API triggers
    if path == "api/rebuild":
        return await api_trigger_rebuild()
    if path == "api/status":
        return await api_get_status()
    if path == "api/start-service":
        body = await request.json()
        return await api_start_service(body)
    if path == "api/stop-service":
        body = await request.json()
        return await api_stop_service(body)
    if path == "api/services":
        return await api_list_services()
    if path == "api/port-registry":
        return await api_port_registry()
    if path.startswith("api/check-port/"):
        try:
            port = int(path.split("/")[-1])
            return await api_check_port(port)
        except ValueError:
            return {"error": "invalid port"}
    if path.startswith("api/check-subdomain/"):
        sub = path.split("/")[-1]
        return await api_check_subdomain(sub)
    if path == "api/register-subdomain":
        body = await request.json()
        return await api_register_subdomain(body)
        
    # If the main container is down/building/healing, serve DevOps Operations HUD
    if build_status != "ONLINE":
        accept = request.headers.get("accept", "")
        if "text/html" in accept or path == "":
            return HTMLResponse(HTML_PORTAL)
        return {"status": build_status, "message": "Container is currently offline / rebuilding."}
        
    # Forward/Proxy HTTP requests transparently to main container remapped to Port 3031
    target_url = f"http://127.0.0.1:3031/{path}"
    headers = dict(request.headers)
    headers.pop("host", None)  # Strip host to avoid loopback
    
    body = await request.body()
    params = dict(request.query_params)
    
    try:
        res = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            params=params,
            content=body,
            follow_redirects=True,
            timeout=30.0
        )
        resp_headers = dict(res.headers)
        # Force-bust Cloudflare/browser cache for all responses
        resp_headers["cache-control"] = "no-cache, no-store, must-revalidate"
        resp_headers["cdn-cache-control"] = "no-store"
        resp_headers["cloudflare-cdn-cache-control"] = "no-store"
        resp_headers["pragma"] = "no-cache"
        resp_headers["expires"] = "0"
        resp_headers.pop("etag", None)
        return Response(
            content=res.content,
            status_code=res.status_code,
            headers=resp_headers
        )
    except Exception as e:
        logger.error(f"SRE Proxy error to {target_url}: {e}")
        # Build is dead on Port 3031. Fallback to serving operations portal
        build_status = "ERROR"
        return HTMLResponse(HTML_PORTAL)

# ── WebSocket Reverse Proxy ───────────────────────────────────────────────────

@app.websocket("/ws")
async def proxy_websocket_endpoint(ws: WebSocket):
    global build_status
    await ws.accept()
    
    # If container is down/building/healing, handle it as DevOps WebSocket
    if build_status != "ONLINE":
        active_sockets.append(ws)
        await ws.send_json({"type": "status", "status": build_status})
        for text in last_logs:
            await ws.send_json({"type": "log", "text": text})
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            if ws in active_sockets:
                active_sockets.remove(ws)
        return
        
    # Proxy WebSocket to internal container ws://127.0.0.1:3031/ws
    from urllib.parse import urlencode
    params = dict(ws.query_params)
    target_ws_url = "ws://127.0.0.1:3031/ws"
    if params:
        target_ws_url += "?" + urlencode(params)
        
    try:
        async with websockets.connect(target_ws_url) as target_ws:

            async def forward_to_client():
                try:
                    async for message in target_ws:
                        await ws.send_text(message)
                except Exception:
                    pass

            async def forward_to_server():
                try:
                    while True:
                        message = await ws.receive_text()
                        await target_ws.send(message)
                except Exception:
                    pass

            t1 = asyncio.create_task(forward_to_client())
            t2 = asyncio.create_task(forward_to_server())
            _, pending = await asyncio.wait(
                [t1, t2], return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
                await asyncio.gather(t, return_exceptions=True)

    except Exception as e:
        logger.error(f"WebSocket Proxy error to {target_ws_url}: {e}")
        try:
            await ws.close(code=1011)
        except Exception:
            pass

# ── HTML DevOps Portal ────────────────────────────────────────────────────────

HTML_PORTAL = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Shadow Garden — Operations Command</title>
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
:root {
  --void:    #02060c;
  --deep:    #050d18;
  --surface: #0a1424;
  --card:    #0f1f35;
  --border:  #1b3252;
  --text:    #d0e5f5;
  --dim:     #6384a6;
  --mute:    #263a56;
  --ceo:     #00d4ff;
  --ok:      #10b981;
  --warn:    #f59e0b;
  --err:     #ef4444;
}
*{box-sizing:border-box;margin:0;padding:0}
body {
  background: var(--void); color: var(--text);
  font-family: 'Rajdhani', sans-serif;
  overflow: hidden; height: 100vh;
  display: flex; flex-direction: column;
  background-image:
    radial-gradient(ellipse 60% 40% at 50% 10%, rgba(0, 212, 255, 0.05), transparent),
    repeating-linear-gradient(0deg, transparent, transparent 39px, rgba(27,50,82,0.2) 40px);
}
header {
  height: 52px; background: var(--deep); border-bottom: 1px solid var(--border);
  display: flex; align-items: center; padding: 0 20px; gap: 14px; flex-shrink: 0;
}
.brand { font-size: 19px; font-weight: 700; letter-spacing: 4px; color: var(--ceo); text-shadow: 0 0 10px rgba(0,212,255,0.4); }
.brand-sub { font-size: 10px; letter-spacing: 2px; color: var(--dim); text-transform: uppercase; margin-top: 2px; }
.main { flex: 1; display: grid; grid-template-columns: 240px 1fr; overflow: hidden; }
aside {
  background: var(--deep); border-right: 1px solid var(--border);
  padding: 20px; display: flex; flex-direction: column; gap: 20px;
}
section { display: flex; flex-direction: column; padding: 20px; overflow: hidden; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.lbl { font-size: 10px; text-transform: uppercase; color: var(--dim); letter-spacing: 1px; margin-bottom: 6px; }
.status-pill {
  padding: 6px 12px; border-radius: 4px; font-weight: 700; text-align: center;
  font-size: 14px; letter-spacing: 1.5px; border: 1px solid transparent;
}
.status-pill.ONLINE { background: rgba(16,185,129,0.1); border-color: var(--ok); color: var(--ok); box-shadow: 0 0 10px rgba(16,185,129,0.2); }
.status-pill.BUILDING { background: rgba(245,158,11,0.1); border-color: var(--warn); color: var(--warn); box-shadow: 0 0 10px rgba(245,158,11,0.2); animation: pulse 1.5s infinite; }
.status-pill.HEALING { background: rgba(167,139,250,0.1); border-color: #a78bfa; color: #a78bfa; box-shadow: 0 0 10px rgba(167,139,250,0.2); animation: pulse 1.2s infinite; }
.status-pill.ERROR { background: rgba(239,68,68,0.1); border-color: var(--err); color: var(--err); box-shadow: 0 0 10px rgba(239,68,68,0.2); }
@keyframes pulse { 50% { opacity: 0.55; } }
.rebuild-btn {
  background: var(--ceo); color: var(--void); font-family: 'Rajdhani', sans-serif;
  font-size: 13px; font-weight: 700; border: none; padding: 10px; border-radius: 5px;
  cursor: pointer; letter-spacing: 1px; text-transform: uppercase; transition: all 0.2s;
}
.rebuild-btn:hover { background: #33ddff; transform: scale(1.03); }
.rebuild-btn:disabled { background: var(--border); color: var(--dim); cursor: not-allowed; transform: none; }
.console {
  flex: 1; background: var(--void); border: 1px solid var(--border);
  border-radius: 6px; padding: 16px; font-family: 'JetBrains Mono', monospace;
  font-size: 12px; line-height: 1.6; overflow-y: auto; color: #8cb4db;
  box-shadow: inset 0 0 15px rgba(0,0,0,0.7);
}
.c-log { margin-bottom: 4px; white-space: pre-wrap; word-break: break-all; }
.c-log.compose-err, .c-log.compose-err-ev { color: var(--warn); }
.c-log.diag { color: var(--err); font-weight: bold; }
</style>
</head>
<body>
<header>
  <span class="brand">SHADOW GARDEN</span>
  <span class="brand-sub">Operations Command</span>
</header>
<div class="main">
  <aside>
    <div class="card" style="display:flex; flex-direction:column; gap:12px;">
      <div>
        <div class="lbl">Deployment Status</div>
        <div class="status-pill ONLINE" id="spill">ONLINE</div>
      </div>
      <button class="rebuild-btn" id="rbtn" onclick="triggerRebuild()">Manual Rebuild</button>
    </div>
    <div class="card">
      <div class="lbl">Services Managed</div>
      <div style="font-size:12px; line-height:1.8; color:var(--dim);">
        ● Port 3030: SRE Gateway<br>
        ● Port 3031: web_cli container<br>
        ● Port 5432: postgresql<br>
        ● Port 6379: redis
      </div>
    </div>
  </aside>
  <section>
    <div class="lbl" style="margin-bottom:10px;">DevOps Logging Terminal</div>
    <div class="console" id="console"></div>
  </section>
</div>
<script>
let ws;
function connect() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  // Connect to the unified ws endpoint on Port 3030
  ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.onmessage = ({data}) => {
    const o = JSON.parse(data);
    if(o.type === 'reload') {
      // Auto reload browser window when container starts successfully to restore main chat UI
      setTimeout(() => { location.reload(); }, 1200);
      return;
    }
    if(o.type === 'status') {
      const sp = document.getElementById('spill');
      sp.textContent = o.status;
      sp.className = 'status-pill ' + o.status;
      document.getElementById('rbtn').disabled = (o.status === 'BUILDING' || o.status === 'HEALING');
    } else if(o.type === 'log') {
      const con = document.getElementById('console');
      const div = document.createElement('div');
      div.className = 'c-log';
      if(o.text.includes('compose-err') || o.text.includes('warning') || o.text.includes('Rate-limited')) {
        div.classList.add('compose-err');
      } else if(o.text.includes('✗') || o.text.includes('Error') || o.text.includes('Traceback')) {
        div.classList.add('diag');
      }
      div.textContent = o.text;
      con.appendChild(div);
      con.scrollTop = con.scrollHeight;
    }
  };
  ws.onclose = () => setTimeout(connect, 2000);
}
async function triggerRebuild() {
  document.getElementById('rbtn').disabled = true;
  await fetch('/api/rebuild', {method: 'POST'});
}
connect();
</script>
</body>
</html>"""


async def health_check_background_loop():
    """Periodically checks the container health on Port 3031 and auto-recovers to ONLINE if healthy."""
    global build_status
    while True:
        await asyncio.sleep(5.0)
        if build_status in ("ERROR", "OFFLINE"):
            try:
                res = await client.get("http://127.0.0.1:3031/api/capabilities", timeout=1.0)
                if res.status_code == 200:
                    logger.info("Health check passed! Auto-recovering status to ONLINE.")
                    build_status = "ONLINE"
                    await broadcast({"type": "status", "status": "ONLINE"})
                    await broadcast({"type": "log", "text": "🎉 Auto-healed! Main container detected ONLINE on Port 3031."})
                    await broadcast({"type": "reload"})
            except Exception:
                pass


@app.on_event("startup")
async def start_health_check_loop():
    asyncio.create_task(health_check_background_loop())
    asyncio.create_task(_service_watchdog())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=3030)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    print(f"\n  Shadow Garden Operations Command  |  http://{args.host}:{args.port}\n")
    uvicorn.run(app, host=args.host, port=args.port)
