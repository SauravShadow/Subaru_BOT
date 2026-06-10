# Delegation-Tag Regex & Maya Gemini Tool-Tag Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the CEO's `[DELEGATE:browser]` mentions-in-prose from spawning garbage work items, and make Maya reliably emit her `[BROWSER_*]` tool tags when running on the Gemini backend.

**Architecture:** Two independent, surgical fixes against the spec at `docs/superpowers/specs/2026-06-07-delegation-and-maya-tooltag-fixes-design.md`: (1) anchor `_DELEGATE_RE` to line-start (`re.MULTILINE`) plus a persona guard so the CEO stops writing the tag inline, and (2) add a per-agent `gemini_safe_tags` allowlist that `_build_gemini_prompt` uses to carve an explicit exception into its "no tool tags" instruction instead of a contradictory blanket ban.

**Tech Stack:** Python 3.12, pytest + pytest-asyncio, regex (`re`), existing `unittest.mock` test patterns.

---

## File Structure

- Modify: `app/services/delegation.py` — anchor `_DELEGATE_RE` to line-start
- Modify: `app/agents/definitions.py` — add anti-prose guard to `_ceo_persona()`; add `"gemini_safe_tags"` to Maya's `AGENT_DEFS["browser"]` entry
- Modify: `app/agents/executor.py` — make `_build_gemini_prompt` agent-aware of `gemini_safe_tags`
- Create: `tests/test_delegation.py` — regex/parsing tests for Fix 1
- Modify: `tests/test_executor_gemini.py` — add prompt-building tests for Fix 2

---

### Task 1: Anchor `_DELEGATE_RE` to line-start so inline mentions don't parse as directives

**Files:**
- Modify: `app/services/delegation.py:4-6`
- Test: `tests/test_delegation.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_delegation.py`:

```python
"""Tests for CEO delegation-tag parsing — directives vs. inline mentions."""
from app.services.delegation import parse_delegations


def test_real_directive_at_line_start_parses():
    text = "On it — let's get this moving.\n[DELEGATE:browser] Find FastAPI backend roles on LinkedIn in Bangalore and apply."
    result = parse_delegations(text)
    assert result == [("browser", "Find FastAPI backend roles on LinkedIn in Bangalore and apply.")]


def test_inline_mention_does_not_parse_as_directive():
    text = "Say the word and I'll get [DELEGATE:browser] Maya moving on it right away."
    result = parse_delegations(text)
    assert result == []


def test_multiple_real_directives_parse_independently():
    text = (
        "Kicking off two things.\n"
        "[DELEGATE:backend] Build a REST endpoint for user search.\n"
        "[DELEGATE:browser] Apply to the Stripe backend role at https://stripe.com/jobs/123."
    )
    result = parse_delegations(text)
    assert result == [
        ("backend", "Build a REST endpoint for user search."),
        ("browser", "Apply to the Stripe backend role at https://stripe.com/jobs/123."),
    ]


def test_directive_followed_by_trailing_prose_stops_at_next_tag():
    text = (
        "[DELEGATE:browser] Search for Stripe roles and apply.\n"
        "[EMAIL_USER:Heads up] Just letting you know I kicked this off."
    )
    result = parse_delegations(text)
    assert result == [("browser", "Search for Stripe roles and apply.")]
```

- [ ] **Step 2: Run tests to verify the inline-mention test fails**

Run: `cd /home/subaru/projects/virtual-company && python3 -m pytest tests/test_delegation.py -v`

Expected: `test_inline_mention_does_not_parse_as_directive` FAILS — the current
unanchored regex matches `[DELEGATE:browser]` wherever it appears, so
`result` is `[("browser", "Maya moving on it right away.")]` instead of `[]`.
The other three tests should already PASS (they exercise behavior the
unanchored regex also happens to get right).

- [ ] **Step 3: Anchor the regex to line-start**

In `app/services/delegation.py`, replace lines 4-6:

```python
_DELEGATE_RE = re.compile(
    r'\[DELEGATE:(\w+)\]\s*(.*?)(?=\[DELEGATE:|\[EMAIL_USER:|$)', re.DOTALL
)
```

with:

```python
_DELEGATE_RE = re.compile(
    r'^\[DELEGATE:(\w+)\]\s*(.*?)(?=^\[DELEGATE:|^\[EMAIL_USER:|\Z)',
    re.DOTALL | re.MULTILINE
)
```

(`^` now matches start-of-line under `re.MULTILINE`, so a tag that opens its
own line still parses; one embedded mid-sentence no longer matches. `\Z`
replaces `$` as the end-of-string anchor — under `MULTILINE`, `$` would also
match at line-ends, which we don't want for the lookahead's "end" branch.)

- [ ] **Step 4: Run tests to verify they all pass**

Run: `cd /home/subaru/projects/virtual-company && python3 -m pytest tests/test_delegation.py -v`

Expected: all 4 tests PASS.

- [ ] **Step 5: Run the existing delegation-adjacent test suite to check for regressions**

Run: `cd /home/subaru/projects/virtual-company && python3 -m pytest tests/ -k "delegat or email" -v`

Expected: all PASS (no other test file references `_DELEGATE_RE`/`_EMAIL_RE`
directly as of this writing, but this catches anything that does).

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/services/delegation.py tests/test_delegation.py
git commit -m "fix(delegation): anchor [DELEGATE:] regex to line-start

Prevents the CEO's inline mentions of [DELEGATE:role] inside descriptive
prose (e.g. \"I'll get [DELEGATE:browser] Maya on it\") from being parsed
as real delegation directives and spawning garbage work items. Real
directives, which always open their own line per the CEO's persona
instructions, still parse correctly."
```

---

### Task 2: Add an anti-prose guard to the CEO persona

**Files:**
- Modify: `app/agents/definitions.py:15-20` (inside `_ceo_persona()`)

- [ ] **Step 1: Add the guard text directly under the team roster**

In `app/agents/definitions.py`, locate the `_ceo_persona()` block:

```python
YOUR TEAM — delegate using [DELEGATE:role] syntax:
  • Reinhard van Astrea  [DELEGATE:backend]  — Python, FastAPI, PostgreSQL, Redis, REST APIs
  • Emilia               [DELEGATE:frontend] — React, Next.js, TypeScript, HTML/CSS/JS
  • Beatrice             [DELEGATE:qa]       — Testing, security review, code quality
  • Otto Suwen           [DELEGATE:devops]   — Docker, Nginx, ports, deployment, new services
  • Maya                 [DELEGATE:browser]  — Job search, CV tailoring, browser automation
```

Add this paragraph immediately after the roster (before the `HOW YOU ROLL:`
section):

```python
YOUR TEAM — delegate using [DELEGATE:role] syntax:
  • Reinhard van Astrea  [DELEGATE:backend]  — Python, FastAPI, PostgreSQL, Redis, REST APIs
  • Emilia               [DELEGATE:frontend] — React, Next.js, TypeScript, HTML/CSS/JS
  • Beatrice             [DELEGATE:qa]       — Testing, security review, code quality
  • Otto Suwen           [DELEGATE:devops]   — Docker, Nginx, ports, deployment, new services
  • Maya                 [DELEGATE:browser]  — Job search, CV tailoring, browser automation

NEVER mention [DELEGATE:role] tag syntax inside a sentence or when describing
what you might do later (e.g. don't write "I'll get [DELEGATE:browser] Maya
on it" or "say the word and I'll kick off [DELEGATE:browser]"). Describe your
plan in plain words instead — talk about "looping in Maya" or "having the team
take a look", not the tag itself. Only output [DELEGATE:role] as the very
first thing on its own line, when you are delegating right now, for real.
```

- [ ] **Step 2: Verify the persona still renders correctly**

Run:
```bash
cd /home/subaru/projects/virtual-company && python3 -c "from app.agents.definitions import agent_persona; p = agent_persona('ceo'); assert 'NEVER mention [DELEGATE:role] tag syntax' in p; assert 'YOUR TEAM' in p; print('persona OK, length:', len(p))"
```

Expected: prints `persona OK, length: <some number>` with no assertion error.

- [ ] **Step 3: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/agents/definitions.py
git commit -m "fix(ceo): add persona guard against mentioning [DELEGATE:] in prose

Mirrors the existing SING-tag guard pattern. The CEO was observed writing
[DELEGATE:browser] inline inside casual sentences (priming itself off its
own team-roster formatting), which the parser then mistook for a real
directive. This is the persona-side half of the fix — the regex anchor
from the prior commit is the structural backstop."
```

---

### Task 3: Add a `gemini_safe_tags` allowlist to Maya's agent definition

**Files:**
- Modify: `app/agents/definitions.py:295-333` (Maya's `AGENT_DEFS["browser"]` entry)

- [ ] **Step 1: Add the field to Maya's entry**

In `app/agents/definitions.py`, find Maya's entry (currently lines ~295-333):

```python
    "browser": {
        "name":        "Maya",
        "title":       "Browser Automation Agent",
        "color":       "#00ff88",
        "avatar":      "MA",
        "description": "Job search, CV tailoring, and application automation via Playwright.",
        "persona":     _worker_persona(
```

Add the `gemini_safe_tags` key right after `"description"`:

```python
    "browser": {
        "name":        "Maya",
        "title":       "Browser Automation Agent",
        "color":       "#00ff88",
        "avatar":      "MA",
        "description": "Job search, CV tailoring, and application automation via Playwright.",
        "gemini_safe_tags": ["BROWSER_APPLY", "BROWSER_DISCOVER",
                             "BROWSER_COMPANY", "BROWSER_PROFILE_MATCH"],
        "persona":     _worker_persona(
```

- [ ] **Step 2: Verify it's reachable via `get_agent`**

Run:
```bash
cd /home/subaru/projects/virtual-company && python3 -c "from app.agents.definitions import get_agent; tags = get_agent('browser').get('gemini_safe_tags', []); assert tags == ['BROWSER_APPLY', 'BROWSER_DISCOVER', 'BROWSER_COMPANY', 'BROWSER_PROFILE_MATCH'], tags; print('OK:', tags)"
```

Expected: prints `OK: ['BROWSER_APPLY', 'BROWSER_DISCOVER', 'BROWSER_COMPANY', 'BROWSER_PROFILE_MATCH']`

- [ ] **Step 3: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/agents/definitions.py
git commit -m "feat(maya): declare gemini_safe_tags allowlist for browser tool tags

Lists the [BROWSER_*] tags that ARE safe and required to use on the Gemini
backend (they're parsed from Maya's final text response via call_browser_svc,
not Claude's live code-execution loop). This is the data half of the fix —
_build_gemini_prompt (next commit) reads it to stop blanket-suppressing
these tags."
```

---

### Task 4: Make `_build_gemini_prompt` carve an exception for agents with `gemini_safe_tags`

**Files:**
- Modify: `app/agents/executor.py:451-486` (`_build_gemini_prompt`)
- Test: `tests/test_executor_gemini.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_executor_gemini.py`:

```python
def test_gemini_prompt_carves_exception_for_agents_with_safe_tags():
    """Maya's prompt must explicitly permit her [BROWSER_*] tags, not blanket-ban them."""
    from app.agents.executor import _build_gemini_prompt

    prompt = _build_gemini_prompt("browser", "find backend roles and apply")

    # The exception must name her actual tags so Gemini doesn't fold them
    # into "or similar execution tool tags".
    assert "[BROWSER_APPLY:" in prompt
    assert "[BROWSER_DISCOVER:" in prompt
    assert "MUST use your role-specific action tags" in prompt
    # The blanket ban must still cover the Claude-only execution tags.
    assert "Do NOT output [BASH:], [READ:], [WRITE:], [DELEGATE:]" in prompt


def test_gemini_prompt_keeps_blanket_ban_for_agents_without_safe_tags():
    """An agent with no gemini_safe_tags gets the original blanket instruction, unchanged."""
    from app.agents.executor import _build_gemini_prompt

    prompt = _build_gemini_prompt("ceo", "what's the status of the deploy")

    assert "Do NOT output [BASH:], [READ:], [WRITE:]," in prompt
    assert "or similar execution tool tags" in prompt
    assert "MUST use your role-specific action tags" not in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/subaru/projects/virtual-company && python3 -m pytest tests/test_executor_gemini.py -k "safe_tags or blanket_ban" -v`

Expected: `test_gemini_prompt_carves_exception_for_agents_with_safe_tags` FAILS
(the current prompt has no "MUST use your role-specific action tags" text and
no per-tag mentions). `test_gemini_prompt_keeps_blanket_ban_for_agents_without_safe_tags`
should already PASS.

- [ ] **Step 3: Make `_build_gemini_prompt` agent-aware**

In `app/agents/executor.py`, replace the body of `_build_gemini_prompt`
(currently lines 451-486):

```python
def _build_gemini_prompt(agent_id: str, user_msg: str) -> str:
    """Prompt for Gemini API — conversational only, no tool syntax."""
    agent   = defs.get_agent(agent_id)
    persona = defs.agent_persona(agent_id)
    history = state.get_history(agent_id)

    # Strip tool-related instructions from persona for Gemini
    # (Gemini can't execute tools, so it just prints them as text)
    clean_persona = persona.split("AVAILABLE TOOLS:")[0] if "AVAILABLE TOOLS:" in persona else persona

    safe_tags = agent.get("gemini_safe_tags", [])
    if safe_tags:
        tag_list = ", ".join(f"[{t}:...]" for t in safe_tags)
        tool_note = (
            "IMPORTANT: You are responding via Gemini API (limited tool access). "
            "Do NOT output [BASH:], [READ:], [WRITE:], [DELEGATE:] tags — those "
            "require Claude's code execution and won't work here. However, you "
            f"MUST use your role-specific action tags ({tag_list}) exactly as "
            "defined in your persona above whenever the task calls for them — "
            "those ARE supported here and required to actually do the work."
        )
    else:
        tool_note = (
            "IMPORTANT: You are responding via Gemini API (limited tool access). "
            "Answer conversationally and helpfully. Do NOT output [BASH:], [READ:], "
            "[WRITE:], [DELEGATE:], or similar execution tool tags."
        )

    hist_str = "\n".join(
        f"{'User' if h['role'] == 'user' else agent['name']}: {_truncate_content(h['content'])}"
        for h in history[-(config.MAX_HISTORY):]
    )

    live_ctx = _build_context_block(agent_id, user_msg)
    return (
        f"{clean_persona}\n\n"
        f"{tool_note}\n"
        f"MANDATORY — you MUST use these tags in EVERY response:\n"
        f"  [SPEAK: your full reply | emotion: calm|excited|sad|whisper|energetic]  — REQUIRED for ALL responses\n"
        f"    Match emotion to context. Example: [SPEAK: That's done! | emotion: excited]\n"
        f"    If asked to sing: [SING: full lyrics | style: genre]\n"
        f"OPTIONAL — you CAN also use these tags:\n"
        f"  [GENERATE_IMAGE: description]  — generate an image\n"
        f"    Example: [GENERATE_IMAGE: A futuristic city skyline at sunset, cyberpunk neon lights]\n"
        f"  [EMAIL_USER:recipient@domain.com | Subject] body  — send an email to anyone\n"
        f"    Example: [EMAIL_USER:john@example.com | Hello from Shadow Garden] Hi John, just checking in!\n"
        f"  [EMAIL_USER:Subject] body  — send an email to the main user (no recipient = owner)\n"
        f"    Example: [EMAIL_USER:Task Complete] Your task has been finished.\n"
        f"{live_ctx}\n"
        f"Conversation History:\n{hist_str}\n\n"
        f"User: {user_msg}"
    )
```

(Only the tool-instruction block changed — the `MANDATORY`/`OPTIONAL` tag
sections and the trailing context/history/user lines are unchanged from the
original, just now interpolating `{tool_note}` instead of the hardcoded
"IMPORTANT..." string.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/subaru/projects/virtual-company && python3 -m pytest tests/test_executor_gemini.py -v`

Expected: all tests in the file PASS, including the two new ones.

- [ ] **Step 5: Run the full executor test suite to check for regressions**

Run: `cd /home/subaru/projects/virtual-company && python3 -m pytest tests/test_executor_gemini.py tests/test_maya_agent.py tests/test_backend_state.py -v`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/agents/executor.py tests/test_executor_gemini.py
git commit -m "fix(executor): stop Gemini prompt from blanket-banning Maya's tool tags

_build_gemini_prompt told every agent 'do NOT output ... or similar execution
tool tags', which Gemini read as covering Maya's [BROWSER_*] tags too — even
though those are parsed from her final text response (not Claude's live
execution loop) and work the same on any backend. Now agents that declare
gemini_safe_tags get an explicit carve-out naming their tags as required;
agents without the field keep the original blanket ban unchanged."
```

---

### Task 5: Live smoke-check (optional, gated on user approval)

**Files:** none (verification only)

- [ ] **Step 1: Confirm with the user before running**

This step drives a real WebSocket session against the running app and may
cause Maya to take real browser actions (and, if she gets far enough, submit
a real job application). Do NOT run this without the user explicitly saying
go — same gate as the original e2e test. If they decline or don't respond,
skip this task; Tasks 1-4 are already fully verified by their unit tests.

- [ ] **Step 2: If approved, run a scoped WS check**

Connect to `ws://127.0.0.1:3031/ws?model=claude`, send the CEO a message
asking it to delegate a job-search task to Maya, and confirm via the
streamed `tool_call` events (or by tailing `browser-svc` logs for `/discover`
or `/apply` requests) that Maya now actually emits a `[BROWSER_*]` tag instead
of narrating in prose — even if/when she's running on the Gemini backend
(check the `backend_status` event to confirm which backend is active).

Expected: at least one `tool_call` event for Maya with `tool_type` in
(`browser_discover`, `browser_apply`, `browser_company`, `browser_profile_match`),
and a corresponding non-health-check request in `browser-svc` logs.

- [ ] **Step 3: Report findings back to the user**

Summarize whether Maya now invokes her tools reliably on Gemini, and whether
any application actually went out (and if so, to where) — same reporting
discipline as the original e2e test.

---

## Self-Review Notes

- **Spec coverage:** Task 1 + 2 implement Fix 1 (anchored regex + persona
  guard) exactly as specified; Task 3 + 4 implement Fix 2 (allowlist +
  agent-aware prompt) exactly as specified; Task 5 covers the spec's
  "optionally re-run a scoped live WS test" testing note.
- **Placeholder scan:** No TBDs; every step shows the exact code/text/commands.
- **Type consistency:** `gemini_safe_tags` is introduced in Task 3 as a
  `list[str]` on the agent dict and consumed identically in Task 4 via
  `agent.get("gemini_safe_tags", [])` — names and shapes match.
