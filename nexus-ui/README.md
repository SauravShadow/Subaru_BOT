# nexus-ui/ — React + Three.js Frontend

Vite + React 18 + @react-three/fiber SPA. Builds to `app/static/` which is
served by FastAPI. All backend communication goes through a single WebSocket
(`/ws?model=claude`) and REST calls to `/api/*` on the same origin.

**Build**: `cd nexus-ui && npm run build` → outputs to `../app/static/`.
**Dev**: `npm run dev` (port 5173, proxies WS to container).

---

## Zustand Store (`src/store.ts`)

Single store: `useNexusStore`. The WebSocket module-level singleton is outside
Zustand to avoid churn from audio events.

### Store Shape

```typescript
interface NexusStore {
  // Agent graph state
  agents: Record<string, AgentState>   // agent_id → {id, name, role, status, recentOutput, stepCount, recentSteps, checkpoints}
  edges: EdgeState[]                    // [{from: "ceo", to: worker_id, isActive: bool}]
  selectedAgent: string | null          // which agent's detail panel is open

  // WebSocket
  wsStatus: 'connected' | 'offline'
  wsModel: WsModel                      // 'claude' | 'gemini' | 'tgpt'

  // Work tracking
  workQueue: WorkQueueItem[]            // [{id, task, status, agent}] — from queue_update events

  // Notifications (SmartIsland)
  notifications: Notification[]         // rolling last 10; types: done|delegation|queue|message|routine|email|approval|system

  // UI panels
  islandExpanded: boolean
  islandTab: 'notifications' | 'queue' | 'active'
  browserView: BrowserView | null       // {image: base64, mime, url, caption, ts}
  browserVisible: boolean
  designPreviewTs: number | null        // timestamp of last update → triggers panel open
  designPreviewVisible: boolean
  pendingApprovals: number              // counter for OPS button badge
  lastErrorTs: number | null            // triggers ErrorFlash component
  opsRequest: { tab: OpsTab; ts: number } | null  // triggers OpsDrawer to open on specific tab
}
```

### AgentState

```typescript
interface AgentState {
  id: string
  name: string              // e.g. "Reinhard van Astrea"
  role: string              // e.g. "Backend Engineer"
  status: 'idle' | 'thinking' | 'working' | 'done'
  recentOutput: string[]    // last 500 lines (text + "Tool: label" entries)
  stepCount: number         // current step number from worker_step events
  recentSteps: Step[]       // last 20: {step, tool, label, ts}
  checkpoints: Checkpoint[] // all: {index, summary, step, ts}
}
```

### Key Store Actions

```typescript
selectAgent(id | null)          // opens/closes AgentDetailView
openOps(tab)                    // sets opsRequest → NexusScene opens OpsDrawer
setWsStatus('connected'|'offline')
resetAgentStatus(id)            // resets to 'idle' (5-min stuck guard)
setIslandExpanded(bool)
setIslandTab(tab)
setBrowserVisible(bool)
setDesignPreviewVisible(bool)
setPendingApprovals(n)
handleEvent(event)              // main event dispatcher — called from WS onmessage
```

---

## WebSocket Integration (`src/store.ts`)

Module-level singleton — not in Zustand to prevent re-renders on audio events.

```typescript
connectWebSocket(model = 'claude'): void
sendWsMessage(data: Record<string, unknown>): void
```

Reconnects with exponential backoff (1s → 30s max) on `onclose`.

**Audio events** bypass Zustand entirely:
```typescript
onAudioEvent(cb: (base64: string, mode: string) => void)
offAudioEvent(cb)
onSpeechFallback(cb: (text: string) => void)
offSpeechFallback(cb)
```

Audio events go to `_audioListeners`; speech fallback fires only when
`bark_ok === false` on an `assistant` event (Bark audio absent → Web Speech fallback).

**Stuck task guard**: On `delegation`, starts a 5-minute timer to
`resetAgentStatus(agentId)`. Cleared on `worker_done` or `done`.

---

## WebSocket Event → UI Mapping

| WS Event | Store update | UI effect |
|----------|-------------|-----------|
| `init` | Rebuilds `agents`, `edges` from server list | 3D nodes populate |
| `thinking` | `agents.ceo.status = 'thinking'` | CeoNode pulses |
| `delegation` | Worker `status = 'working'`, edge `isActive = true`, adds notification | NeuralEdge animates; AgentNode glows |
| `worker_step` | `agents[id].stepCount`, `.recentSteps` updated | NodeFlowPanel step counter |
| `worker_checkpoint` | `agents[id].checkpoints` appended | NodeFlowPanel checkpoint list |
| `worker_done` | Worker `status = 'done'`, edge `isActive = false`, adds notification | NeuralEdge dims |
| `done` | `agents.ceo.status = 'idle'` | CeoNode returns to idle |
| `queue_update` | `workQueue` replaced | SmartIsland queue tab |
| `assistant` | `agents[id].recentOutput` appended | AgentDetailView terminal scrolls |
| `audio` | Fires `_audioListeners` (bypasses Zustand) | useVoice AudioQueue plays WAV |
| `error` | Agent `status = 'idle'`, `lastErrorTs` set, adds notification | ErrorFlash shows; SmartIsland notif |
| `backend_switch` / `backend_status` | `wsModel` updated | ModelPill indicator changes |
| `browser_navigated` | `browserView` updated, `browserVisible = true` | BrowserViewport shows screenshot |
| `browser_result` | Adds notification | SmartIsland notif |
| `design_preview_updated` | `designPreviewTs` set, `designPreviewVisible = true` | DesignPreviewPanel opens |
| `routine_completed` | Adds notification | SmartIsland notif |
| `standup` | Adds notification | SmartIsland notif |
| `email_sent` | Adds notification | SmartIsland notif |
| `source_file_modified` | Adds notification | SmartIsland notif |
| `approval_requested` | Adds notification, `pendingApprovals++` | OPS button badge |
| `approval_applied` / `approval_denied` | Adds notification, `pendingApprovals--` | OPS button badge |
| `tool_call` | `recentOutput` appended with `"Tool: {label}"` | AgentDetailView terminal |

---

## Component Map

### Root: `NexusScene` (`components/NexusScene.tsx`)
Top-level layout. Contains everything: Three.js Canvas + all DOM overlays.
Mounts: `ReactorRing`, `CeoNode`, `AgentNode` (×N), `NeuralEdge` (×N),
`EdgeTaskLabel`, `HoloBrowser` (browser agent only), `Background`, `PostProcessing`
inside the Canvas. Outside Canvas: `CommandBar`, `SmartIsland`, `ModelPill`,
`BrowserViewport`, `DesignPreviewPanel`, `SystemVitals`, `ErrorFlash`, `HudFrame`,
`OpsDrawer`, `AgentDetailView`, `HoverCard`, `CommandPalette`, `BootOverlay`.

### 3D (inside Canvas, React Three Fiber)

| Component | Purpose |
|-----------|---------|
| `CeoNode` | CEO sphere at CEO_POSITION [0, 0.5, 4]; pulses when `isSpeaking` |
| `ReactorRing` | 48 animated bars around CEO; rotation/activity scales with busy agent count; shows HH:MM clock |
| `AgentNode` | Worker sphere at fixed or computed positions; glows on `working` status |
| `NeuralEdge` | Animated line CEO→worker; brightens when `edge.isActive` |
| `EdgeTaskLabel` | Billboard text showing current task label on active edges |
| `HoloBrowser` | Holographic browser frame at browser agent position |
| `Background` | Particle field / scene background |
| `PostProcessing` | Bloom + vignette post-processing effects |
| `CameraDirector` | Auto-pans camera to focused agent on `selectAgent` change |

**Positions**: Fixed in `AGENT_POSITIONS` (`types.ts`). Custom/hired agents placed
on a 200° arc via `workerPosition(index, total)`.

### DOM Overlays (above Canvas)

| Component | Position | Purpose |
|-----------|----------|---------|
| `CommandBar` | Bottom center (fixed) | Main input: text + voice, agent target picker, send to WS |
| `SmartIsland` | Bottom right (fixed) | Collapsible panel: notifications / work queue / active workers |
| `AgentDetailView` | Right panel (fixed) | Opened when `selectedAgent != null`; shows terminal output, step list, voice input |
| `OpsDrawer` | Left slide-in (fixed) | Tabs: routines, skills, approvals, email-tasks, team (hire/fire) |
| `ModelPill` | Top left (fixed) | Shows current backend (claude/gemini/tgpt) + connection status |
| `BrowserViewport` | Floating panel | Shows `browserView.image` from `browser_navigated` events |
| `DesignPreviewPanel` | Floating panel | iframe to `/static/previews/index.html` |
| `SystemVitals` | Top right (fixed) | Storage % + active agent count |
| `ErrorFlash` | Full-screen flash | Triggered by `lastErrorTs` change |
| `HudFrame` | Fixed corners | Decorative HUD frame overlay |
| `BootOverlay` | Full-screen | Shows on initial load, fades once WS connects |
| `HoverCard` | Mouse-following | Agent info card on 3D node hover |
| `CommandPalette` | Center modal | Keyboard shortcut launcher (Cmd+K) |
| `NodeFlowPanel` | Inside AgentDetailView | Step counter, checkpoint list for active worker |

---

## Voice System (`hooks/useVoice.ts`)

**Module-level singletons** (shared across all `useVoice` instances to prevent
double-playback when multiple components are mounted):

```typescript
_ttsEnabled: boolean           // persisted in localStorage('nexus-tts-enabled')
_speakingSubs: Set<fn>         // pub/sub for isSpeaking state
_ttsSubs: Set<fn>              // pub/sub for ttsEnabled state
AudioQueue                     // sequential WAV playback queue
_playbackInit: boolean         // guards one-time registration
```

**AudioQueue**: Sequential. `push(base64, mode)` adds to queue; `_next()` decodes
base64 → Blob → Audio element → plays via Web Audio API. On `ended`, calls `_next()`.

**Initialization** (`_initPlaybackOnce()`): Called on first `useVoice` mount.
Registers `onAudioEvent` → `AudioQueue.push()` and `onSpeechFallback` → `window.speechSynthesis.speak()`.
Web Speech fallback only fires if `AudioQueue._playing == false` (Bark audio wins).

**Per-instance microphone** (`SpeechRecognition`): Each `useVoice` call gets its
own microphone (since only one input should capture voice at a time).

```typescript
const { isListening, isSpeaking, ttsEnabled, hasSpeechRecognition,
        startListening, stopListening, toggleTts } = useVoice(agentId, onTranscript)
```

`onTranscript(text)` called with recognized speech → caller sends WS message.

**Bark → Web Speech fallback logic** (in `store.ts` WS `onmessage`):
```
if (event.type === 'assistant' && event.bark_ok === false) → fire _speechListeners
if (event.type === 'audio') → fire _audioListeners (AudioQueue)
```
Streaming token chunks (no `bark_ok` field) → no TTS. Only the pipeline's finalized
`assistant` message with `bark_ok === false` triggers Web Speech.

---

## How to Add a New UI Panel

1. Create `nexus-ui/src/components/MyPanel.tsx` as a fixed-position React component.
2. Add any needed state to the Zustand store interface and initial state in `store.ts`.
3. If the panel responds to a new WS event, add a case in `handleEvent()` in `store.ts`.
4. Import and mount `<MyPanel />` in `NexusScene.tsx` outside the `<Canvas>` block.
5. `npm run build` to update `app/static/`.

## How to Add a New Event Handler

1. Backend: emit `{type: "my_event", ...fields}` via `broadcast_event()` or `send()`.
2. Frontend: add a `case 'my_event':` in `handleEvent()` in `store.ts`.
3. Update relevant store fields and return the new state.
4. Any component subscribed to those store fields re-renders automatically.

## Tech Stack

| Library | Version | Purpose |
|---------|---------|---------|
| React | 18 | UI framework |
| @react-three/fiber | — | Three.js React renderer |
| @react-three/drei | — | 3D helpers (Billboard, Text, CameraControls, etc.) |
| Three.js | — | WebGL 3D |
| Zustand | — | State management |
| Vite | — | Build tool + dev server |
| TypeScript | — | Type safety |
