# NEXUS Neural Command Center — Full Redesign Spec

**Date:** 2026-06-11
**Status:** Approved
**Supersedes:** `2026-06-10-nexus-3d-neural-dashboard-design.md` (visual + feature gaps)
**Approach:** B — `@react-three/postprocessing` GPU bloom + DOM glassmorphic panels

---

## Overview

A full-immersion redesign of the NEXUS React Three Fiber dashboard. The visual theme is **Neural Command Center** — the scene feels like being inside a living brain. CEO Subaru Natsuki is a golden arc reactor at the command center's heart, radiating light that reflects off worker icosahedra. Neural edges pulse with agent-specific identity colors. Clicking a node shatters it and materializes a glassmorphic hexagonal panel. A command palette (⌘K), smart island, push-to-talk voice, and model pill complete the feature set.

All existing WS event handling is preserved. New WS events (`backend_switch`, `queue_update`, `tool_call`) are wired. Existing bugs (broken `done` timeout, curve recreation per frame, stale edges on reconnect, missing `queue_update` handler) are fixed inline.

---

## Architecture

### New File Structure

```
nexus-ui/src/
├── main.tsx                    ← unchanged
├── store.ts                    ← additions: workQueue, wsModel, notifications, resetAgentStatus, 4 new event cases
├── types.ts                    ← additions: WorkQueueItem, Notification, WsModel
│
├── components/
│   ├── NexusScene.tsx          ← rewrite: postprocessing, HUD layer, ⌘K listener, canvas blur on select
│   ├── AgentNode.tsx           ← rewrite: shatter animation, hover trigger, identity colors, fixed done timeout
│   ├── CeoNode.tsx             ← NEW: arc reactor (nested tori + core sphere + audio waveform ring)
│   ├── NeuralEdge.tsx          ← patch: useMemo curve, reverse burst, idle heartbeat, agent identity color
│   ├── Background.tsx          ← rewrite: cortical wave floor shader, turbulent 3-class particles, 3-point lights
│   ├── AgentDetailView.tsx     ← rewrite: hex-clip glassmorphic panel, entrance animation, voice button
│   ├── NodeFlowPanel.tsx       ← patch: animated entry, step duration, glow on checkpoints
│   ├── ProgressRing.tsx        ← patch: done→idle 3s fade opacity spring
│   │
│   ├── PostProcessing.tsx      ← NEW: Bloom + ChromaticAberration + Vignette
│   ├── CommandPalette.tsx      ← NEW: ⌘K overlay, fuzzy search, action registry
│   ├── SmartIsland.tsx         ← NEW: bottom-right collapsible chip → 3-tab panel
│   ├── HoverCard.tsx           ← NEW: mouse-tracked agent tooltip
│   └── ModelPill.tsx           ← NEW: top-left backend pill (Claude / Gemini / tgpt)
│
└── hooks/
    ├── useVoice.ts             ← NEW: Web Speech API PTT + Bark AudioQueue
    └── useCommandPalette.ts    ← NEW: ⌘K keybind, action registry, fuzzy filter
```

### New Dependencies

```json
"@react-three/postprocessing": "^2",
"postprocessing": "^6"
```

All other features use existing deps or native browser APIs (Web Speech API, Audio, fetch).

---

## Design System

### Color Palette

```css
--bg-void:        #020408
--bg-base:        #050a14
--bg-card:        rgba(8, 14, 28, 0.75)
--bg-elevated:    rgba(13, 20, 40, 0.85)

--ceo-gold:       #f59e0b
--ceo-glow:       #fbbf24

--neural-cyan:    #00f0ff
--neural-purple:  #7c3aed
--neural-green:   #22c55e
--neural-red:     #ef4444

--agent-backend:  #3b82f6
--agent-frontend: #ec4899
--agent-qa:       #f59e0b
--agent-devops:   #10b981
--agent-browser:  #8b5cf6

--text-primary:   #e2e8f0
--text-muted:     #475569
--border:         rgba(0, 240, 255, 0.12)
--glow-cyan:      0 0 24px rgba(0, 240, 255, 0.35)
--glow-gold:      0 0 32px rgba(245, 158, 11, 0.5)
```

### Typography

| Use | Font |
|---|---|
| Agent names (3D scene), panel titles, palette headers, model pill | Orbitron (Google Fonts) |
| UI, panels, chat, body text | Inter |
| Terminal output, code | JetBrains Mono (Google Fonts) |

Load via `@import` in `main.tsx` or `index.html`:
```html
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=JetBrains+Mono&display=swap" rel="stylesheet">
```

### Agent Identity Colors

Each worker has a unique identity color used for: node emissive, edge particles, panel border glow, hover card accent.

| Agent | ID | Color |
|---|---|---|
| Subaru Natsuki | ceo | #f59e0b (gold) |
| Reinhard | backend | #3b82f6 (steel blue) |
| Emilia | frontend | #ec4899 (rose pink) |
| Beatrice | qa | #f59e0b (amber, lighter usage) |
| Otto | devops | #10b981 (emerald) |
| Maya | browser | #8b5cf6 (violet) |

### Post-Processing Stack (`PostProcessing.tsx`)

```tsx
<EffectComposer>
  <Bloom
    intensity={1.2}
    luminanceThreshold={0.4}
    luminanceSmoothing={0.9}
    mipmapBlur
  />
  <ChromaticAberration offset={[0.0008, 0.0008]} />
  <Vignette darkness={0.4} />
</EffectComposer>
```

Mounted inside the R3F `<Canvas>` after all scene geometry. Only surfaces with `emissiveIntensity` above `0.4` trigger bloom — idle nodes do not bloom, active nodes glow dramatically.

---

## CEO Arc Reactor (`CeoNode.tsx`)

```tsx
<group position={[0, 0.5, 4]}>
  {/* Core */}
  <mesh>
    <sphereGeometry args={[0.25, 32, 32]} />
    <meshBasicMaterial color="#f59e0b" />
  </mesh>
  <pointLight color="#f59e0b" intensity={idleIntensity} distance={12} />

  {/* Inner ring — Z rotation */}
  <mesh rotation={[0, 0, ringAngle1]}>
    <torusGeometry args={[0.55, 0.03, 16, 64]} />
    <meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={2.5} />
  </mesh>

  {/* Mid ring — Y rotation, X tilt 55° */}
  <mesh rotation={[Math.PI * 0.31, ringAngle2, 0]}>
    <torusGeometry args={[0.8, 0.025, 16, 64]} />
    <meshStandardMaterial color="#fbbf24" emissive="#fbbf24" emissiveIntensity={2.0} />
  </mesh>

  {/* Outer ring — X rotation, Z tilt 30° */}
  <mesh rotation={[ringAngle3, 0, Math.PI * 0.17]}>
    <torusGeometry args={[1.05, 0.02, 16, 64]} />
    <meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={1.5} transparent opacity={0.6} />
  </mesh>

  {/* Audio waveform ring — visible when TTS speaking */}
  {isSpeaking && <AudioWaveformRing radius={1.2} color="#fbbf24" />}

  <Text font="Orbitron" position={[0, -1.5, 0]} fontSize={0.16} color="#f59e0b">
    SUBARU NATSUKI
  </Text>
  <Text position={[0, -1.75, 0]} fontSize={0.10} color="#94a3b8">
    Chief Executive Officer
  </Text>
</group>
```

Ring rotation speeds (rad/s, driven by `useFrame`):

| Ring | Idle | Thinking | Working |
|---|---|---|---|
| Inner (Z) | 0.6 | 1.8 | 3.0 |
| Mid (Y) | -0.4 | -1.2 | -2.0 |
| Outer (X) | 0.25 | 0.75 | 1.2 |

PointLight intensity: idle `2.0`, thinking `3.5`, working `5.0`.

`AudioWaveformRing`: 64-point `BufferGeometry` circle. On each `useFrame`, vertex Y positions displaced by `sin(theta × freq + time) × amplitude` where `amplitude` tracks `AudioAnalyser.getAverageFrequency()` normalized to `[0, 0.15]`.

---

## Worker Nodes (`AgentNode.tsx`)

### Geometry

```tsx
<group position={position}>
  <mesh ref={meshRef} onClick={handleClick} onPointerOver={handleOver} onPointerOut={handleOut}>
    <icosahedronGeometry args={[radius, 1]} />
    <meshStandardMaterial
      color={agentColor}
      emissive={agentColor}
      emissiveIntensity={emissiveIntensity}  // driven by useFrame
      metalness={0.8}
      roughness={0.2}
    />
  </mesh>

  {/* Outer halo — working only */}
  {status === 'working' && (
    <mesh>
      <icosahedronGeometry args={[radius + 0.18, 1]} />
      <meshBasicMaterial color={agentColor} transparent opacity={haloOpacity} wireframe />
    </mesh>
  )}

  {/* Particle corona — thinking + working */}
  {(status === 'thinking' || status === 'working') && (
    <CoronaParticles count={12} radius={radius + 0.3} color={agentColor} speed={status === 'working' ? 1.5 : 0.6} />
  )}

  <ProgressRing agent={agent} nodeRadius={radius} lastCheckpointIndex={agent.checkpoints.length} />

  <Text font="Orbitron" position={[0, -(radius + 0.35), 0]} fontSize={0.16} color={agentColor}>
    {name.toUpperCase()}
  </Text>
  <Text position={[0, -(radius + 0.58), 0]} fontSize={0.10} color="#475569">
    {role}
  </Text>
</group>
```

### Status → emissiveIntensity

| Status | emissiveIntensity |
|---|---|
| `idle` | 0.08 |
| `thinking` | 0.3 → 1.0 sine, 2s cycle |
| `working` | 0.6 → 2.0 sine, 0.8s fast cycle |
| `done` | 2.5 flash, then fades to 0.08 over 3s |

### Shatter on Click + Dim Others

```typescript
// On selectAgent(id):
// 1. Clicked node: useSpring { scale: 1→1.6, opacity: 1→0 } over 300ms
// 2. All other nodes: emissiveIntensity multiplied by 0.2
// 3. Edges not connected to this agent: opacity → 0.05
// 4. AgentDetailView mounts at t=200ms with entrance animation
// 5. Canvas: filter: 'blur(3px) brightness(0.6)', transition 300ms

// On selectAgent(null):
// All animations reverse — nodes restore, canvas unblurs, panel fades out
```

### Fixed: `done` → `idle` Timeout

```typescript
useEffect(() => {
  if (status !== 'done') return
  const timer = setTimeout(() => resetAgentStatus(id), 3000)
  return () => clearTimeout(timer)
}, [status, id, resetAgentStatus])
```

---

## Neural Edges (`NeuralEdge.tsx`)

### Fixes

```typescript
// Curve memoized (not recreated every render)
const curve = useMemo(() => new THREE.QuadraticBezierCurve3(
  new THREE.Vector3(...start),
  new THREE.Vector3(...mid),
  new THREE.Vector3(...end),
), [start[0], start[1], start[2], end[0], end[1], end[2]])
```

### Enhancements

**Idle heartbeat:** `isActive=false` → baseline line opacity pulses `0.08 → 0.18`, 4s sine cycle. Network never looks dead.

**Agent identity color:** Active particles use `AGENT_COLORS[workerId]` instead of always cyan.

**Reverse burst on `worker_done`:** 5 particles spawn at the worker end, travel to CEO over 1s using `t` from `1.0 → 0.0`, color `#22c55e`. Implemented as a separate `ReverseBurst` component triggered by a brief boolean flag set on `worker_done`.

**Particle count:** `isActive` → 5 particles (up from 3). Stagger offsets: `[0, 0.2, 0.4, 0.6, 0.8]`.

---

## Background (`Background.tsx`)

### Cortical Wave Floor

Custom `ShaderMaterial` plane replacing `<gridHelper>`. 80×80 vertex segments, size 40×40 units, `y=-4`.

```glsl
// Vertex shader
uniform float uTime;
uniform vec3 uCeoPos;

void main() {
  vec3 pos = position;
  float dist = length(pos.xz - uCeoPos.xz);
  float wave = sin(dist * 1.2 - uTime * 2.5) * 0.08;
  float attenuation = 1.0 - smoothstep(0.0, 18.0, dist);
  pos.y += wave * attenuation;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
}

// Fragment shader
void main() {
  float brightness = 0.2 + waveIntensity * 0.4;
  float radialFade = 1.0 - smoothstep(12.0, 20.0, dist);
  gl_FragColor = vec4(0.055, 0.647, 0.914, brightness * radialFade); // #0ea5e9
}
```

### 3-Class Particle System

| Class | Count | Motion | Color |
|---|---|---|---|
| A — Organic drift | 200 | Upward + Perlin XZ noise | #0ea5e9, opacity 0.5 |
| B — CEO orbit | 200 | Slow orbit around [0,0.5,4] at varying radii | #f59e0b, opacity 0.3 |
| C — Data streaks | 100 | Fast vertical, random appear/disappear | Active worker color, opacity 0.8 |

Class C only rendered when at least one worker is in `working` state. Their color matches the working worker's identity color (if multiple workers active, alternates).

### 3-Point Lighting

```tsx
<ambientLight intensity={0.15} />
<pointLight position={[0, 0.5, 4]} color="#f59e0b" intensity={ceoLightIntensity} distance={12} />  {/* key */}
<pointLight position={[-6, 4, -2]} color="#1e3a5f" intensity={0.8} distance={20} />               {/* fill */}
<pointLight position={[6, -2, -4]} color="#0c1a2e" intensity={0.4} distance={15} />               {/* rim */}
```

`ceoLightIntensity`: idle `2.0`, thinking `3.5`, working `5.0` — driven by CEO status from store.

### Fog

```tsx
<fog attach="fog" args={['#020408', 6, 35]} />
```

---

## Agent Detail View (`AgentDetailView.tsx`)

### Click Sequence

```
t=0ms    selectAgent(id) fired
         → clicked node begins shatter spring
         → other nodes dim, unrelated edges fade
         → canvas gains blur CSS

t=200ms  AgentDetailView mounts, opacity=0, scale=0.92

t=250ms  Panel entrance: opacity→1, scale→1.0
         CSS: transition 200ms cubic-bezier(0.16, 1, 0.3, 1)

t=450ms  Panel fully interactive
```

Back button reverses all animations with same timing.

### Panel CSS

```css
.agent-panel {
  position: fixed;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%) scale(1);
  width: 560px;
  max-height: 80vh;

  background: rgba(8, 14, 28, 0.82);
  backdrop-filter: blur(24px) saturate(1.4);
  border: 1px solid {agentColor}59;     /* 35% opacity */
  box-shadow:
    0 0 0 1px {agentColor}1a,           /* subtle inner */
    0 0 40px {agentColor}26,            /* outer glow */
    inset 0 1px 0 rgba(255,255,255,0.06);

  clip-path: polygon(
    8px 0%, calc(100% - 8px) 0%,
    100% 8px, 100% calc(100% - 8px),
    calc(100% - 8px) 100%, 8px 100%,
    0% calc(100% - 8px), 0% 8px
  );

  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 20px 24px;
  overflow: hidden;
}

.agent-panel-title {
  font-family: 'Orbitron', sans-serif;
  color: {agentColor};
  font-size: 13px;
  letter-spacing: 0.1em;
  font-weight: 700;
}

.agent-terminal {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  line-height: 1.6;
  flex: 1;
  overflow-y: auto;
  max-height: 320px;
}
```

### Panel Layout

```
┌─────────────────────────────────────────────────────────┐
│  ← Back       REINHARD VON ASTREA  •  Backend Eng  ●   │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  NODE FLOW  ──────────────────────────  6 steps · 2 ✓  │
│  ◆ Checkpoint 2 · step 6    "All tests pass"      0.3s  │
│  ○ step 6  ⚙ bash    curl health check            0.3s  │
│                                                          │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  > Tool: bash — running pytest...                        │
│  > All 14 tests passing                                  │
│                                                          │
│  ─────────────────────────────────────────────────────  │
│  [ Send message to Reinhard...         ]  [ 🎤 ] [Send] │
└─────────────────────────────────────────────────────────┘
```

### Voice Button States

| State | Appearance |
|---|---|
| Idle | `[ 🎤 ]` grey border |
| Listening | `[ 🎤 ]` agent-color pulsing border + 3 waveform dots |
| Speaking (Bark) | `[ 🔊 ]` gold border + subtle glow |

---

## Voice System (`useVoice.ts`)

### Hook Interface

```typescript
interface UseVoiceReturn {
  isListening: boolean
  isSpeaking: boolean
  ttsEnabled: boolean
  startListening: () => void
  stopListening: () => void
  toggleTts: () => void
}
```

`ttsEnabled` persisted to `localStorage['nexus-tts-enabled']`.

### Push-to-Talk Flow

1. User clicks 🎤 → `startListening()` → `SpeechRecognition.start()`
2. Silence detection: auto-stops after 1.5s of no speech via `onspeechend`
3. Or: user clicks 🎤 again → `stopListening()` → `SpeechRecognition.stop()`
4. `onresult` fires → transcript sent via `sendWsMessage({ type: 'message', agent: id, text: transcript })`
5. Filler fetch: `GET /api/filler?context={transcript}` → if audio returned, `AudioQueue.push(audio, 'filler')`

### Bark AudioQueue

```typescript
const AudioQueue = {
  _queue: Array<{ base64: string; mode: 'speak' | 'sing' | 'filler' }>,
  _playing: false,

  push(base64: string, mode: 'speak' | 'sing' | 'filler') {
    this._queue.push({ base64, mode })
    if (!this._playing) this._next()
  },

  async _next() {
    if (!this._queue.length) { this._playing = false; return }
    this._playing = true
    const { base64, mode } = this._queue.shift()!
    const blob = new Blob([Uint8Array.from(atob(base64), c => c.charCodeAt(0))], { type: 'audio/wav' })
    const url = URL.createObjectURL(blob)
    const el = new Audio(url)
    if (mode === 'speak') setIsSpeaking(true)   // triggers CEO waveform ring
    el.onended = () => {
      URL.revokeObjectURL(url)
      if (mode === 'speak') setIsSpeaking(false)
      this._next()
    }
    el.play()
  }
}
```

WS `audio` events are forwarded to AudioQueue via a module-level EventEmitter (not Zustand) to avoid unnecessary re-renders.

### Degradation

| Scenario | Behaviour |
|---|---|
| Bark down (`bark_ok: false`) | `speakResponse()` Web Speech Synthesis fallback |
| `SpeechRecognition` unavailable | Mic button hidden, text input only |
| TTS disabled | No filler fetch, no audio processing |
| Audio playing + mic clicked | Queue paused, mic starts |

---

## Command Palette (`CommandPalette.tsx` + `useCommandPalette.ts`)

Triggered by `⌘K` / `Ctrl+K`, dismissed by `Escape` or clicking outside.

### Action Registry

```typescript
const ACTIONS: PaletteAction[] = [
  { id: 'agent-ceo',      label: 'Talk to Subaru',      group: 'AGENTS',      action: () => selectAgent('ceo') },
  { id: 'agent-backend',  label: 'Talk to Reinhard',    group: 'AGENTS',      action: () => selectAgent('backend') },
  { id: 'agent-frontend', label: 'Talk to Emilia',      group: 'AGENTS',      action: () => selectAgent('frontend') },
  { id: 'agent-qa',       label: 'Talk to Beatrice',    group: 'AGENTS',      action: () => selectAgent('qa') },
  { id: 'agent-devops',   label: 'Talk to Otto',        group: 'AGENTS',      action: () => selectAgent('devops') },
  { id: 'agent-browser',  label: 'Talk to Maya',        group: 'AGENTS',      action: () => selectAgent('browser') },
  { id: 'queue-show',     label: 'Show work queue',     group: 'WORK QUEUE',  action: () => SmartIsland.setTab('queue') },
  { id: 'notif-show',     label: 'Show notifications',  group: 'WORK QUEUE',  action: () => SmartIsland.setTab('notifications') },
  // SmartIsland.setTab is a module-level setter exported from SmartIsland.tsx
  // that updates local tab state and also expands the island if collapsed
  { id: 'tts-toggle',     label: 'Toggle voice / TTS',  group: 'VOICE',       action: () => toggleTts() },
  { id: 'ws-reconnect',   label: 'Reconnect WebSocket', group: 'SYSTEM',      action: () => connectWebSocket() },
]
```

Fuzzy filter: `label.toLowerCase().includes(query.toLowerCase())` — no library.

### Visual Layout

```
┌──────────────────────────────────────────────────────┐
│  ⌘  Search or command...                     [Esc]   │  ← Orbitron font
├──────────────────────────────────────────────────────┤
│  AGENTS                                              │
│  ◉ Talk to Subaru (CEO)              ← gold accent   │
│  ● Talk to Reinhard (Backend)        ← blue accent   │
│  ● Talk to Emilia (Frontend)         ← pink accent   │
│                                                      │
│  WORK QUEUE                                          │
│  📋 Show work queue                                  │
│  🔔 Show notifications                               │
│                                                      │
│  VOICE                                               │
│  🎤 Toggle voice mode              [currently ON]    │
│                                                      │
│  SYSTEM                                              │
│  🔄 Reconnect WebSocket                              │
└──────────────────────────────────────────────────────┘
```

### CSS

```css
.command-palette {
  position: fixed;
  top: 20%;
  left: 50%;
  transform: translateX(-50%);
  width: 520px;
  background: rgba(5, 10, 20, 0.92);
  backdrop-filter: blur(32px);
  border: 1px solid rgba(0, 240, 255, 0.15);
  border-radius: 12px;
  z-index: 200;
  /* entrance: translateY(-8px) → 0, opacity 0→1, 180ms */
}
```

---

## Smart Island (`SmartIsland.tsx`)

Fixed bottom-right. Collapsed to a chip by default, expands on click.

### Chip State

```
[ ● 3 active · 2 queued ]
```
Click → expands to 320px panel.

### Expanded — 3 Tabs

```
┌─────────────────────────────────────────┐
│  NOTIFICATIONS  │  QUEUE  │  ACTIVE TOOL │
├─────────────────────────────────────────┤
│  NOTIFICATIONS:                          │
│  ✓ Reinhard completed API routes  2m ago │
│  ⚡ Emilia assigned frontend task  5m   │
│                                          │
│  QUEUE:                                  │
│  [1] Build trading dashboard  pending    │
│  [2] Write unit tests         blocked    │
│                                          │
│  ACTIVE TOOL:                            │
│  ⚙ Reinhard: bash              12s       │
│  🌐 Maya: browser navigate      4s       │
└─────────────────────────────────────────┘
```

### Store Wiring

- **Notifications**: stored in `notifications: Notification[]` (last 10), populated on `worker_done`, `queue_update`, `assistant` events — new entries prepended, slice to 10.
- **Queue**: from `workQueue: WorkQueueItem[]` populated by `queue_update` events.
- **Active Tool**: derived from agents in `working` state → their last `recentSteps` entry.

### CSS

```css
.smart-island {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 320px;
  background: rgba(8, 14, 28, 0.88);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(0, 240, 255, 0.12);
  border-radius: 10px;
  z-index: 50;
  /* entrance: translateY(8px) → 0, 200ms */
}
```

---

## Model Pill (`ModelPill.tsx`)

Top-left corner, always visible.

```
[ ⚡ Claude Sonnet ]
```

Updates on `backend_switch` WS events. Colors:

| Backend | Color |
|---|---|
| `claude` | #f59e0b gold |
| `gemini` | #3b82f6 blue |
| `tgpt` | #475569 grey |

Font: Orbitron, 11px. `position: fixed; top: 16px; left: 16px; z-index: 10`.

---

## Store Additions (`store.ts`)

### New Types

```typescript
// Agent identity colors — exported constant in types.ts
export const AGENT_COLORS: Record<string, string> = {
  ceo:      '#f59e0b',
  backend:  '#3b82f6',
  frontend: '#ec4899',
  qa:       '#f59e0b',
  devops:   '#10b981',
  browser:  '#8b5cf6',
}

export type WsModel = 'claude' | 'gemini' | 'tgpt'

export interface WorkQueueItem {
  id: string
  task: string
  status: 'pending' | 'active' | 'blocked' | 'completed'
  agent?: string
}

export interface Notification {
  id: string
  text: string
  ts: number
  type: 'done' | 'delegation' | 'queue' | 'message'
}
```

### New Store Fields

```typescript
workQueue: WorkQueueItem[]     // default: []
wsModel: WsModel               // default: 'claude'
notifications: Notification[]  // default: [], max 10
```

### New Actions

```typescript
resetAgentStatus: (id: string) => void   // sets agent.status → 'idle'
```

### New Event Cases

```typescript
case 'tool_call': {
  if (!agentId) break
  const label = event.label as string
  const prev = agents[agentId] ?? defaultAgent(agentId)
  updateAgent(agentId, {
    recentOutput: [...prev.recentOutput, `Tool: ${label}`].slice(-500)
  })
  break
}

case 'queue_update': {
  const items = (event.queue as WorkQueueItem[]) ?? []
  return { ...state, workQueue: items }
}

case 'backend_switch': {
  return { ...state, wsModel: event.model as WsModel }
}

// init fix — reset stale edges:
case 'init': {
  // existing agent hydration...
  edges.forEach(e => { e.isActive = false })
  break
}
```

### 5-Minute Stuck Task Guard

In `connectWebSocket` module scope:

```typescript
const _workingTimers: Record<string, ReturnType<typeof setTimeout>> = {}

// On 'delegation' event (inside onmessage, after handleEvent):
if (type === 'delegation' && agentId) {
  clearTimeout(_workingTimers[agentId])
  _workingTimers[agentId] = setTimeout(() => {
    useNexusStore.getState().resetAgentStatus(agentId)
    delete _workingTimers[agentId]
  }, 5 * 60 * 1000)
}

// On 'worker_done' event:
if (type === 'worker_done' && agentId) {
  clearTimeout(_workingTimers[agentId])
  delete _workingTimers[agentId]
}
```

---

## Bug Fixes Summary

| Bug | File | Fix |
|---|---|---|
| `done` timeout does nothing | `AgentNode.tsx` | `setTimeout(() => resetAgentStatus(id), 3000)` |
| `ProgressRing` never fades after done | `ProgressRing.tsx` | Opacity spring: `delay: 3000, opacity: 0` on done |
| Curve recreated every render | `NeuralEdge.tsx` | `useMemo` on `QuadraticBezierCurve3` |
| `tool_call` event silently dropped | `store.ts` | New case, appends to `recentOutput` |
| `queue_update` event ignored | `store.ts` | New case, updates `workQueue` |
| `backend_switch` event ignored | `store.ts` | New case, updates `wsModel` |
| Stale active edges after reconnect | `store.ts` | `init` case resets all edges to `isActive: false` |
| 5-min stuck worker never resets | `store.ts` | Module-level `_workingTimers` guard |
| Agent hover shows no info | `AgentNode.tsx` + `HoverCard.tsx` | New pointer events + DOM tooltip |

---

## HoverCard (`HoverCard.tsx`)

DOM tooltip anchored to mouse position, shown on `onPointerOver` in `AgentNode`.

```
┌────────────────────────────────┐
│  ● REINHARD   Backend Eng.     │  ← Orbitron, agent color
│  ────────────────────────────  │
│  Status: Working               │
│  Steps: 6  ·  Checkpoints: 2  │
│  Backend: Claude Sonnet        │
│  Last: bash — curl health chk  │
└────────────────────────────────┘
```

Position: `{ left: mouseX + 16, top: mouseY + 8 }`, `position: fixed`.
Hidden after 300ms `onPointerOut` delay (prevents flicker on node edge).

---

## Build Notes

### `vite.config.ts` — no changes needed
`@react-three/postprocessing` tree-shakes cleanly through Vite.

### Bundle estimate
Current: ~400KB gzip. New additions: `@react-three/postprocessing` + `postprocessing` ~65KB gzip.
Total estimated: ~465KB gzip.

### Dev workflow unchanged
```bash
cd nexus-ui && npm run dev   # Vite :5173, proxies /ws and /api to 127.0.0.1:3031
```

---

## Build Order

1. `types.ts` — add `WorkQueueItem`, `Notification`, `WsModel`, `AGENT_COLORS` constant
2. `store.ts` — new fields + new event cases + `resetAgentStatus` + stuck task guard
3. `PostProcessing.tsx` — Bloom + ChromaticAberration + Vignette (isolated, no deps)
4. `Background.tsx` — rewrite with cortical wave shader + 3-class particles + 3-point lights
5. `CeoNode.tsx` — new component, arc reactor geometry
6. `AgentNode.tsx` — rewrite with shatter spring, identity color, fixed done timeout, hover trigger
7. `NeuralEdge.tsx` — patch: useMemo curve, idle heartbeat, identity color, reverse burst
8. `ProgressRing.tsx` — patch: done fade opacity spring
9. `NodeFlowPanel.tsx` — patch: animated entry, step duration, checkpoint glow
10. `HoverCard.tsx` — new DOM tooltip
11. `ModelPill.tsx` — new top-left backend indicator
12. `useVoice.ts` — new hook: Web Speech API PTT + AudioQueue
13. `AgentDetailView.tsx` — rewrite: glassmorphic panel, entrance animation, voice button, hex clip
14. `useCommandPalette.ts` — new hook: keybind, action registry, fuzzy filter
15. `CommandPalette.tsx` — new component
16. `SmartIsland.tsx` — new component
17. `NexusScene.tsx` — rewrite: wire all new components, canvas blur on select, PostProcessing
    - Instantiates `useVoice()` at root — passes `isSpeaking` to `CeoNode`, `ttsEnabled`+`toggleTts` to `AgentDetailView`
    - Instantiates `useCommandPalette()` at root — passes `open`/`close` to `CommandPalette`
    - `AudioWaveformRing` is defined as an internal sub-component inside `CeoNode.tsx` (not a separate file)

---

## Out of Scope

- Mobile / touch support
- Agent drag-to-reposition in 3D space
- Image drag-drop (Claude vision input) — backend not yet wired for vision in current graph
- Skills Panel UI — backend `/api/skills` endpoint exists but not surfaced yet
- Dark/light theme toggle
- Multi-agent `[ASK:ceo]` visualization in the scene (handled server-side)
