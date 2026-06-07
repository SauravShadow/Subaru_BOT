# Fix: Stray `[DELEGATE:]` tag parsing & Maya's missing `[BROWSER_*]` tool tags on Gemini

## Background

A live end-to-end test (CEO → Maya delegation, real WebSocket session) surfaced two
agent-behavior bugs that block real job applications from ever going out:

1. The CEO sometimes writes `[DELEGATE:browser]` inside ordinary descriptive prose
   (e.g. *"Say the word and I'll get [DELEGATE:browser] Maya moving on it right
   away."*). The delegation parser fires on the tag regardless of context, creating
   a garbage work item with task text like `"Maya moving on it right away."`
2. When Maya (the browser-automation agent) runs on the Gemini backend, she never
   emits her `[BROWSER_APPLY:]` / `[BROWSER_DISCOVER:]` / etc. tags — she narrates in
   prose instead ("I'll write a script to tailor the CV...") and finishes with
   `[DONE: 0 applied, 0 skipped]`. No request ever reaches `browser-svc`.

Both stem from the same class of problem: bracket tag instructions get
misread or contradicted depending on surrounding context, and nothing in the
system disambiguates "real instruction" from "text that merely mentions the
tag."

## Fix 1 — Stray `[DELEGATE:role]` tags in CEO prose

### Root cause
- `app/agents/definitions.py:15-20` prints the team roster with the tag glued
  directly to each name: `• Maya  [DELEGATE:browser]  — Job search, ...`. This
  primes the model to reproduce `[DELEGATE:browser] Maya` as a unit in casual
  conversation.
- `app/services/delegation.py:4-6`'s `_DELEGATE_RE` has no anchor — it matches
  `[DELEGATE:role]` anywhere in the response text, real directive or not:
  ```python
  _DELEGATE_RE = re.compile(
      r'\[DELEGATE:(\w+)\]\s*(.*?)(?=\[DELEGATE:|\[EMAIL_USER:|$)', re.DOTALL
  )
  ```

### Change
**A. Anchor the regex to line-start** (structural signal that distinguishes a
real directive from an inline mention — a real delegation is, by the persona's
own instructions, the start of a new line/paragraph):
```python
_DELEGATE_RE = re.compile(
    r'^\[DELEGATE:(\w+)\]\s*(.*?)(?=^\[DELEGATE:|^\[EMAIL_USER:|\Z)',
    re.DOTALL | re.MULTILINE
)
```
`^` in `re.MULTILINE` matches at the start of any line, so a tag that opens its
own line still parses correctly; one embedded mid-sentence ("...I'll get
[DELEGATE:browser] Maya...") no longer matches.

**B. Add a persona guard**, mirroring the existing SING-tag guard
(`definitions.py:62`, *"NEVER write lyrics as plain text. NEVER say 'I'll
sing...'. Just output the tag directly."*). Add a parallel rule directly under
the team roster in `_ceo_persona()`:
```
NEVER mention [DELEGATE:role] tag syntax inside a sentence or when describing
what you might do later (e.g. don't write "I'll get [DELEGATE:browser] Maya
on it"). Describe your plan in plain words. Only output [DELEGATE:role] on
its own line, as the first thing on that line, when you are delegating right
now.
```

This is defense in depth: the persona guard reduces how often the model
produces the tag in prose at all; the anchored regex is the structural
backstop that makes a slip-up harmless even if the model still does it.

### Why this approach (vs. the alternatives considered)
- A persona-only fix relies entirely on model compliance with no structural
  backstop — the same class of "agent didn't follow instructions" problem
  we're trying to fix in Bug 2.
- A heuristic post-filter (rejecting matches that "look like sentence
  fragments") is fragile pattern-matching on natural language and will rot.
- Anchoring + a persona rule reuses a pattern already proven to work
  (SING tags) and adds a cheap, durable structural guarantee.

## Fix 2 — Maya never emits `[BROWSER_*]` tags on the Gemini backend

### Root cause
`_build_gemini_prompt` (`app/agents/executor.py:451-486`) sends every agent —
regardless of role — this blanket instruction:
```
IMPORTANT: You are responding via Gemini API (limited tool access).
Answer conversationally and helpfully. Do NOT output [BASH:], [READ:], [WRITE:],
[DELEGATE:], or similar execution tool tags.
```
Maya's persona (which is preserved — her tags live in her custom `extra` text,
not the stripped `AVAILABLE TOOLS:` section) tells her to use
`[BROWSER_APPLY:]` / `[BROWSER_DISCOVER:]` / `[BROWSER_COMPANY:]` /
`[BROWSER_PROFILE_MATCH]`. Gemini reads "or similar execution tool tags" as
covering hers too, and suppresses them — even though these specific tags are
parsed from her final text response (`parse_tool_call` in `tools.py:277-303`
→ `call_browser_svc`) and work identically regardless of backend; they don't
require Claude's live code-execution loop.

### Change
Add a small per-agent allowlist of tags that ARE safe (and required) to use on
Gemini, and have `_build_gemini_prompt` build an explicit exception into the
instruction instead of a blanket ban.

In `app/agents/definitions.py`, add to Maya's entry:
```python
"browser": {
    ...
    "gemini_safe_tags": ["BROWSER_APPLY", "BROWSER_DISCOVER",
                         "BROWSER_COMPANY", "BROWSER_PROFILE_MATCH"],
    ...
}
```

In `_build_gemini_prompt` (`executor.py`), read that field and adjust the
instruction text:
```python
agent = defs.get_agent(agent_id)
safe_tags = agent.get("gemini_safe_tags", [])
if safe_tags:
    tag_list = ", ".join(f"[{t}:...]" for t in safe_tags)
    tool_note = (
        "IMPORTANT: You are responding via Gemini API (limited tool access). "
        "Do NOT output [BASH:], [READ:], [WRITE:], [DELEGATE:] tags — those "
        "require Claude's code execution and won't work here. However, you "
        f"MUST use your role-specific action tags ({tag_list}) exactly as "
        "defined in your persona above whenever the task calls for them — "
        "those ARE supported and required."
    )
else:
    tool_note = (
        "IMPORTANT: You are responding via Gemini API (limited tool access). "
        "Answer conversationally and helpfully. Do NOT output [BASH:], [READ:], "
        "[WRITE:], [DELEGATE:], or similar execution tool tags."
    )
```
…and substitute `tool_note` for the existing hardcoded instruction block at
`executor.py:469-471`.

This keeps the field generic (`gemini_safe_tags`) so any future agent with
custom Gemini-compatible action tags can opt in the same way, without
special-casing "browser" by name in the executor.

### Why this approach (vs. the alternatives considered)
- Forcing Maya onto Claude always (bypassing classification) throws away the
  cost/speed benefit of Gemini and leaves her stuck with no fallback at all
  if Claude's quota is exhausted — which is the exact situation that routed
  her to Gemini in the first place.
- A retry/nudge loop ("you described an action but didn't tag it — try
  again") is general-purpose but adds loop/infinite-retry complexity to paper
  over what is, at root, a contradictory prompt. Fixing the contradiction
  directly is simpler and removes the failure mode rather than working around
  it.

## Testing

- **Fix 1**: Unit-test `parse_delegations` with three inputs: (a) a real
  directive at line-start → still parses to a work item; (b) the same tag
  embedded mid-sentence ("I'll get [DELEGATE:browser] Maya on it") → no match;
  (c) multiple real directives across lines → both parse independently with
  correct task-text boundaries (the existing lookahead behavior must still
  work under `MULTILINE`).
- **Fix 2**: Unit-test `_build_gemini_prompt` for an agent with
  `gemini_safe_tags` set (Maya) vs. one without (e.g. CEO) — assert the
  resulting prompt text contains the tag-specific exception for Maya and the
  original blanket ban for CEO.
- Optionally re-run a scoped live WS test (CEO → Maya delegation on the Gemini
  backend) to confirm Maya now emits a real `[BROWSER_DISCOVER:]` /
  `[BROWSER_APPLY:]` tag and `browser-svc` receives a non-health-check request
  — gated on the user explicitly approving a real submission, same as before.

## Out of scope

- Any change to `_classify_model` / backend routing logic.
- Any change to other tag types (`[BASH:]`, `[EMAIL_USER:]`, etc.) beyond the
  `[DELEGATE:]` regex anchor — they weren't observed to misfire in testing and
  changing them isn't needed to fix the two reported bugs.
- Retry/nudge mechanisms for missing tool calls (considered and rejected above).
