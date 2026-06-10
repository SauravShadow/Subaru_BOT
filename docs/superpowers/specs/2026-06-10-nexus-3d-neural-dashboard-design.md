# NEXUS 3D Neural Dashboard — Design Spec
**Date:** 2026-06-10  
**Status:** Approved  
**Replaces:** `app/static/index.html` + `app.js` + `style.css` (current plain-JS UI)

---

## Overview

A full-screen React Three Fiber dashboard that replaces the existing NEXUS UI. Six agent nodes float in 3D space with a hierarchical depth layout. Neural particle streams animate along edges connecting the CEO to each worker whenever a task is delegated. Clicking any node zooms the camera in and presents that agent's live terminal log and chat input as a DOM overlay.

Two additive backend events are required for node progress visualization (`worker_step`, `worker_checkpoint`) — defined in `2026-06-10-langgraph-transformation-design.md` Section 12. All existing events are unchanged. The UI degrades gracefully if these events are absent (progress ring stays at zero, NodeFlowPanel shows empty).

---

## Architecture & Data Flow

```
Browser
  └── React app (Vite build → app/static/)
        ├── NexusScene       (R3F Canvas, full screen)
        │     ├── Background (grid plane, floating particles, depth fog)
        │     ├── AgentNode × 6  (CEO + 5 workers as 3D icosahedron meshes)
        │     └── NeuralEdge × 5 (CEO → worker bezier particle streams)
        ├── AgentDetailView  (DOM overlay, shown on zoom-in)
        │     ├── TerminalLog (streaming output, auto-scroll, 500-line cap)
        │     └── ChatInput   (send message via WS)
        └── useNexusStore    (Zustand)
              └── WebSocket → parses events → updates store

FastAPI (unchanged except one SPA fallback route)
  ├── GET /         → serves app/static/index.html
  ├── GET /assets/* → serves Vite build assets
  └── WS  /ws       → existing protocol (no changes)
```

### WebSocket Event → Store Mapping

| WS event | Store mutation |
|---|---|
| `init` | Hydrate all agents + work queue |
| `thinking` | `agent.status = "thinking"` |
| `delegation` | `agent.status = "working"`, `edge.isActive = true` |
| `worker_done` | `agent.status = "done"`, `edge.isActive = false`, reset `stepCount` |
| `tool_call` | `agent.recentOutput.push(label)` *(legacy — kept for compat)* |
| `worker_step` | `agent.stepCount++`, `agent.recentSteps.push({step, tool, label})` (FIFO cap 20) |
| `worker_checkpoint` | `agent.checkpoints.push({index, summary, step, ts})` |
| `assistant` | `agent.recentOutput.push(content)` |
| `queue_update` | Update work queue in store |

### Agent store shape (additions)

```ts
interface AgentState {
  // existing fields unchanged
  id: string
  status: 'idle' | 'thinking' | 'working' | 'done'
  recentOutput: string[]

  // new fields for node progress
  stepCount: number                         // total tool calls this session
  recentSteps: Step[]                       // last 20 steps, FIFO
  checkpoints: Checkpoint[]                 // major milestones
}

interface Step {
  step: number
  tool: string
  label: string
  ts: number
}

interface Checkpoint {
  index: number
  summary: string
  step: number      // step count when checkpoint was saved
  ts: number
}
```

All new fields initialise to zero/empty on `init`. Reset to zero/empty on `worker_done` for that agent.

---

## Project Structure

```
virtual-company/
├── app/                        ← FastAPI (unchanged)
│   └── static/                 ← OUTPUT: vite build writes here
│       ├── index.html
│       └── assets/
│           ├── index-[hash].js
│           └── index-[hash].css
├── nexus-ui/                   ← NEW: Vite + React source
│   ├── package.json
│   ├── vite.config.ts          ← outDir: ../app/static, WS/API proxy for dev
│   ├── tsconfig.json
│   └── src/
│       ├── main.tsx
│       ├── store.ts            ← Zustand store + WS hook
│       ├── types.ts
│       └── components/
│           ├── NexusScene.tsx       ← R3F Canvas root
│           ├── AgentNode.tsx        ← per-agent 3D mesh + label + ProgressRing
│           ├── ProgressRing.tsx     ← arc overlay showing step count on node
│           ├── NeuralEdge.tsx       ← animated bezier particle stream
│           ├── Background.tsx       ← grid, particles, fog
│           ├── AgentDetailView.tsx  ← DOM overlay (terminal + chat)
│           └── NodeFlowPanel.tsx    ← checkpoint timeline inside detail view
```

---

## 3D Scene

### Agent Positions (hierarchical depth)

| Agent | Role | x | y | z |
|---|---|---|---|---|
| Subaru Natsuki | CEO | 0 | 0.5 | +4 |
| Reinhard | Backend | -3 | 0 | -1 |
| Emilia | Frontend | -2 | 0 | -3 |
| Beatrice | QA | 0 | 0 | -2 |
| Otto | DevOps | +2 | 0 | -1 |
| Maya | Browser | +3 | 0 | -3 |

Camera: position `(0, 2, 10)`, looking at origin. Workers form a shallow arc behind the CEO.

### Node Visual States

| Status | Color | Effect |
|---|---|---|
| `idle` | `#1e293b` | dim, static |
| `thinking` | `#7c3aed` | slow `emissiveIntensity` pulse (0.3 → 1.0, 2s cycle) |
| `working` | `#00f0ff` | fast pulse + outer halo ring |
| `done` | `#22c55e` | 1s green flash then returns to idle |

Node geometry: `IcosahedronGeometry`. CEO radius `0.9`, workers `0.6`. Floating `<Text>` (drei) below each node: agent name + role.

### Neural Edges

Each edge is a `QuadraticBezierLine` (drei) curving from CEO to the worker node.

- **Baseline:** thin `#1e293b` line, always visible
- **Active (`isActive=true`):** 3 staggered particle spheres (`r=0.08`, `#00f0ff`, emissive) ride the bezier path using `useFrame` with `t` offsets of `0`, `0.33`, `0.66`. Each loops `0→1` at 1.5s/cycle.

### Background

- `<gridHelper>` on XZ plane at `y=-4`, 40×40 units, cyan `#0ea5e9` at 40% opacity — digital floor
- 300 `<Points>` scattered in `[-20, 20]³` bounding box, slow drift `+y` via `useFrame`, wrap at top — floating data motes
- `<fog>` color `#050a14`, near `8`, far `40` — fades distant particles naturally
- `<ambientLight>` intensity `0.3` + `<pointLight>` at CEO position intensity `1.5` — command center spotlight

---

## Node Progress Visualization

### `ProgressRing` (3D scene, always visible)

Rendered inside `AgentNode` as a `<Ring>` geometry orbiting the icosahedron. Visible in the main 3D scene without clicking — gives the CEO a live at-a-glance status for every worker.

**Geometry:** `RingGeometry` with inner radius `node_radius + 0.12`, outer radius `node_radius + 0.22`. Faces the camera via `billboard` (drei).

**Visual behaviour:**

| Condition | Ring appearance |
|---|---|
| `stepCount === 0` | invisible (`visible={false}`) |
| `stepCount > 0, status === "working"` | cyan `#00f0ff`, opacity 0.7, slow clockwise rotation via `useFrame` |
| New `worker_checkpoint` received | 0.4s white flash (`#ffffff`) then back to cyan |
| `status === "done"` | green `#22c55e`, static, fades out after 3s |

**Step label:** `<Text>` (drei) positioned above the ring, billboard-aligned. Content: `"N steps"` when `stepCount > 0 && stepCount < 10`, `"N steps · C ✓"` when checkpoints exist. Font size `0.13`. Color matches ring.

**Checkpoint pulse:** On every `worker_checkpoint` event, a short `<ring>` burst animation plays — ring briefly scales to `1.4×` over 200ms then snaps back. Implemented via `@react-spring/three` `useSpring`.

---

### `NodeFlowPanel` (inside `AgentDetailView`)

A vertical scrollable timeline rendered above the terminal log in the detail overlay. Shows exactly what the worker has done and when each milestone landed.

**Layout inside `AgentDetailView`:**
```
┌─────────────────────────────────────────────────────┐
│  ← Back       REINHARD  •  Backend Engineer          │
│  ─────────────────────────────────────────────────── │
│                                                      │
│  NODE FLOW  ────────────────────────── 6 steps · 2 ✓ │
│                                                      │
│  ◆ Checkpoint 1 · step 3              "Scaffolded    │
│  │                                     API routes"   │
│  ○ step 4  bash        Running pytest               │
│  ○ step 5  write       /workspace/app/routes.py     │
│  ◆ Checkpoint 2 · step 6              "All tests pass│
│  │                                     API live :8090│
│  ○ step 6  bash        curl health check            │
│                                                      │
│  [streaming terminal log below]                      │
└─────────────────────────────────────────────────────┘
```

**Item types:**

- **Step row** (`○`): dim circle, `tool` in cyan, `label` in muted white. Tool icons: `⚙` bash, `📖` read, `✍` write, `✏` edit, `🌐` web, `🎫` jira, `🔍` browser.
- **Checkpoint row** (`◆`): green diamond, bold step number, summary text in green. A faint horizontal rule separates it from steps below.
- **Connecting line**: 1px `#1e293b` vertical line between items.

**Behaviour:**
- Auto-scrolls to bottom as new steps arrive (same behaviour as terminal log).
- User can scroll up freely.
- If `recentSteps` and `checkpoints` are both empty: panel hidden, no empty state shown.
- Max height: `180px`, scrollable. Does not push terminal log below fold.

---

## Agent Detail View

**Trigger:** `selectAgent(id)` in Zustand store.

**Camera animation:** `CameraControls` ref (drei) animates camera to `0.5` units in front of the clicked node over `800ms` spring curve. 3D scene stays mounted, blurred (`filter: blur(4px)`) behind overlay.

**Overlay layout:**
```
┌─────────────────────────────────────────────┐
│  ← Back       REINHARD  •  Backend Engineer  │
│  ─────────────────────────────────────────── │
│                                               │
│  [streaming terminal log, monospace]          │
│  > Tool: bash — running pytest...             │
│  > all tests passing                          │
│                                               │
│  ─────────────────────────────────────────── │
│  [ Send message to Reinhard...    ]  [Send]   │
└─────────────────────────────────────────────┘
```

- Background: `#0d1117`, terminal text `#e2e8f0`, tool calls `#00f0ff`
- Auto-scrolls to bottom on new output; user can scroll up freely
- Chat input sends `{"type": "message", "agent": "<id>", "text": "..."}` via WS
- CEO node: input placeholder "Talk to Subaru...", `"agent": "ceo"`
- Back button: reverses camera animation, unmounts overlay
- Live updates continue while overlay is open (store subscription stays active)

---

## FastAPI Integration

### SPA Fallback Route

Add to `app/api/router.py`:
```python
from fastapi.responses import FileResponse

@router.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    return FileResponse("app/static/index.html")
```

This must be the last route registered to avoid shadowing API endpoints.

### Build Command
```bash
cd nexus-ui && npm run build
# Writes to ../app/static/ — FastAPI StaticFiles mount picks it up immediately
```

### Dev Workflow
```bash
cd nexus-ui && npm run dev   # Vite on :5173, proxies /ws and /api to 127.0.0.1:3031
```

### Dependencies
```json
{
  "@react-three/fiber": "^8",
  "@react-three/drei": "^9",
  "three": "^0.165",
  "zustand": "^4",
  "@react-spring/three": "^9",
  "react": "^18",
  "react-dom": "^18"
}
```
Bundle: ~400KB gzipped. No Dockerfile changes, no new ports.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| WS disconnect | Exponential backoff reconnect (1s → 2s → 4s → max 30s). Corner badge shows `● OFFLINE`. All nodes dim to idle. |
| Worker stuck `working` | Client-side 5-minute timeout per active task resets node to `idle`. ProgressRing fades out. |
| `worker_step` / `worker_checkpoint` absent (old backend) | ProgressRing stays invisible, NodeFlowPanel hidden. Degrades gracefully, no errors. |
| App refresh while in detail view | `selectAgent` state not persisted — boots directly into 3D map, no broken camera. |
| Output stream overflow | `recentOutput[]` capped at 500 lines per agent (FIFO drop). |
| Empty `init` payload | Scene renders all 6 nodes using hardcoded positions with `idle` status. Nodes never missing. |
| Build failure | `vite build` only overwrites `app/static/` on success. Failed build leaves previous build intact. |

---

## Out of Scope

- Voice input/output (existing Bark TTS integration is unaffected — CEO still speaks via `[SPEAK:]` tags processed server-side)
- Drag-to-reposition nodes (camera orbit replaces the need to rearrange)
- Mobile/touch support
- Dark/light theme toggle
