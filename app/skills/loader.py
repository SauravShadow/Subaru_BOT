"""
SkillLoader — hot-loadable skill registry.

Core tools (bash, read, write, edit, read_inbox) are metadata-only: their
handlers live in app/agents/tools.py and are dispatched by executor.py.
Learned skills are independent modules with async handle_<name>() functions.
"""
import importlib.util
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SkillLoader:
    def __init__(self, skills_dir: Path):
        self._dir    = skills_dir
        self._tools: dict[str, callable] = {}   # tool_name → async handler (learned only)
        self._meta:  list[dict]          = []   # all tool metadata (core + learned)

    # ── Loading ────────────────────────────────────────────────────

    def load_all(self) -> None:
        self._tools.clear()
        self._meta.clear()
        self._load_core()
        self._load_learned()

    def _load_core(self) -> None:
        core_dir = self._dir / "core"
        if not core_dir.exists():
            return
        for py in sorted(core_dir.glob("*.py")):
            if py.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"skills_core_{py.stem}", py)
                mod  = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for tool in getattr(mod, "TOOLS", []):
                    self._meta.append({**tool, "zone": "core"})
            except Exception as exc:
                logger.error("Failed loading core skill %s: %s", py.name, exc)

    def _load_learned(self) -> None:
        learned_dir = self._dir / "learned"
        if not learned_dir.exists():
            return
        for manifest_path in sorted(learned_dir.glob("*/manifest.json")):
            try:
                self._load_from_manifest(manifest_path)
            except Exception as exc:
                logger.error("Failed loading skill %s: %s", manifest_path.parent.name, exc)

    def _load_from_manifest(self, manifest_path: Path) -> None:
        manifest = json.loads(manifest_path.read_text())
        sid      = manifest["id"]
        version  = str(manifest.get("active_version", "1"))
        skill_py = manifest_path.parent / f"v{version}" / "skill.py"

        if not skill_py.exists():
            logger.warning("Skill %s v%s skill.py not found", sid, version)
            return

        mod_name = f"learned_skill_{sid}_v{version}"
        spec = importlib.util.spec_from_file_location(mod_name, skill_py)
        mod  = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)

        for tool in getattr(mod, "TOOLS", []):
            name    = tool["name"]
            handler = getattr(mod, f"handle_{name}", None)
            if handler:
                self._tools[name] = handler
                self._meta.append({**tool, "zone": "learned",
                                   "skill_id": sid, "version": version})

    # ── Public API ─────────────────────────────────────────────────

    def get_tool(self, name: str) -> Optional[callable]:
        """Return the async handler for a learned skill tool, or None for core tools."""
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        """All tool metadata (core + learned) for the Skills Panel."""
        return list(self._meta)

    def list_manifests(self) -> list[dict]:
        learned_dir = self._dir / "learned"
        if not learned_dir.exists():
            return []
        result = []
        for p in sorted(learned_dir.glob("*/manifest.json")):
            try:
                result.append(json.loads(p.read_text()))
            except Exception:
                pass
        return result

    # ── Skill installation ─────────────────────────────────────────

    def register_skill(self, manifest: dict, skill_code: str, test_code: str) -> dict:
        """Write skill files, run pytest, register on pass. Raises ValueError on test failure."""
        import re as _re
        sid = manifest.get("id", "")
        if not _re.match(r'^[a-zA-Z0-9_-]+$', sid):
            raise ValueError(
                f"Invalid skill id {sid!r}: only letters, digits, underscores and hyphens allowed"
            )
        version     = str(manifest.get("active_version", "1"))
        skill_dir   = self._dir / "learned" / sid
        version_dir = skill_dir / f"v{version}"
        version_dir.mkdir(parents=True, exist_ok=True)

        (version_dir / "skill.py").write_text(skill_code, encoding="utf-8")
        (version_dir / "test_skill.py").write_text(test_code, encoding="utf-8")
        (skill_dir / "__init__.py").touch(exist_ok=True)
        (version_dir / "__init__.py").touch(exist_ok=True)

        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(version_dir / "test_skill.py"),
             "-q", "--tb=short", "--no-header"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise ValueError(
                f"Skill '{sid}' tests failed:\n{result.stdout}\n{result.stderr}"
            )

        # Write manifest only after tests pass
        (skill_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        self._load_from_manifest(skill_dir / "manifest.json")
        logger.info("Skill '%s' v%s registered.", sid, version)
        return manifest

    def rollback(self, skill_id: str) -> bool:
        """Revert skill to the version listed in manifest.rollback_to."""
        manifest_path = self._dir / "learned" / skill_id / "manifest.json"
        if not manifest_path.exists():
            return False
        manifest    = json.loads(manifest_path.read_text())
        rollback_to = manifest.get("rollback_to")
        if not rollback_to:
            return False
        manifest["rollback_to"]    = manifest["active_version"]
        manifest["active_version"] = str(rollback_to)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self.load_all()  # full reload to avoid stale _meta entries
        return True
