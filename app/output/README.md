# app/output/ — Output Pipeline

Post-processes every LLM response by scanning for registered `[TAG: ...]` patterns,
dispatching each to a handler, stripping the raw tags from display text, and
emitting a single `{type: "assistant"}` WebSocket message with a `bark_ok` flag.

---

## Pipeline (`pipeline.py`)

**Entry point**:
```python
async def process(text: str, agent_id: str, send: Sender) -> str:
```

**Flow**:
1. Loads the handler registry via `registry.get_registry()` (lazy singleton).
2. For each `(tag_name, handler)` in registry:
   - Finds all `handler.PATTERN` matches in `text`.
   - For each match: calls `handler.handle(args, agent_id, send) -> (display_text, bark_ok)`.
     - If handler has 2 capture groups, joins them with `\x00` separator.
     - `display_text` replaces the raw tag in display output (may be empty string).
     - `bark_ok=True` means the handler delivered audio to the client.
   - Replaces tag in display string with handler's `display_text`.
3. Sends a single `{type: "assistant", agent: agent_id, message: {content: [{type: "text", text: display}]}, bark_ok: bool}` event.
4. Returns the cleaned display string.

**Called from**:
- `app/graph/nodes/ceo.py` — after CEO LLM call
- `app/graph/nodes/output.py` — after each worker's LLM result
- `app/api/websocket.py` — in `_run_direct()` for direct agent chat

**Not called from**:
- `app/agents/runner.py` — runner returns raw text; callers own pipeline invocation.

---

## Registry (`registry.py`)

Lazy singleton mapping tag names → handler modules.

```python
def get_registry() -> dict:
    # Returns on first call, then cached in _registry
    {
        "SPEAK":                 speak,
        "SING":                  sing,
        "GENERATE_IMAGE":        image,
        "EMAIL_USER":            email_handler,
        "BROWSER_APPLY":         browser_apply,
        "BROWSER_DISCOVER":      browser_discover,
        "BROWSER_COMPANY":       browser_company,
        "BROWSER_PROFILE_MATCH": browser_profile_match,
    }
```

`REGISTRY: dict = {}` module-level alias used in tests: `patch.dict("app.output.registry.REGISTRY", ...)`.

---

## Handler Interface

Each handler module in `app/output/handlers/` must expose:

```python
TAG: str                    # e.g. "SPEAK"
PATTERN: re.Pattern         # compiled regex with 1 or 2 capture groups
                            # 1 group:  args = match.group(1)
                            # 2 groups: args = match.group(1) + "\x00" + match.group(2)

async def handle(
    args: str,
    agent_id: str,
    send: Sender,           # async (dict) -> None
) -> tuple[str, bool]:
    # Returns (display_text, bark_ok)
    # display_text: replaces the raw tag in output (empty string removes it)
    # bark_ok: True if audio was successfully sent to client
```

---

## Existing Tags

### SPEAK (`handlers/speak.py`)
```
[SPEAK: text | emotion: calm|excited|sad|whisper|energetic]
```
Sends text to `bark_client.speak(text, emotion)` → base64 WAV.
Emits `{type: "audio", mode: "speak", data: base64}` WS event.
Returns `(text, True)` if bark-svc responded, `(text, False)` if unavailable.
The frontend then uses Web Speech API as fallback when `bark_ok == False`.

### SING (`handlers/sing.py`)
```
[SING: lyrics | style: genre description]
```
Sends to `bark_client.sing(lyrics, style)` → base64 WAV.
Emits `{type: "audio", mode: "sing", data: base64}`.

### GENERATE_IMAGE (`handlers/image.py`)
```
[GENERATE_IMAGE: description of image]
```
Generates image (implementation details in handlers/image.py).
Emits `{type: "assistant", agent, message: {content: [{type: "image", ...}]}}`.

### EMAIL_USER (`handlers/email.py`)
```
[EMAIL_USER: recipient@domain.com | Subject] body text
[EMAIL_USER: Subject] body text   ← sends to config.USER_EMAIL
```
Pattern has 2 capture groups (header, body), joined with `\x00` separator.
Parses `header` to extract optional recipient and subject.
Calls `email_svc.send_mail(subject, body, to=recipient)`.
Emits `{type: "email_sent", subject, ok, error}` WS event.
Returns `("", False)` — removes tag from display, no audio.

### BROWSER_APPLY (`handlers/browser_apply.py`)
```
[BROWSER_APPLY: https://job-url]
```
Calls `browser_svc.call_browser_svc("browser_apply", {"url": ...})`.
Proxies to browser-svc at `BROWSER_SVC_URL/browser/apply`.

### BROWSER_DISCOVER (`handlers/browser_discover.py`)
```
[BROWSER_DISCOVER: keywords | platform | location]
```
Calls browser-svc discover endpoint. Platform: "linkedin", "indeed", "naukri".

### BROWSER_COMPANY (`handlers/browser_company.py`)
```
[BROWSER_COMPANY: Company Name]
```
Calls browser-svc company careers search endpoint.

### BROWSER_PROFILE_MATCH (`handlers/browser_profile_match.py`)
```
[BROWSER_PROFILE_MATCH]
```
Uses target_companies from browser-svc profile; visits each careers page.

---

## Tags NOT in the Output Pipeline

These tags are parsed elsewhere:

| Tag | Parser | Location |
|-----|--------|---------|
| `[DELEGATE: agent]` | `parse_delegations_from_response()` | `app/graph/nodes/ceo.py` |
| `[ARTIFACT: name \| path]` | `_extract_artifacts()` | `app/graph/nodes/output.py`, `workers/base.py` |
| `[DONE: summary]` | `_extract_summary()` | `app/graph/nodes/output.py`, `api/websocket.py` |

These are consumed by the graph routing logic, not the output pipeline.

---

## How to Add a New [TAG] Handler

1. Create `app/output/handlers/mytag.py`:
   ```python
   import re
   import logging
   from typing import Callable, Awaitable

   logger  = logging.getLogger(__name__)
   TAG     = "MY_TAG"
   PATTERN = re.compile(r'\[MY_TAG:\s*(.*?)\]', re.DOTALL)
   Sender  = Callable[[dict], Awaitable[None]]

   async def handle(args: str, agent_id: str, send: Sender) -> tuple[str, bool]:
       # args = match.group(1) from PATTERN
       # Do the work...
       await send({"type": "my_event", "data": args})
       return ("", False)  # or (display_text, True) if audio was sent
   ```

2. Register in `app/output/registry.py`:
   ```python
   from app.output.handlers import mytag
   _registry = {
       ...
       "MY_TAG": mytag,
   }
   ```

3. Add `[MY_TAG: ...]` instructions to agent personas in `definitions.py` so
   agents know the syntax is available.

4. The pipeline auto-discovers new entries on first call after import; no restart
   needed if uvicorn `--reload` picks up the changes.
