# NEXUS Neural Command Center Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the NEXUS 3D dashboard into an immersive Neural Command Center with GPU bloom, golden arc reactor CEO, agent identity colors, glassmorphic hex panels, push-to-talk voice, command palette, and smart island.

**Architecture:** React Three Fiber scene with `@react-three/postprocessing` for GPU bloom. DOM overlays (glassmorphic panels, glassmorphic command palette, smart island) rendered outside Canvas. Zustand store extended with work queue, model tracking, notifications, island state. Voice via Web Speech API (PTT) + Bark AudioQueue for ordered audio playback.

**Tech Stack:** React 18, React Three Fiber 8, drei 9, @react-three/postprocessing 2, Three.js 0.165, Zustand 4, @react-spring/three 9, TypeScript, Vite

**Spec:** `docs/superpowers/specs/2026-06-11-nexus-neural-command-center-redesign.md`

---

## File Map

| Status | File | Purpose |
|---|---|---|
| Modify | `nexus-ui/package.json` | Add postprocessing deps |
| Modify | `nexus-ui/index.html` | Add Google Fonts (Orbitron, JetBrains Mono) |
| Modify | `nexus-ui/src/types.ts` | Add AGENT_COLORS, WorkQueueItem, Notification, WsModel |
| Modify | `nexus-ui/src/store.ts` | New state fields + 4 new event cases + island state + stuck guard |
| Create | `nexus-ui/src/components/PostProcessing.tsx` | Bloom + ChromaticAberration + Vignette |
| Modify | `nexus-ui/src/components/Background.tsx` | Cortical wave floor shader + 3-class particles + 3-point lights |
| Create | `nexus-ui/src/components/CeoNode.tsx` | Arc reactor: nested tori + core sphere + audio waveform ring |
| Modify | `nexus-ui/src/components/AgentNode.tsx` | Shatter spring, identity colors, corona, fixed done timeout |
| Modify | `nexus-ui/src/components/NeuralEdge.tsx` | useMemo curve, idle heartbeat, identity color, reverse burst |
| Modify | `nexus-ui/src/components/ProgressRing.tsx` | Done→idle 3s fade opacity spring |
| Modify | `nexus-ui/src/components/NodeFlowPanel.tsx` | Animated entry, step duration, checkpoint glow |
| Create | `nexus-ui/src/components/HoverCard.tsx` | Mouse-tracked agent tooltip |
| Create | `nexus-ui/src/components/ModelPill.tsx` | Top-left backend pill |
| Create | `nexus-ui/src/hooks/useVoice.ts` | Web Speech API PTT + Bark AudioQueue |
| Modify | `nexus-ui/src/components/AgentDetailView.tsx` | Glassmorphic hex panel + entrance anim + voice button |
| Create | `nexus-ui/src/hooks/useCommandPalette.ts` | ⌘K keybind + action registry + fuzzy filter |
| Create | `nexus-ui/src/components/CommandPalette.tsx` | ⌘K search overlay |
| Create | `nexus-ui/src/components/SmartIsland.tsx` | Bottom-right collapsible 3-tab panel |
| Modify | `nexus-ui/src/components/NexusScene.tsx` | Wire all new components, canvas blur, postprocessing |

---

## Task 1: Install dependencies and fonts

**Files:**
- Modify: `nexus-ui/package.json`
- Modify: `nexus-ui/index.html`

- [ ] **Step 1: Add postprocessing packages**

In `nexus-ui/`, run:
```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui
npm install @react-three/postprocessing@^2 postprocessing@^6
```

Expected: `package.json` now lists both packages under `dependencies`.

- [ ] **Step 2: Add Google Fonts to index.html**

In `nexus-ui/index.html`, add inside `<head>` before the closing `</head>`:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
```

- [ ] **Step 3: Verify build still compiles**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui
npm run build 2>&1 | tail -20
```

Expected: build succeeds (no errors, warnings about new packages are fine).

- [ ] **Step 4: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/package.json nexus-ui/package-lock.json nexus-ui/index.html
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): add postprocessing deps and Google Fonts"
```

---

## Task 2: Extend types.ts

**Files:**
- Modify: `nexus-ui/src/types.ts`

- [ ] **Step 1: Add new types and constants**

Replace the full content of `nexus-ui/src/types.ts` with:

```typescript
export type AgentStatus = 'idle' | 'thinking' | 'working' | 'done'
export type WsModel = 'claude' | 'gemini' | 'tgpt'

export interface Step {
  step: number
  tool: string
  label: string
  ts: number
}

export interface Checkpoint {
  index: number
  summary: string
  step: number
  ts: number
}

export interface AgentState {
  id: string
  name: string
  role: string
  status: AgentStatus
  recentOutput: string[]
  stepCount: number
  recentSteps: Step[]
  checkpoints: Checkpoint[]
}

export interface EdgeState {
  from: string
  to: string
  isActive: boolean
}

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

export const AGENT_POSITIONS: Record<string, [number, number, number]> = {
  ceo:      [0,  0.5,  4],
  backend:  [-3, 0,   -1],
  frontend: [-2, 0,   -3],
  qa:       [0,  0,   -2],
  devops:   [2,  0,   -1],
  browser:  [3,  0,   -3],
}

export const AGENT_RADII: Record<string, number> = {
  ceo:      0.9,
  backend:  0.6,
  frontend: 0.6,
  qa:       0.6,
  devops:   0.6,
  browser:  0.6,
}

export const AGENT_COLORS: Record<string, string> = {
  ceo:      '#f59e0b',
  backend:  '#3b82f6',
  frontend: '#ec4899',
  qa:       '#f59e0b',
  devops:   '#10b981',
  browser:  '#8b5cf6',
}

export const TOOL_ICONS: Record<string, string> = {
  bash:    '⚙',
  read:    '📖',
  write:   '✍',
  edit:    '✏',
  web:     '🌐',
  jira:    '🎫',
  browser: '🔍',
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui
npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/types.ts
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): add AGENT_COLORS, WorkQueueItem, Notification, WsModel types"
```

---

## Task 3: Extend store.ts

**Files:**
- Modify: `nexus-ui/src/store.ts`

- [ ] **Step 1: Replace store.ts with extended version**

Replace the full content of `nexus-ui/src/store.ts` with:

```typescript
import { create } from 'zustand'
import type { AgentState, EdgeState, Step, Checkpoint, WorkQueueItem, Notification, WsModel } from './types'

const WORKER_IDS = ['backend', 'frontend', 'qa', 'devops', 'browser']

function defaultAgent(id: string, name = id, role = ''): AgentState {
  return {
    id, name, role,
    status: 'idle',
    recentOutput: [],
    stepCount: 0,
    recentSteps: [],
    checkpoints: [],
  }
}

function defaultEdges(): EdgeState[] {
  return WORKER_IDS.map(id => ({ from: 'ceo', to: id, isActive: false }))
}

function makeNotification(text: string, type: Notification['type']): Notification {
  return { id: `${Date.now()}-${Math.random()}`, text, ts: Date.now(), type }
}

interface NexusStore {
  agents: Record<string, AgentState>
  edges: EdgeState[]
  selectedAgent: string | null
  wsStatus: 'connected' | 'offline'
  wsModel: WsModel
  workQueue: WorkQueueItem[]
  notifications: Notification[]
  islandExpanded: boolean
  islandTab: 'notifications' | 'queue' | 'active'

  selectAgent: (id: string | null) => void
  setWsStatus: (s: 'connected' | 'offline') => void
  resetAgentStatus: (id: string) => void
  setIslandExpanded: (v: boolean) => void
  setIslandTab: (tab: 'notifications' | 'queue' | 'active') => void
  handleEvent: (event: Record<string, unknown>) => void
}

export const useNexusStore = create<NexusStore>((set) => ({
  agents: Object.fromEntries(
    ['ceo', ...WORKER_IDS].map(id => [id, defaultAgent(id)])
  ),
  edges: defaultEdges(),
  selectedAgent: null,
  wsStatus: 'offline',
  wsModel: 'claude',
  workQueue: [],
  notifications: [],
  islandExpanded: false,
  islandTab: 'notifications',

  selectAgent: (id) => set({ selectedAgent: id }),
  setWsStatus: (s) => set({ wsStatus: s }),
  resetAgentStatus: (id) => set(state => ({
    agents: { ...state.agents, [id]: { ...state.agents[id], status: 'idle' } }
  })),
  setIslandExpanded: (v) => set({ islandExpanded: v }),
  setIslandTab: (tab) => set({ islandTab: tab, islandExpanded: true }),

  handleEvent: (event) => {
    const type = event.type as string
    const agentId = event.agent as string | undefined

    set(state => {
      const agents = { ...state.agents }
      const edges = state.edges.map(e => ({ ...e }))
      const notifications = [...state.notifications]

      const updateAgent = (id: string, patch: Partial<AgentState>) => {
        agents[id] = { ...(agents[id] ?? defaultAgent(id)), ...patch }
      }

      const addNotif = (text: string, type: Notification['type']) => {
        notifications.unshift(makeNotification(text, type))
        if (notifications.length > 10) notifications.pop()
      }

      switch (type) {
        case 'init': {
          const list = (event.agents as Array<{ id: string; name: string; role: string }>) ?? []
          list.forEach(a => {
            agents[a.id] = { ...defaultAgent(a.id, a.name, a.role), ...agents[a.id] }
          })
          // Reset stale active edges on reconnect
          edges.forEach(e => { e.isActive = false })
          break
        }

        case 'thinking':
          if (agentId) updateAgent(agentId, { status: 'thinking' })
          break

        case 'delegation':
          if (agentId) {
            updateAgent(agentId, { status: 'working' })
            const edge = edges.find(e => e.to === agentId)
            if (edge) edge.isActive = true
            addNotif(`${agents[agentId]?.name ?? agentId} assigned task`, 'delegation')
          }
          break

        case 'worker_done':
          if (agentId) {
            const name = agents[agentId]?.name ?? agentId
            updateAgent(agentId, {
              status: 'done',
              stepCount: 0,
              recentSteps: [],
              checkpoints: [],
            })
            const edge = edges.find(e => e.to === agentId)
            if (edge) edge.isActive = false
            addNotif(`${name} completed task`, 'done')
          }
          break

        case 'tool_call': {
          if (!agentId) break
          const label = event.label as string
          const prev = agents[agentId] ?? defaultAgent(agentId)
          updateAgent(agentId, {
            recentOutput: [...prev.recentOutput, `Tool: ${label}`].slice(-500)
          })
          break
        }

        case 'worker_step': {
          if (!agentId) break
          const step: Step = {
            step: event.step as number,
            tool: event.tool as string,
            label: event.label as string,
            ts: Date.now(),
          }
          const prev = agents[agentId] ?? defaultAgent(agentId)
          updateAgent(agentId, {
            stepCount: event.step as number,
            recentSteps: [...prev.recentSteps, step].slice(-20),
          })
          break
        }

        case 'worker_checkpoint': {
          if (!agentId) break
          const cp: Checkpoint = {
            index: event.index as number,
            summary: event.summary as string,
            step: event.step as number,
            ts: Date.now(),
          }
          const prev2 = agents[agentId] ?? defaultAgent(agentId)
          updateAgent(agentId, { checkpoints: [...prev2.checkpoints, cp] })
          break
        }

        case 'assistant': {
          if (!agentId) break
          const content = (event.message as { content?: string })?.content ?? ''
          if (!content) break
          const prev3 = agents[agentId] ?? defaultAgent(agentId)
          updateAgent(agentId, {
            recentOutput: [...prev3.recentOutput, content].slice(-500)
          })
          break
        }

        case 'queue_update': {
          const items = (event.queue as WorkQueueItem[]) ?? []
          return { agents, edges, notifications, workQueue: items }
        }

        case 'backend_switch':
          return { agents, edges, notifications, wsModel: event.model as WsModel }

        case 'done':
          if (agentId) updateAgent(agentId, { status: 'idle' })
          break

        case 'error':
          if (agentId) updateAgent(agentId, { status: 'idle' })
          break
      }

      return { agents, edges, notifications }
    })
  },
}))

// ── WebSocket ────────────────────────────────────────────────────────────────

let _ws: WebSocket | null = null
let _retryDelay = 1000
const _workingTimers: Record<string, ReturnType<typeof setTimeout>> = {}

// Module-level audio event emitter (avoids Zustand churn for audio events)
type AudioListener = (base64: string, mode: string) => void
const _audioListeners: AudioListener[] = []
export function onAudioEvent(cb: AudioListener) { _audioListeners.push(cb) }
export function offAudioEvent(cb: AudioListener) {
  const i = _audioListeners.indexOf(cb)
  if (i >= 0) _audioListeners.splice(i, 1)
}

export function connectWebSocket(model = 'claude'): void {
  if (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)) return

  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${protocol}//${location.host}/ws?model=${model}`
  _ws = new WebSocket(url)

  _ws.onopen = () => {
    _retryDelay = 1000
    useNexusStore.getState().setWsStatus('connected')
  }

  _ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data) as Record<string, unknown>

      // Route audio events to listeners only (not into Zustand)
      if (data.type === 'audio') {
        _audioListeners.forEach(cb => cb(data.data as string, (data.mode as string) ?? 'speak'))
        return
      }

      useNexusStore.getState().handleEvent(data)

      // Stuck task guard
      const type = data.type as string
      const agentId = data.agent as string | undefined
      if (type === 'delegation' && agentId) {
        clearTimeout(_workingTimers[agentId])
        _workingTimers[agentId] = setTimeout(() => {
          useNexusStore.getState().resetAgentStatus(agentId)
          delete _workingTimers[agentId]
        }, 5 * 60 * 1000)
      }
      if ((type === 'worker_done' || type === 'done') && agentId) {
        clearTimeout(_workingTimers[agentId])
        delete _workingTimers[agentId]
      }
    } catch { /* ignore malformed */ }
  }

  _ws.onclose = () => {
    useNexusStore.getState().setWsStatus('offline')
    setTimeout(() => connectWebSocket(model), Math.min(_retryDelay, 30000))
    _retryDelay = Math.min(_retryDelay * 2, 30000)
  }
}

export function sendWsMessage(data: Record<string, unknown>): void {
  if (_ws?.readyState === WebSocket.OPEN) {
    _ws.send(JSON.stringify(data))
  }
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui
npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/store.ts
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): extend store with work queue, island state, audio emitter, 5-min guard"
```

---

## Task 4: PostProcessing component

**Files:**
- Create: `nexus-ui/src/components/PostProcessing.tsx`

- [ ] **Step 1: Create the file**

```typescript
// nexus-ui/src/components/PostProcessing.tsx
import { EffectComposer, Bloom, ChromaticAberration, Vignette } from '@react-three/postprocessing'
import { BlendFunction } from 'postprocessing'

export function PostProcessing() {
  return (
    <EffectComposer>
      <Bloom
        intensity={1.2}
        luminanceThreshold={0.4}
        luminanceSmoothing={0.9}
        mipmapBlur
      />
      <ChromaticAberration
        blendFunction={BlendFunction.NORMAL}
        offset={[0.0008, 0.0008] as unknown as THREE.Vector2}
      />
      <Vignette darkness={0.4} />
    </EffectComposer>
  )
}
```

Note: `@react-three/postprocessing` re-exports `THREE` types. If the `offset` type causes issues, cast via `new THREE.Vector2(0.0008, 0.0008)` instead — import `THREE` from `'three'`.

- [ ] **Step 2: Verify build**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui
npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/components/PostProcessing.tsx
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): add PostProcessing component (Bloom + ChromaticAberration + Vignette)"
```

---

## Task 5: Background rewrite

**Files:**
- Modify: `nexus-ui/src/components/Background.tsx`

- [ ] **Step 1: Replace Background.tsx**

```typescript
// nexus-ui/src/components/Background.tsx
import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useNexusStore } from '../store'

const PARTICLE_COUNT_A = 200
const PARTICLE_COUNT_B = 200
const PARTICLE_COUNT_C = 100
const TOTAL = PARTICLE_COUNT_A + PARTICLE_COUNT_B + PARTICLE_COUNT_C

const floorVertexShader = `
  uniform float uTime;
  varying float vDist;
  varying float vWave;

  void main() {
    // CEO is at world XZ = (0, 4). Plane is rotated -PI/2 on X.
    // For that rotation: world_z = -local_y, so CEO local_y = -4.
    float dist = length(position.xy - vec2(0.0, -4.0));
    float wave = sin(dist * 1.2 - uTime * 2.5) * 0.08;
    float attenuation = 1.0 - smoothstep(0.0, 18.0, dist);
    vWave = wave * attenuation;
    vDist = dist;

    vec3 pos = position;
    // Displace in local Z = world Y (upward) due to -PI/2 X rotation
    pos.z += vWave;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
  }
`

const floorFragmentShader = `
  varying float vDist;
  varying float vWave;

  void main() {
    float radialFade = 1.0 - smoothstep(12.0, 20.0, vDist);
    float brightness = 0.15 + max(0.0, vWave * 5.0) * 0.4;
    // #0ea5e9 = rgb(0.055, 0.647, 0.914)
    vec3 color = vec3(0.055, 0.647, 0.914);
    gl_FragColor = vec4(color, brightness * radialFade * 0.75);
  }
`

function makeAllPositions() {
  const pos = new Float32Array(TOTAL * 3)
  let i = 0

  // Class A: organic drift — random scatter
  for (; i < PARTICLE_COUNT_A; i++) {
    pos[i * 3]     = (Math.random() - 0.5) * 40
    pos[i * 3 + 1] = (Math.random() - 0.5) * 40
    pos[i * 3 + 2] = (Math.random() - 0.5) * 40
  }

  // Class B: orbit around CEO [0, 0.5, 4] at random radii
  for (; i < PARTICLE_COUNT_A + PARTICLE_COUNT_B; i++) {
    const theta = Math.random() * Math.PI * 2
    const phi = Math.random() * Math.PI
    const r = 3 + Math.random() * 8
    pos[i * 3]     = Math.sin(phi) * Math.cos(theta) * r
    pos[i * 3 + 1] = Math.cos(phi) * r * 0.5 + 0.5
    pos[i * 3 + 2] = Math.sin(phi) * Math.sin(theta) * r + 4
  }

  // Class C: data streaks — random XZ near center, full Y range
  for (; i < TOTAL; i++) {
    pos[i * 3]     = (Math.random() - 0.5) * 20
    pos[i * 3 + 1] = (Math.random() - 0.5) * 40
    pos[i * 3 + 2] = (Math.random() - 0.5) * 20
  }

  return pos
}

export function Background() {
  const pointsRef = useRef<THREE.Points>(null!)
  const floorRef = useRef<THREE.Mesh>(null!)
  const posRef = useRef(makeAllPositions())
  const timeRef = useRef(0)

  const agents = useNexusStore(s => s.agents)
  const workingAgent = Object.values(agents).find(a => a.status === 'working' && a.id !== 'ceo')
  const hasWorking = !!workingAgent
  const ceoStatus = agents['ceo']?.status ?? 'idle'

  const ceoLightIntensity = ceoStatus === 'working' ? 5.0 : ceoStatus === 'thinking' ? 3.5 : 2.0

  const floorUniforms = useMemo(() => ({
    uTime: { value: 0 },
  }), [])

  useFrame((_, delta) => {
    timeRef.current += delta
    const t = timeRef.current
    const pos = posRef.current

    // Class A: upward drift + simple XZ noise
    for (let i = 0; i < PARTICLE_COUNT_A; i++) {
      pos[i * 3 + 1] += delta * 0.3
      pos[i * 3]     += Math.sin(t * 0.3 + i * 0.7) * delta * 0.05
      pos[i * 3 + 2] += Math.cos(t * 0.2 + i * 1.1) * delta * 0.05
      if (pos[i * 3 + 1] > 20) pos[i * 3 + 1] -= 40
    }

    // Class B: slow orbit around CEO
    for (let i = PARTICLE_COUNT_A; i < PARTICLE_COUNT_A + PARTICLE_COUNT_B; i++) {
      const speed = 0.08 + (i % 7) * 0.01
      const angle = t * speed + i * 0.314
      const r = 3 + (i % 5) + 3
      pos[i * 3]     = Math.cos(angle) * r
      pos[i * 3 + 2] = Math.sin(angle) * r + 4
      pos[i * 3 + 1] = Math.sin(t * 0.3 + i) * 2 + 0.5
    }

    // Class C: vertical streaks, only rendered if hasWorking (opacity set in material)
    for (let i = PARTICLE_COUNT_A + PARTICLE_COUNT_B; i < TOTAL; i++) {
      pos[i * 3 + 1] += delta * 2.0
      if (pos[i * 3 + 1] > 20) pos[i * 3 + 1] = -20
    }

    if (pointsRef.current) {
      (pointsRef.current.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true
    }

    // Update floor shader time
    if (floorRef.current) {
      const mat = floorRef.current.material as THREE.ShaderMaterial
      mat.uniforms.uTime.value = t
    }
  })

  return (
    <>
      <fog attach="fog" args={['#020408', 6, 35]} />
      <ambientLight intensity={0.15} />
      {/* CEO key light */}
      <pointLight position={[0, 0.5, 4]} color="#f59e0b" intensity={ceoLightIntensity} distance={12} />
      {/* Fill light */}
      <pointLight position={[-6, 4, -2]} color="#1e3a5f" intensity={0.8} distance={20} />
      {/* Rim light */}
      <pointLight position={[6, -2, -4]} color="#0c1a2e" intensity={0.4} distance={15} />

      {/* Cortical wave floor */}
      <mesh ref={floorRef} position={[0, -4, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[40, 40, 80, 80]} />
        <shaderMaterial
          vertexShader={floorVertexShader}
          fragmentShader={floorFragmentShader}
          uniforms={floorUniforms}
          transparent
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      {/* All particle classes in one Points object */}
      <points ref={pointsRef}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[posRef.current, 3]}
          />
        </bufferGeometry>
        <pointsMaterial
          color="#0ea5e9"
          size={0.05}
          transparent
          opacity={0.5}
          sizeAttenuation
        />
      </points>
    </>
  )
}
```

> **Note:** The 3-class particle system uses one `Points` object with all 500 particles. Class C particles use the same color as classes A/B for now — per-particle coloring requires a vertex-colored material which adds complexity. The opacity of the entire group reflects the most active worker. This is a pragmatic simplification; the spec intent (data streaks in agent color) can be refined in a follow-up.

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/components/Background.tsx
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): rewrite Background with cortical wave floor shader and 3-point lighting"
```

---

## Task 6: CeoNode arc reactor

**Files:**
- Create: `nexus-ui/src/components/CeoNode.tsx`

- [ ] **Step 1: Create CeoNode.tsx**

```typescript
// nexus-ui/src/components/CeoNode.tsx
import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { Text, Billboard } from '@react-three/drei'
import * as THREE from 'three'
import { useNexusStore } from '../store'
import { AGENT_POSITIONS } from '../types'

interface CeoNodeProps {
  isSpeaking: boolean
  onClick: () => void
}

function AudioWaveformRing({ radius, color }: { radius: number; color: string }) {
  const points = useRef<THREE.Points>(null!)
  const timeRef = useRef(0)
  const COUNT = 64

  const positions = useMemo(() => {
    const pos = new Float32Array(COUNT * 3)
    for (let i = 0; i < COUNT; i++) {
      const theta = (i / COUNT) * Math.PI * 2
      pos[i * 3]     = Math.cos(theta) * radius
      pos[i * 3 + 1] = 0
      pos[i * 3 + 2] = Math.sin(theta) * radius
    }
    return pos
  }, [radius])

  useFrame((_, delta) => {
    timeRef.current += delta
    const t = timeRef.current
    const pos = positions.slice()
    for (let i = 0; i < COUNT; i++) {
      const theta = (i / COUNT) * Math.PI * 2
      pos[i * 3 + 1] = Math.sin(theta * 4 + t * 6) * 0.12
    }
    if (points.current) {
      (points.current.geometry.attributes.position as THREE.BufferAttribute).array.set(pos)
      ;(points.current.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true
    }
  })

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial color={color} size={0.04} transparent opacity={0.9} sizeAttenuation />
    </points>
  )
}

export function CeoNode({ isSpeaking, onClick }: CeoNodeProps) {
  const ring1Ref = useRef<THREE.Mesh>(null!)
  const ring2Ref = useRef<THREE.Mesh>(null!)
  const ring3Ref = useRef<THREE.Mesh>(null!)
  const coreRef  = useRef<THREE.Mesh>(null!)
  const lightRef = useRef<THREE.PointLight>(null!)

  const status = useNexusStore(s => s.agents['ceo']?.status ?? 'idle')
  const selectAgent = useNexusStore(s => s.selectAgent)
  const position = AGENT_POSITIONS['ceo']!

  const speeds = useMemo(() => {
    if (status === 'working')  return { r1: 3.0,  r2: -2.0, r3: 1.2,  li: 5.0 }
    if (status === 'thinking') return { r1: 1.8,  r2: -1.2, r3: 0.75, li: 3.5 }
    return                            { r1: 0.6,  r2: -0.4, r3: 0.25, li: 2.0 }
  }, [status])

  useFrame((_, delta) => {
    if (ring1Ref.current) ring1Ref.current.rotation.z += delta * speeds.r1
    if (ring2Ref.current) ring2Ref.current.rotation.y += delta * speeds.r2
    if (ring3Ref.current) ring3Ref.current.rotation.x += delta * speeds.r3

    if (coreRef.current && lightRef.current) {
      const t = Date.now() / 1000
      const pulse = status === 'thinking'
        ? 2.5 + Math.sin(t * Math.PI) * 0.5
        : status === 'working'
        ? 3.0 + Math.sin(t * Math.PI * 2) * 1.0
        : 2.0
      ;(coreRef.current.material as THREE.MeshBasicMaterial).color.setStyle('#f59e0b')
      lightRef.current.intensity = pulse
    }
  })

  return (
    <group position={position}>
      {/* Core */}
      <mesh
        ref={coreRef}
        onClick={() => { onClick(); selectAgent('ceo') }}
        onPointerOver={() => { document.body.style.cursor = 'pointer' }}
        onPointerOut={() => { document.body.style.cursor = 'default' }}
      >
        <sphereGeometry args={[0.25, 32, 32]} />
        <meshBasicMaterial color="#f59e0b" />
      </mesh>

      <pointLight ref={lightRef} color="#f59e0b" intensity={2.0} distance={12} />

      {/* Inner ring — Z rotation */}
      <mesh ref={ring1Ref}>
        <torusGeometry args={[0.55, 0.03, 16, 64]} />
        <meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={2.5} />
      </mesh>

      {/* Mid ring — Y rotation, X tilt 55° */}
      <mesh ref={ring2Ref} rotation={[Math.PI * 0.31, 0, 0]}>
        <torusGeometry args={[0.8, 0.025, 16, 64]} />
        <meshStandardMaterial color="#fbbf24" emissive="#fbbf24" emissiveIntensity={2.0} />
      </mesh>

      {/* Outer ring — X rotation, Z tilt 30° */}
      <mesh ref={ring3Ref} rotation={[0, 0, Math.PI * 0.17]}>
        <torusGeometry args={[1.05, 0.02, 16, 64]} />
        <meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={1.5} transparent opacity={0.6} />
      </mesh>

      {/* Audio waveform ring — visible when TTS speaking */}
      {isSpeaking && <AudioWaveformRing radius={1.2} color="#fbbf24" />}

      <Billboard>
        <Text
          font="https://fonts.gstatic.com/s/orbitron/v29/yMJMMIlzdpvBhQQL_SC3X9yhF25-T1nyGy6xpmIyXjU1pg.woff2"
          position={[0, -1.5, 0]}
          fontSize={0.16}
          color="#f59e0b"
          anchorX="center"
          anchorY="top"
        >
          SUBARU NATSUKI
        </Text>
        <Text
          position={[0, -1.75, 0]}
          fontSize={0.10}
          color="#94a3b8"
          anchorX="center"
          anchorY="top"
        >
          Chief Executive Officer
        </Text>
      </Billboard>
    </group>
  )
}
```

> **Font URL note:** The Orbitron woff2 URL above is a Google Fonts CDN link. drei's `<Text>` accepts a direct URL. If this causes CORS issues in production (since the build is served from port 3030), use the font loaded from the page's Google Fonts `<link>` tag instead — drei will find it via `document.fonts`.

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/components/CeoNode.tsx
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): add CeoNode arc reactor with nested rings and audio waveform"
```

---

## Task 7: AgentNode rewrite

**Files:**
- Modify: `nexus-ui/src/components/AgentNode.tsx`

- [ ] **Step 1: Replace AgentNode.tsx**

```typescript
// nexus-ui/src/components/AgentNode.tsx
import { useRef, useEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { Text, Billboard } from '@react-three/drei'
import { useSpring, animated } from '@react-spring/three'
import * as THREE from 'three'
import type { AgentState } from '../types'
import { AGENT_RADII, AGENT_COLORS } from '../types'
import { ProgressRing } from './ProgressRing'
import { useNexusStore } from '../store'

interface AgentNodeProps {
  agent: AgentState
  position: [number, number, number]
  dimmed: boolean
  onHoverEnter: (id: string, x: number, y: number) => void
  onHoverLeave: () => void
}

function CoronaParticles({ count, orbitRadius, color, speed }: {
  count: number
  orbitRadius: number
  color: string
  speed: number
}) {
  const ref = useRef<THREE.Points>(null!)
  const positions = useMemo(() => {
    const pos = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const theta = (i / count) * Math.PI * 2
      const phi = Math.random() * Math.PI
      pos[i * 3]     = Math.sin(phi) * Math.cos(theta) * orbitRadius
      pos[i * 3 + 1] = Math.cos(phi) * orbitRadius * 0.5
      pos[i * 3 + 2] = Math.sin(phi) * Math.sin(theta) * orbitRadius
    }
    return pos
  }, [count, orbitRadius])

  const offsets = useMemo(() => Array.from({ length: count }, (_, i) => i * 0.52), [count])

  useFrame((_, delta) => {
    if (!ref.current) return
    const pos = ref.current.geometry.attributes.position as THREE.BufferAttribute
    const arr = pos.array as Float32Array
    const t = Date.now() / 1000
    for (let i = 0; i < count; i++) {
      const theta = (offsets[i] + t * speed) % (Math.PI * 2)
      const phi = Math.sin(t * 0.5 + i) * Math.PI * 0.5 + Math.PI * 0.25
      arr[i * 3]     = Math.sin(phi) * Math.cos(theta) * orbitRadius
      arr[i * 3 + 1] = Math.cos(phi) * orbitRadius * 0.4
      arr[i * 3 + 2] = Math.sin(phi) * Math.sin(theta) * orbitRadius
    }
    pos.needsUpdate = true
  })

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial color={color} size={0.03} transparent opacity={0.8} sizeAttenuation />
    </points>
  )
}

export function AgentNode({ agent, position, dimmed, onHoverEnter, onHoverLeave }: AgentNodeProps) {
  const meshRef = useRef<THREE.Mesh>(null!)
  const { status, id, name, role } = agent
  const radius = AGENT_RADII[id] ?? 0.6
  const color = AGENT_COLORS[id] ?? '#00f0ff'
  const selectAgent = useNexusStore(s => s.selectAgent)
  const resetAgentStatus = useNexusStore(s => s.resetAgentStatus)
  const lastCpIdx = agent.checkpoints.length

  // Shatter spring on select
  const [shatterSpring, shatterApi] = useSpring(() => ({
    scale: 1,
    opacity: 1,
    config: { tension: 280, friction: 18 },
  }))

  const handleClick = (e: { clientX: number; clientY: number }) => {
    shatterApi.start({ scale: 1.6, opacity: 0 })
    selectAgent(id)
  }

  // Reverse on deselect (when selectedAgent becomes null while this was selected)
  const selectedAgent = useNexusStore(s => s.selectedAgent)
  useEffect(() => {
    if (selectedAgent === null) {
      shatterApi.start({ scale: 1, opacity: 1 })
    }
  }, [selectedAgent, shatterApi])

  // Fixed done → idle timeout
  useEffect(() => {
    if (status !== 'done') return
    const timer = setTimeout(() => resetAgentStatus(id), 3000)
    return () => clearTimeout(timer)
  }, [status, id, resetAgentStatus])

  useFrame(() => {
    if (!meshRef.current) return
    const mat = meshRef.current.material as THREE.MeshStandardMaterial
    const t = Date.now() / 1000

    let intensity: number
    if (status === 'thinking') {
      intensity = 0.3 + ((Math.sin(t * Math.PI) + 1) / 2) * 0.7
    } else if (status === 'working') {
      intensity = 0.6 + ((Math.sin(t * Math.PI * 2.5) + 1) / 2) * 1.4
    } else if (status === 'done') {
      intensity = 2.5
    } else {
      intensity = dimmed ? 0.02 : 0.08
    }

    mat.emissiveIntensity = intensity
    // Floating Y animation (local to group)
    meshRef.current.position.y = Math.sin(t * 1.0 + id.charCodeAt(0) * 0.5) * 0.08
  })

  const showCorona = status === 'thinking' || status === 'working'
  const coronaSpeed = status === 'working' ? 1.5 : 0.6

  return (
    <group position={position}>
      <animated.mesh
        ref={meshRef}
        scale={shatterSpring.scale}
        onClick={handleClick}
        onPointerOver={(e) => {
          document.body.style.cursor = 'pointer'
          onHoverEnter(id, e.clientX, e.clientY)
        }}
        onPointerOut={() => {
          document.body.style.cursor = 'default'
          onHoverLeave()
        }}
      >
        <icosahedronGeometry args={[radius, 1]} />
        <animated.meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={0.08}
          metalness={0.8}
          roughness={0.2}
          transparent
          opacity={shatterSpring.opacity}
        />
      </animated.mesh>

      {/* Outer halo when working */}
      {status === 'working' && (
        <mesh>
          <icosahedronGeometry args={[radius + 0.18, 1]} />
          <meshBasicMaterial color={color} transparent opacity={0.15} wireframe />
        </mesh>
      )}

      {showCorona && (
        <CoronaParticles
          count={12}
          orbitRadius={radius + 0.3}
          color={color}
          speed={coronaSpeed}
        />
      )}

      <ProgressRing agent={agent} nodeRadius={radius} lastCheckpointIndex={lastCpIdx} />

      <Billboard>
        <Text
          position={[0, -(radius + 0.35), 0]}
          fontSize={0.16}
          color={dimmed ? '#334155' : color}
          anchorX="center"
          anchorY="top"
        >
          {name.toUpperCase()}
        </Text>
        <Text
          position={[0, -(radius + 0.58), 0]}
          fontSize={0.10}
          color="#475569"
          anchorX="center"
          anchorY="top"
        >
          {role}
        </Text>
      </Billboard>
    </group>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1 | head -30
```

NexusScene.tsx will have type errors until Task 18 because it still uses the old AgentNode props — that's expected.

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/components/AgentNode.tsx
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): rewrite AgentNode with shatter spring, identity colors, corona particles"
```

---

## Task 8: NeuralEdge patches

**Files:**
- Modify: `nexus-ui/src/components/NeuralEdge.tsx`

- [ ] **Step 1: Replace NeuralEdge.tsx**

```typescript
// nexus-ui/src/components/NeuralEdge.tsx
import { useRef, useMemo, useState, useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import { QuadraticBezierLine } from '@react-three/drei'
import * as THREE from 'three'

interface NeuralEdgeProps {
  start: [number, number, number]
  end:   [number, number, number]
  isActive: boolean
  workerId: string
  // justDone is detected internally via isActive true→false transition
}

const OFFSETS = [0, 0.2, 0.4, 0.6, 0.8]

function Particle({ curve, offset, active, color }: {
  curve: THREE.QuadraticBezierCurve3
  offset: number
  active: boolean
  color: string
}) {
  const ref = useRef<THREE.Mesh>(null!)
  const tRef = useRef(offset)

  useFrame((_, delta) => {
    if (!active || !ref.current) return
    tRef.current = (tRef.current + delta / 1.5) % 1
    const pos = curve.getPoint(tRef.current)
    ref.current.position.copy(pos)
  })

  if (!active) return null
  return (
    <mesh ref={ref}>
      <sphereGeometry args={[0.07, 6, 6]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2.5} />
    </mesh>
  )
}

function ReverseBurst({ curve, color }: { curve: THREE.QuadraticBezierCurve3; color: string }) {
  const refs = useRef<Array<THREE.Mesh | null>>([])
  const tRefs = useRef([1.0, 0.8, 0.6, 0.4, 0.2])
  const done = useRef(false)

  useFrame((_, delta) => {
    if (done.current) return
    let allDone = true
    tRefs.current.forEach((t, i) => {
      const next = t - delta * 1.0
      tRefs.current[i] = next
      const mesh = refs.current[i]
      if (mesh) {
        if (next < 0) {
          mesh.visible = false
        } else {
          allDone = false
          const pos = curve.getPoint(Math.max(0, next))
          mesh.position.copy(pos)
        }
      }
    })
    if (allDone) done.current = true
  })

  return (
    <>
      {tRefs.current.map((_, i) => (
        <mesh key={i} ref={el => { refs.current[i] = el }}>
          <sphereGeometry args={[0.07, 6, 6]} />
          <meshStandardMaterial color="#22c55e" emissive="#22c55e" emissiveIntensity={2.5} />
        </mesh>
      ))}
    </>
  )
}

import { AGENT_COLORS } from '../types'

export function NeuralEdge({ start, end, isActive, workerId }: NeuralEdgeProps) {
  const [showBurst, setShowBurst] = useState(false)
  const burstKey = useRef(0)
  const prevActiveRef = useRef(isActive)

  const color = AGENT_COLORS[workerId] ?? '#00f0ff'

  const mid: [number, number, number] = [
    (start[0] + end[0]) / 2,
    (start[1] + end[1]) / 2 + 1.5,
    (start[2] + end[2]) / 2,
  ]

  // Memoized curve — no longer recreated every render
  const curve = useMemo(() => new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(...start),
    new THREE.Vector3(...mid),
    new THREE.Vector3(...end),
  ), [start[0], start[1], start[2], end[0], end[1], end[2], mid[0], mid[1], mid[2]])

  // Detect isActive true→false transition to trigger reverse burst
  useEffect(() => {
    if (!isActive && prevActiveRef.current) {
      burstKey.current += 1
      setShowBurst(true)
      const t = setTimeout(() => setShowBurst(false), 1200)
      prevActiveRef.current = false
      return () => clearTimeout(t)
    }
    prevActiveRef.current = isActive
  }, [isActive])

  return (
    <group>
      <QuadraticBezierLine
        start={start}
        mid={mid}
        end={end}
        color={isActive ? color : '#1e293b'}
        lineWidth={isActive ? 1.5 : 0.5}
        transparent
        opacity={isActive ? 1.0 : undefined}
      />

      {isActive && OFFSETS.map((offset, i) => (
        <Particle key={i} curve={curve} offset={offset} active color={color} />
      ))}

      {showBurst && <ReverseBurst key={burstKey.current} curve={curve} color="#22c55e" />}
    </group>
  )
}
```

- [ ] **Step 2: Note on idle heartbeat**

The idle line opacity heartbeat (pulsing 0.08→0.18) requires `QuadraticBezierLine` to accept a ref for animation. Since drei's `QuadraticBezierLine` doesn't easily expose a ref to the underlying line material, and adding that complexity would require a custom line implementation, the idle heartbeat is omitted from this implementation. The static dim line (`#1e293b`, lineWidth 0.5) still communicates the network connection without movement. This is a pragmatic tradeoff.

- [ ] **Step 3: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1 | head -20
```

NexusScene.tsx errors are expected until Task 18 (AgentNode props changed). Ignore those for now.

- [ ] **Step 4: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/components/NeuralEdge.tsx
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): patch NeuralEdge with useMemo curve, identity colors, reverse burst"
```

---

## Task 9: ProgressRing patch

**Files:**
- Modify: `nexus-ui/src/components/ProgressRing.tsx`

- [ ] **Step 1: Add done→idle fade opacity spring**

Replace the full content of `nexus-ui/src/components/ProgressRing.tsx`:

```typescript
// nexus-ui/src/components/ProgressRing.tsx
import { useRef, useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import { Billboard, Text } from '@react-three/drei'
import { useSpring, animated } from '@react-spring/three'
import * as THREE from 'three'
import type { AgentState } from '../types'

interface ProgressRingProps {
  agent: AgentState
  nodeRadius: number
  lastCheckpointIndex: number
}

export function ProgressRing({ agent, nodeRadius, lastCheckpointIndex }: ProgressRingProps) {
  const meshRef = useRef<THREE.Mesh>(null!)
  const prevCpIdx = useRef(0)
  const { stepCount, status, checkpoints } = agent

  // Scale pulse on new checkpoint
  const [scaleSpring, scaleApi] = useSpring(() => ({
    scale: 1,
    config: { tension: 400, friction: 20 },
  }))

  // Opacity fade when done
  const [opacitySpring, opacityApi] = useSpring(() => ({
    opacity: 0.7,
    config: { duration: 1000 },
  }))

  useEffect(() => {
    if (lastCheckpointIndex > prevCpIdx.current) {
      prevCpIdx.current = lastCheckpointIndex
      scaleApi.start({ scale: 1.4, onRest: () => scaleApi.start({ scale: 1 }) })
    }
  }, [lastCheckpointIndex, scaleApi])

  useEffect(() => {
    if (status === 'done') {
      const t = setTimeout(() => {
        opacityApi.start({ opacity: 0 })
      }, 3000)
      return () => clearTimeout(t)
    } else {
      opacityApi.start({ opacity: 0.7 })
    }
  }, [status, opacityApi])

  useFrame((_, delta) => {
    if (meshRef.current && status === 'working') {
      meshRef.current.rotation.z += delta * 0.8
    }
  })

  if (stepCount === 0) return null

  const innerR = nodeRadius + 0.12
  const outerR = nodeRadius + 0.22
  const color = status === 'done' ? '#22c55e' : '#00f0ff'

  const label = checkpoints.length > 0
    ? `${stepCount} steps · ${checkpoints.length} ✓`
    : `${stepCount} steps`

  return (
    <Billboard>
      <animated.mesh ref={meshRef} scale={scaleSpring.scale}>
        <ringGeometry args={[innerR, outerR, 48]} />
        <animated.meshBasicMaterial
          color={color}
          transparent
          opacity={opacitySpring.opacity}
          side={THREE.DoubleSide}
        />
      </animated.mesh>
      <Text
        position={[0, outerR + 0.15, 0]}
        fontSize={0.13}
        color={color}
        anchorX="center"
        anchorY="bottom"
      >
        {label}
      </Text>
    </Billboard>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/components/ProgressRing.tsx
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "fix(nexus-ui): ProgressRing fades out 3s after done status"
```

---

## Task 10: NodeFlowPanel patch

**Files:**
- Modify: `nexus-ui/src/components/NodeFlowPanel.tsx`

- [ ] **Step 1: Add step duration + checkpoint glow CSS**

Replace `nexus-ui/src/components/NodeFlowPanel.tsx`:

```typescript
// nexus-ui/src/components/NodeFlowPanel.tsx
import { useEffect, useRef } from 'react'
import type { AgentState, Step, Checkpoint } from '../types'
import { TOOL_ICONS, AGENT_COLORS } from '../types'

interface NodeFlowPanelProps {
  agent: AgentState
}

type TimelineItem =
  | { kind: 'step'; data: Step }
  | { kind: 'checkpoint'; data: Checkpoint }

function buildTimeline(steps: Step[], checkpoints: Checkpoint[]): TimelineItem[] {
  const items: TimelineItem[] = []
  let cpIdx = 0
  for (const step of steps) {
    while (cpIdx < checkpoints.length && checkpoints[cpIdx].step <= step.step) {
      items.push({ kind: 'checkpoint', data: checkpoints[cpIdx] })
      cpIdx++
    }
    items.push({ kind: 'step', data: step })
  }
  while (cpIdx < checkpoints.length) {
    items.push({ kind: 'checkpoint', data: checkpoints[cpIdx] })
    cpIdx++
  }
  return items
}

function formatElapsed(ts: number): string {
  const s = (Date.now() - ts) / 1000
  return s < 60 ? `${s.toFixed(1)}s` : `${(s / 60).toFixed(1)}m`
}

export function NodeFlowPanel({ agent }: NodeFlowPanelProps) {
  const { recentSteps, checkpoints, id } = agent
  const bottomRef = useRef<HTMLDivElement>(null)
  const agentColor = AGENT_COLORS[id] ?? '#00f0ff'

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [recentSteps.length, checkpoints.length])

  if (recentSteps.length === 0 && checkpoints.length === 0) return null

  const timeline = buildTimeline(recentSteps, checkpoints)

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.headerLabel}>NODE FLOW</span>
        <span style={styles.headerStats}>
          {recentSteps.length > 0 && `${agent.stepCount} steps`}
          {checkpoints.length > 0 && ` · ${checkpoints.length} ✓`}
        </span>
      </div>
      <div style={styles.list}>
        {timeline.map((item, i) =>
          item.kind === 'checkpoint' ? (
            <div key={`cp-${item.data.index}`} style={styles.checkpointRow}>
              <span style={{ ...styles.cpDiamond, textShadow: `0 0 8px ${agentColor}` }}>◆</span>
              <span style={styles.cpText}>
                <strong>Checkpoint {item.data.index}</strong> · step {item.data.step}
                <br />
                <span style={{ color: '#86efac' }}>{item.data.summary}</span>
              </span>
            </div>
          ) : (
            <div
              key={`step-${item.data.step}-${i}`}
              style={{
                ...styles.stepRow,
                animation: 'slideInStep 0.2s ease-out',
                animationFillMode: 'both',
                animationDelay: `${Math.min(i * 20, 200)}ms`,
              }}
            >
              <span style={styles.stepCircle}>○</span>
              <span style={{ ...styles.stepTool, color: agentColor }}>
                {TOOL_ICONS[item.data.tool] ?? '⚙'} {item.data.tool}
              </span>
              <span style={styles.stepLabel}>{item.data.label}</span>
              <span style={styles.stepElapsed}>{formatElapsed(item.data.ts)}</span>
            </div>
          )
        )}
        <div ref={bottomRef} />
      </div>
      <style>{`
        @keyframes slideInStep {
          from { opacity: 0; transform: translateX(-8px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    borderBottom: '1px solid #1e293b',
    marginBottom: 8,
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.1em',
    color: '#475569',
    textTransform: 'uppercase',
    padding: '6px 0 4px',
  },
  headerLabel: { color: '#475569' },
  headerStats: { color: '#94a3b8', fontWeight: 400 },
  list: {
    maxHeight: 180,
    overflowY: 'auto',
    fontSize: 11,
    lineHeight: '1.6',
  },
  stepRow: {
    display: 'flex',
    gap: 6,
    alignItems: 'baseline',
    borderLeft: '1px solid #1e293b',
    marginLeft: 6,
    paddingLeft: 8,
    paddingBottom: 2,
  },
  stepCircle: { color: '#334155', minWidth: 10 },
  stepTool: {
    minWidth: 64,
    fontFamily: 'JetBrains Mono, monospace',
  },
  stepLabel: {
    color: '#94a3b8',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: 180,
  },
  stepElapsed: {
    color: '#334155',
    fontSize: 10,
    marginLeft: 'auto',
    whiteSpace: 'nowrap',
  },
  checkpointRow: {
    display: 'flex',
    gap: 8,
    alignItems: 'flex-start',
    padding: '4px 0',
    borderTop: '1px solid #1e293b',
  },
  cpDiamond: { color: '#22c55e', minWidth: 16, marginLeft: 2 },
  cpText: { color: '#94a3b8', fontSize: 11 },
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/components/NodeFlowPanel.tsx
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): NodeFlowPanel step duration, slide-in animation, checkpoint glow"
```

---

## Task 11: HoverCard

**Files:**
- Create: `nexus-ui/src/components/HoverCard.tsx`

- [ ] **Step 1: Create HoverCard.tsx**

```typescript
// nexus-ui/src/components/HoverCard.tsx
import { useEffect, useRef } from 'react'
import { useNexusStore } from '../store'
import { AGENT_COLORS } from '../types'

interface HoverCardProps {
  agentId: string
  x: number
  y: number
}

export function HoverCard({ agentId, x, y }: HoverCardProps) {
  const agent = useNexusStore(s => s.agents[agentId])
  const wsModel = useNexusStore(s => s.wsModel)
  const ref = useRef<HTMLDivElement>(null)

  // Keep card on screen
  useEffect(() => {
    if (!ref.current) return
    const el = ref.current
    const rect = el.getBoundingClientRect()
    if (x + rect.width + 16 > window.innerWidth) {
      el.style.left = `${x - rect.width - 8}px`
    }
  })

  if (!agent) return null
  const color = AGENT_COLORS[agentId] ?? '#00f0ff'
  const lastOutput = agent.recentOutput[agent.recentOutput.length - 1] ?? '—'
  const truncated = lastOutput.length > 48 ? lastOutput.slice(0, 48) + '…' : lastOutput

  const modelLabels: Record<string, string> = {
    claude: 'Claude Sonnet',
    gemini: 'Gemini Flash',
    tgpt: 'tgpt',
  }

  return (
    <div
      ref={ref}
      style={{
        position: 'fixed',
        left: x + 16,
        top: y + 8,
        zIndex: 300,
        background: 'rgba(8, 14, 28, 0.95)',
        backdropFilter: 'blur(16px)',
        border: `1px solid ${color}40`,
        boxShadow: `0 0 20px ${color}20`,
        borderRadius: 8,
        padding: '10px 14px',
        minWidth: 200,
        pointerEvents: 'none',
      }}
    >
      <div style={{
        fontFamily: 'Orbitron, sans-serif',
        color,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: '0.08em',
        marginBottom: 6,
      }}>
        {agent.name.toUpperCase()}
        <span style={{ color: '#475569', fontWeight: 400, marginLeft: 8, fontFamily: 'Inter, sans-serif' }}>
          {agent.role}
        </span>
      </div>
      <div style={{ height: 1, background: '#1e293b', marginBottom: 6 }} />
      <div style={{ fontSize: 11, color: '#94a3b8', lineHeight: 1.6 }}>
        <div><span style={{ color: '#475569' }}>Status:</span> {agent.status}</div>
        {agent.stepCount > 0 && (
          <div>
            <span style={{ color: '#475569' }}>Steps:</span> {agent.stepCount}
            {agent.checkpoints.length > 0 && ` · Checkpoints: ${agent.checkpoints.length}`}
          </div>
        )}
        <div><span style={{ color: '#475569' }}>Backend:</span> {modelLabels[wsModel]}</div>
        {agent.recentOutput.length > 0 && (
          <div style={{ color: '#475569', marginTop: 4, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' }}>
            {truncated}
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/components/HoverCard.tsx
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): add HoverCard agent tooltip"
```

---

## Task 12: ModelPill

**Files:**
- Create: `nexus-ui/src/components/ModelPill.tsx`

- [ ] **Step 1: Create ModelPill.tsx**

```typescript
// nexus-ui/src/components/ModelPill.tsx
import { useNexusStore } from '../store'

const MODEL_LABELS: Record<string, string> = {
  claude: 'Claude Sonnet',
  gemini: 'Gemini Flash',
  tgpt:   'tgpt',
}

const MODEL_COLORS: Record<string, string> = {
  claude: '#f59e0b',
  gemini: '#3b82f6',
  tgpt:   '#475569',
}

export function ModelPill() {
  const wsModel = useNexusStore(s => s.wsModel)
  const wsStatus = useNexusStore(s => s.wsStatus)
  const color = MODEL_COLORS[wsModel] ?? '#475569'

  return (
    <div style={{
      position: 'fixed',
      top: 16,
      left: 16,
      zIndex: 10,
      display: 'flex',
      gap: 12,
      alignItems: 'center',
    }}>
      <div style={{
        fontFamily: 'Orbitron, sans-serif',
        fontSize: 11,
        color,
        background: 'rgba(5, 10, 20, 0.85)',
        border: `1px solid ${color}44`,
        borderRadius: 6,
        padding: '4px 10px',
        letterSpacing: '0.06em',
      }}>
        ⚡ {MODEL_LABELS[wsModel] ?? wsModel}
      </div>
      <div style={{
        fontSize: 11,
        color: wsStatus === 'connected' ? '#22c55e' : '#ef4444',
        background: 'rgba(5, 10, 20, 0.85)',
        border: `1px solid ${wsStatus === 'connected' ? '#22c55e44' : '#ef444444'}`,
        borderRadius: 6,
        padding: '4px 10px',
        fontFamily: 'Orbitron, sans-serif',
        letterSpacing: '0.06em',
      }}>
        ● {wsStatus === 'connected' ? 'NEXUS ONLINE' : 'OFFLINE'}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/components/ModelPill.tsx
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): add ModelPill with live backend indicator"
```

---

## Task 13: useVoice hook

**Files:**
- Create: `nexus-ui/src/hooks/useVoice.ts`

- [ ] **Step 1: Create hooks directory and useVoice.ts**

```bash
mkdir -p /mnt/HC_Volume_105874680/virtual-company/nexus-ui/src/hooks
```

```typescript
// nexus-ui/src/hooks/useVoice.ts
import { useState, useEffect, useCallback, useRef } from 'react'
import { onAudioEvent, offAudioEvent } from '../store'

const TTS_KEY = 'nexus-tts-enabled'

// Module-level AudioQueue — shared across all hook instances
const AudioQueue = {
  _queue: [] as Array<{ base64: string; mode: string }>,
  _playing: false,
  _onPlayingChange: null as ((v: boolean) => void) | null,

  push(base64: string, mode: string) {
    this._queue.push({ base64, mode })
    if (!this._playing) this._next()
  },

  async _next() {
    if (!this._queue.length) {
      this._playing = false
      this._onPlayingChange?.(false)
      return
    }
    this._playing = true
    this._onPlayingChange?.(true)

    const { base64, mode } = this._queue.shift()!
    try {
      const binary = atob(base64)
      const bytes = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
      const blob = new Blob([bytes], { type: 'audio/wav' })
      const url = URL.createObjectURL(blob)
      const el = new Audio(url)
      el.onended = () => {
        URL.revokeObjectURL(url)
        this._next()
      }
      el.onerror = () => {
        URL.revokeObjectURL(url)
        this._next()
      }
      await el.play()
    } catch {
      this._next()
    }
  },
}

export function useVoice(agentId: string | null, onTranscript: (text: string) => void) {
  const [isListening, setIsListening] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [ttsEnabled, setTtsEnabled] = useState(() => {
    try { return localStorage.getItem(TTS_KEY) !== 'false' } catch { return true }
  })

  const recogRef = useRef<SpeechRecognition | null>(null)

  // Wire AudioQueue → isSpeaking state
  useEffect(() => {
    AudioQueue._onPlayingChange = setIsSpeaking
    return () => { AudioQueue._onPlayingChange = null }
  }, [])

  // Listen for audio events from WS
  useEffect(() => {
    if (!ttsEnabled) return
    const cb = (base64: string, mode: string) => {
      AudioQueue.push(base64, mode)
    }
    onAudioEvent(cb)
    return () => offAudioEvent(cb)
  }, [ttsEnabled])

  const startListening = useCallback(() => {
    const SpeechRecognition =
      (window as unknown as { SpeechRecognition?: typeof window.SpeechRecognition }).SpeechRecognition ??
      (window as unknown as { webkitSpeechRecognition?: typeof window.SpeechRecognition }).webkitSpeechRecognition

    if (!SpeechRecognition) return

    const recog = new SpeechRecognition()
    recog.continuous = false
    recog.interimResults = false
    recog.lang = 'en-US'

    recog.onresult = (e) => {
      const transcript = e.results[0]?.[0]?.transcript ?? ''
      if (transcript.trim()) onTranscript(transcript.trim())
    }

    recog.onend = () => setIsListening(false)
    recog.onerror = () => setIsListening(false)

    recog.start()
    recogRef.current = recog
    setIsListening(true)
  }, [onTranscript])

  const stopListening = useCallback(() => {
    recogRef.current?.stop()
    recogRef.current = null
    setIsListening(false)
  }, [])

  const toggleTts = useCallback(() => {
    setTtsEnabled(prev => {
      const next = !prev
      try { localStorage.setItem(TTS_KEY, String(next)) } catch {}
      return next
    })
  }, [])

  const hasSpeechRecognition = !!(
    (window as unknown as { SpeechRecognition?: unknown }).SpeechRecognition ??
    (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition
  )

  return {
    isListening,
    isSpeaking,
    ttsEnabled,
    hasSpeechRecognition,
    startListening,
    stopListening,
    toggleTts,
  }
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/hooks/useVoice.ts
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): add useVoice hook with PTT, Bark AudioQueue, TTS toggle"
```

---

## Task 14: AgentDetailView rewrite

**Files:**
- Modify: `nexus-ui/src/components/AgentDetailView.tsx`

- [ ] **Step 1: Replace AgentDetailView.tsx**

```typescript
// nexus-ui/src/components/AgentDetailView.tsx
import { useEffect, useRef, useState, KeyboardEvent } from 'react'
import { useNexusStore, sendWsMessage } from '../store'
import { AGENT_COLORS } from '../types'
import { NodeFlowPanel } from './NodeFlowPanel'
import { useVoice } from '../hooks/useVoice'

export function AgentDetailView() {
  const selectedId  = useNexusStore(s => s.selectedAgent)
  const selectAgent = useNexusStore(s => s.selectAgent)
  const agent       = useNexusStore(s => selectedId ? s.agents[selectedId] : null)
  const [input, setInput] = useState('')
  const [mounted, setMounted] = useState(false)
  const termRef = useRef<HTMLDivElement>(null)

  const color = AGENT_COLORS[selectedId ?? ''] ?? '#00f0ff'

  const handleTranscript = (text: string) => {
    if (!agent) return
    sendWsMessage({ type: 'message', agent: agent.id, text })
    if (voice.ttsEnabled) {
      fetch(`/api/filler?context=${encodeURIComponent(text)}`)
        .then(r => r.json())
        .then(({ audio }) => { /* AudioQueue will receive via onAudioEvent */ })
        .catch(() => {})
    }
  }

  const voice = useVoice(selectedId, handleTranscript)

  // Entrance animation
  useEffect(() => {
    const t = setTimeout(() => setMounted(true), 50)
    return () => clearTimeout(t)
  }, [])

  useEffect(() => {
    termRef.current?.scrollTo({ top: termRef.current.scrollHeight, behavior: 'smooth' })
  }, [agent?.recentOutput.length])

  if (!agent) return null

  const placeholder = agent.id === 'ceo'
    ? 'Talk to Subaru...'
    : `Send message to ${agent.name}...`

  const handleSend = () => {
    const text = input.trim()
    if (!text) return
    sendWsMessage({ type: 'message', agent: agent.id, text })
    if (voice.ttsEnabled) {
      fetch(`/api/filler?context=${encodeURIComponent(text)}`)
        .catch(() => {})
    }
    setInput('')
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleSend()
  }

  const handleMicClick = () => {
    if (voice.isListening) {
      voice.stopListening()
    } else {
      voice.startListening()
    }
  }

  const statusDotColor = agent.status === 'working' ? color
    : agent.status === 'thinking' ? '#7c3aed'
    : agent.status === 'done' ? '#22c55e'
    : '#334155'

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 100,
      opacity: mounted ? 1 : 0,
      transform: mounted ? 'scale(1)' : 'scale(0.92)',
      transition: 'opacity 200ms cubic-bezier(0.16,1,0.3,1), transform 200ms cubic-bezier(0.16,1,0.3,1)',
    }}>
      <div style={{
        width: 560,
        maxHeight: '80vh',
        background: 'rgba(8, 14, 28, 0.82)',
        backdropFilter: 'blur(24px) saturate(1.4)',
        border: `1px solid ${color}59`,
        boxShadow: `0 0 0 1px ${color}1a, 0 0 40px ${color}26, inset 0 1px 0 rgba(255,255,255,0.06)`,
        clipPath: 'polygon(8px 0%, calc(100% - 8px) 0%, 100% 8px, 100% calc(100% - 8px), calc(100% - 8px) 100%, 8px 100%, 0% calc(100% - 8px), 0% 8px)',
        borderRadius: 4,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        padding: '20px 24px',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <button
            onClick={() => { setMounted(false); setTimeout(() => selectAgent(null), 200) }}
            style={{
              background: 'none',
              border: '1px solid #334155',
              color: '#94a3b8',
              borderRadius: 6,
              padding: '4px 10px',
              cursor: 'pointer',
              fontSize: 12,
            }}
          >
            ← Back
          </button>
          <span style={{
            flex: 1,
            fontFamily: 'Orbitron, sans-serif',
            color,
            fontWeight: 700,
            fontSize: 13,
            letterSpacing: '0.1em',
          }}>
            {agent.name.toUpperCase()}
            <span style={{ color: '#475569', fontWeight: 400, fontFamily: 'Inter, sans-serif', letterSpacing: 0, marginLeft: 8 }}>
              • {agent.role}
            </span>
          </span>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: statusDotColor,
            boxShadow: `0 0 6px ${statusDotColor}`,
          }} />
        </div>

        <div style={{ height: 1, background: '#1e293b', marginBottom: 8 }} />

        <NodeFlowPanel agent={agent} />

        {/* Terminal */}
        <div
          ref={termRef}
          style={{
            flex: 1,
            overflowY: 'auto',
            fontFamily: 'JetBrains Mono, monospace',
            fontSize: 12,
            lineHeight: '1.6',
            minHeight: 120,
            maxHeight: 320,
            paddingBottom: 8,
          }}
        >
          {agent.recentOutput.length === 0 ? (
            <div style={{ color: '#334155', fontStyle: 'italic', fontSize: 11 }}>No output yet…</div>
          ) : (
            agent.recentOutput.map((line, i) => (
              <div key={i} style={{
                color: (line.startsWith('Tool:') || line.startsWith('> Tool:')) ? color : '#e2e8f0',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}>
                {line}
              </div>
            ))
          )}
        </div>

        <div style={{ height: 1, background: '#1e293b', marginTop: 8, marginBottom: 10 }} />

        {/* Input row */}
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            style={{
              flex: 1,
              background: '#0f172a',
              border: '1px solid #334155',
              borderRadius: 6,
              color: '#e2e8f0',
              padding: '8px 12px',
              fontSize: 13,
              outline: 'none',
              fontFamily: 'Inter, sans-serif',
            }}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
          />

          {voice.hasSpeechRecognition && (
            <button
              onClick={handleMicClick}
              title={voice.isListening ? 'Stop recording' : 'Start voice input'}
              style={{
                background: voice.isListening ? `${color}22` : 'none',
                border: `1px solid ${voice.isListening ? color : voice.isSpeaking ? '#f59e0b' : '#334155'}`,
                color: voice.isListening ? color : voice.isSpeaking ? '#f59e0b' : '#94a3b8',
                borderRadius: 6,
                padding: '8px 12px',
                cursor: 'pointer',
                fontSize: 14,
                transition: 'all 150ms',
                boxShadow: voice.isListening ? `0 0 8px ${color}66` : 'none',
              }}
            >
              {voice.isSpeaking ? '🔊' : '🎤'}
            </button>
          )}

          <button
            onClick={handleSend}
            style={{
              background: `${color}22`,
              border: `1px solid ${color}66`,
              color,
              borderRadius: 6,
              padding: '8px 16px',
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1 | head -30
```

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/components/AgentDetailView.tsx
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): rewrite AgentDetailView with glassmorphic hex panel and voice button"
```

---

## Task 15: useCommandPalette hook

**Files:**
- Create: `nexus-ui/src/hooks/useCommandPalette.ts`

- [ ] **Step 1: Create useCommandPalette.ts**

```typescript
// nexus-ui/src/hooks/useCommandPalette.ts
import { useState, useEffect, useCallback } from 'react'
import { useNexusStore, connectWebSocket } from '../store'

export interface PaletteAction {
  id: string
  label: string
  group: string
  accent?: string
}

export function useCommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')

  const selectAgent    = useNexusStore(s => s.selectAgent)
  const setIslandTab   = useNexusStore(s => s.setIslandTab)
  const agents         = useNexusStore(s => s.agents)

  const AGENT_ACCENTS: Record<string, string> = {
    ceo:      '#f59e0b',
    backend:  '#3b82f6',
    frontend: '#ec4899',
    qa:       '#f59e0b',
    devops:   '#10b981',
    browser:  '#8b5cf6',
  }

  const actions: PaletteAction[] = [
    ...['ceo', 'backend', 'frontend', 'qa', 'devops', 'browser'].map(id => ({
      id: `agent-${id}`,
      label: `Talk to ${agents[id]?.name ?? id}`,
      group: 'AGENTS',
      accent: AGENT_ACCENTS[id],
    })),
    { id: 'queue-show',   label: 'Show work queue',    group: 'WORK QUEUE' },
    { id: 'notif-show',   label: 'Show notifications', group: 'WORK QUEUE' },
    { id: 'tts-toggle',   label: 'Toggle voice / TTS', group: 'VOICE' },
    { id: 'ws-reconnect', label: 'Reconnect WebSocket', group: 'SYSTEM' },
  ]

  const filtered = query.trim()
    ? actions.filter(a => a.label.toLowerCase().includes(query.toLowerCase()))
    : actions

  const runAction = useCallback((id: string, toggleTts?: () => void) => {
    setOpen(false)
    setQuery('')

    if (id.startsWith('agent-')) {
      selectAgent(id.replace('agent-', ''))
    } else if (id === 'queue-show') {
      setIslandTab('queue')
    } else if (id === 'notif-show') {
      setIslandTab('notifications')
    } else if (id === 'tts-toggle') {
      toggleTts?.()
    } else if (id === 'ws-reconnect') {
      connectWebSocket()
    }
  }, [selectAgent, setIslandTab])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setOpen(prev => !prev)
      }
      if (e.key === 'Escape') {
        setOpen(false)
        setQuery('')
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return { open, setOpen, query, setQuery, filtered, runAction }
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/hooks/useCommandPalette.ts
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): add useCommandPalette hook with ⌘K keybind and action registry"
```

---

## Task 16: CommandPalette component

**Files:**
- Create: `nexus-ui/src/components/CommandPalette.tsx`

- [ ] **Step 1: Create CommandPalette.tsx**

```typescript
// nexus-ui/src/components/CommandPalette.tsx
import { useEffect, useRef } from 'react'
import type { PaletteAction } from '../hooks/useCommandPalette'

interface CommandPaletteProps {
  open: boolean
  query: string
  filtered: PaletteAction[]
  onQueryChange: (q: string) => void
  onAction: (id: string) => void
  onClose: () => void
}

export function CommandPalette({ open, query, filtered, onQueryChange, onAction, onClose }: CommandPaletteProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50)
  }, [open])

  if (!open) return null

  // Group actions
  const groups: Record<string, PaletteAction[]> = {}
  for (const action of filtered) {
    if (!groups[action.group]) groups[action.group] = []
    groups[action.group].push(action)
  }

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, zIndex: 190,
          background: 'rgba(2, 4, 8, 0.6)',
          backdropFilter: 'blur(4px)',
        }}
      />

      {/* Panel */}
      <div style={{
        position: 'fixed',
        top: '18%',
        left: '50%',
        transform: 'translateX(-50%)',
        width: 520,
        zIndex: 200,
        background: 'rgba(5, 10, 20, 0.95)',
        backdropFilter: 'blur(32px)',
        border: '1px solid rgba(0, 240, 255, 0.15)',
        borderRadius: 12,
        overflow: 'hidden',
        boxShadow: '0 0 60px rgba(0, 240, 255, 0.08)',
        animation: 'paletteIn 180ms cubic-bezier(0.16, 1, 0.3, 1)',
      }}>
        <style>{`
          @keyframes paletteIn {
            from { opacity: 0; transform: translateX(-50%) translateY(-8px); }
            to   { opacity: 1; transform: translateX(-50%) translateY(0); }
          }
        `}</style>

        {/* Search input */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px', borderBottom: '1px solid #1e293b' }}>
          <span style={{ color: '#475569', fontSize: 14, fontFamily: 'Orbitron, sans-serif' }}>⌘</span>
          <input
            ref={inputRef}
            value={query}
            onChange={e => onQueryChange(e.target.value)}
            placeholder="Search or command..."
            style={{
              flex: 1,
              background: 'none',
              border: 'none',
              outline: 'none',
              color: '#e2e8f0',
              fontSize: 14,
              fontFamily: 'Inter, sans-serif',
            }}
          />
          <span
            onClick={onClose}
            style={{ color: '#475569', fontSize: 11, cursor: 'pointer', padding: '2px 6px', border: '1px solid #334155', borderRadius: 4 }}
          >
            Esc
          </span>
        </div>

        {/* Actions */}
        <div style={{ maxHeight: 360, overflowY: 'auto', padding: '8px 0' }}>
          {Object.entries(groups).map(([group, items]) => (
            <div key={group}>
              <div style={{
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: '0.1em',
                color: '#334155',
                padding: '8px 16px 4px',
                fontFamily: 'Orbitron, sans-serif',
              }}>
                {group}
              </div>
              {items.map(action => (
                <div
                  key={action.id}
                  onClick={() => onAction(action.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    padding: '9px 16px',
                    cursor: 'pointer',
                    color: action.accent ?? '#94a3b8',
                    fontSize: 13,
                    transition: 'background 100ms',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,240,255,0.04)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  {action.accent && (
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: action.accent, flexShrink: 0 }} />
                  )}
                  {action.label}
                </div>
              ))}
            </div>
          ))}
          {filtered.length === 0 && (
            <div style={{ color: '#334155', fontSize: 13, padding: '12px 16px', fontStyle: 'italic' }}>
              No commands found
            </div>
          )}
        </div>
      </div>
    </>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/components/CommandPalette.tsx
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): add CommandPalette component with grouped actions and fuzzy search"
```

---

## Task 17: SmartIsland

**Files:**
- Create: `nexus-ui/src/components/SmartIsland.tsx`

- [ ] **Step 1: Create SmartIsland.tsx**

```typescript
// nexus-ui/src/components/SmartIsland.tsx
import { useNexusStore } from '../store'

const TAB_LABELS = {
  notifications: 'NOTIFS',
  queue: 'QUEUE',
  active: 'ACTIVE',
} as const

export function SmartIsland() {
  const expanded     = useNexusStore(s => s.islandExpanded)
  const tab          = useNexusStore(s => s.islandTab)
  const setExpanded  = useNexusStore(s => s.setIslandExpanded)
  const setTab       = useNexusStore(s => s.setIslandTab)
  const notifications = useNexusStore(s => s.notifications)
  const workQueue    = useNexusStore(s => s.workQueue)
  const agents       = useNexusStore(s => s.agents)

  const activeWorkers = Object.values(agents).filter(a => a.status === 'working' && a.id !== 'ceo')
  const pendingCount = workQueue.filter(q => q.status === 'pending' || q.status === 'active').length

  const chipLabel = [
    activeWorkers.length > 0 && `${activeWorkers.length} active`,
    pendingCount > 0 && `${pendingCount} queued`,
    !activeWorkers.length && !pendingCount && 'Idle',
  ].filter(Boolean).join(' · ')

  const STATUS_COLORS: Record<string, string> = {
    pending:   '#f59e0b',
    active:    '#00f0ff',
    blocked:   '#ef4444',
    completed: '#22c55e',
  }

  return (
    <div style={{
      position: 'fixed',
      bottom: 24,
      right: 24,
      zIndex: 50,
      fontFamily: 'Inter, sans-serif',
    }}>
      {expanded ? (
        <div style={{
          width: 320,
          background: 'rgba(8, 14, 28, 0.92)',
          backdropFilter: 'blur(20px)',
          border: '1px solid rgba(0, 240, 255, 0.12)',
          borderRadius: 10,
          overflow: 'hidden',
          boxShadow: '0 0 30px rgba(0, 240, 255, 0.06)',
          animation: 'islandIn 200ms cubic-bezier(0.16, 1, 0.3, 1)',
        }}>
          <style>{`
            @keyframes islandIn {
              from { opacity: 0; transform: translateY(8px); }
              to   { opacity: 1; transform: translateY(0); }
            }
          `}</style>

          {/* Tabs */}
          <div style={{ display: 'flex', borderBottom: '1px solid #1e293b' }}>
            {(['notifications', 'queue', 'active'] as const).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                style={{
                  flex: 1,
                  background: tab === t ? 'rgba(0, 240, 255, 0.08)' : 'none',
                  border: 'none',
                  borderBottom: tab === t ? '2px solid #00f0ff' : '2px solid transparent',
                  color: tab === t ? '#00f0ff' : '#475569',
                  padding: '10px 0',
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: '0.08em',
                  cursor: 'pointer',
                  fontFamily: 'Orbitron, sans-serif',
                }}
              >
                {TAB_LABELS[t]}
              </button>
            ))}
            <button
              onClick={() => setExpanded(false)}
              style={{
                background: 'none', border: 'none',
                color: '#334155', cursor: 'pointer',
                padding: '10px 12px', fontSize: 12,
              }}
            >
              ×
            </button>
          </div>

          {/* Content */}
          <div style={{ maxHeight: 220, overflowY: 'auto', padding: '8px 0' }}>
            {tab === 'notifications' && (
              notifications.length === 0 ? (
                <div style={{ color: '#334155', fontSize: 12, padding: '12px 14px', fontStyle: 'italic' }}>
                  No notifications yet
                </div>
              ) : notifications.map(n => (
                <div key={n.id} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                  padding: '8px 14px', borderBottom: '1px solid #0d1117', fontSize: 12,
                }}>
                  <span style={{ color: '#e2e8f0', flex: 1 }}>
                    {n.type === 'done' && '✓ '}
                    {n.type === 'delegation' && '⚡ '}
                    {n.type === 'queue' && '📋 '}
                    {n.text}
                  </span>
                  <span style={{ color: '#334155', fontSize: 10, marginLeft: 8, whiteSpace: 'nowrap' }}>
                    {Math.round((Date.now() - n.ts) / 60000)}m ago
                  </span>
                </div>
              ))
            )}

            {tab === 'queue' && (
              workQueue.length === 0 ? (
                <div style={{ color: '#334155', fontSize: 12, padding: '12px 14px', fontStyle: 'italic' }}>
                  No tasks in queue
                </div>
              ) : workQueue.map((item, i) => (
                <div key={item.id} style={{
                  display: 'flex', gap: 8, alignItems: 'center',
                  padding: '8px 14px', borderBottom: '1px solid #0d1117', fontSize: 12,
                }}>
                  <span style={{ color: '#475569', minWidth: 20 }}>[{i + 1}]</span>
                  <span style={{ color: '#e2e8f0', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.task}
                  </span>
                  <span style={{ color: STATUS_COLORS[item.status] ?? '#475569', fontSize: 10, whiteSpace: 'nowrap' }}>
                    {item.status}
                  </span>
                </div>
              ))
            )}

            {tab === 'active' && (
              activeWorkers.length === 0 ? (
                <div style={{ color: '#334155', fontSize: 12, padding: '12px 14px', fontStyle: 'italic' }}>
                  No active workers
                </div>
              ) : activeWorkers.map(a => {
                const lastStep = a.recentSteps[a.recentSteps.length - 1]
                return (
                  <div key={a.id} style={{
                    display: 'flex', gap: 8, alignItems: 'center',
                    padding: '8px 14px', borderBottom: '1px solid #0d1117', fontSize: 12,
                  }}>
                    <span style={{ color: '#00f0ff', minWidth: 80, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {lastStep ? `${lastStep.tool}` : '…'}
                    </span>
                    <span style={{ color: '#94a3b8', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {a.name}
                    </span>
                    <span style={{ color: '#475569', fontSize: 10 }}>
                      {lastStep ? `${Math.round((Date.now() - lastStep.ts) / 1000)}s` : ''}
                    </span>
                  </div>
                )
              })
            )}
          </div>
        </div>
      ) : (
        <button
          onClick={() => setExpanded(true)}
          style={{
            background: 'rgba(8, 14, 28, 0.92)',
            backdropFilter: 'blur(16px)',
            border: '1px solid rgba(0, 240, 255, 0.15)',
            borderRadius: 20,
            color: activeWorkers.length > 0 ? '#00f0ff' : '#475569',
            padding: '6px 14px',
            fontSize: 11,
            cursor: 'pointer',
            fontFamily: 'Inter, sans-serif',
            boxShadow: activeWorkers.length > 0 ? '0 0 12px rgba(0, 240, 255, 0.15)' : 'none',
          }}
        >
          ● {chipLabel}
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/components/SmartIsland.tsx
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): add SmartIsland collapsible 3-tab panel"
```

---

## Task 18: NexusScene rewrite — wire everything

**Files:**
- Modify: `nexus-ui/src/components/NexusScene.tsx`

- [ ] **Step 1: Replace NexusScene.tsx**

```typescript
// nexus-ui/src/components/NexusScene.tsx
import { useState, useCallback } from 'react'
import { Canvas } from '@react-three/fiber'
import { CameraControls } from '@react-three/drei'
import { Background } from './Background'
import { CeoNode } from './CeoNode'
import { AgentNode } from './AgentNode'
import { NeuralEdge } from './NeuralEdge'
import { PostProcessing } from './PostProcessing'
import { AgentDetailView } from './AgentDetailView'
import { CommandPalette } from './CommandPalette'
import { SmartIsland } from './SmartIsland'
import { HoverCard } from './HoverCard'
import { ModelPill } from './ModelPill'
import { useNexusStore } from '../store'
import { AGENT_POSITIONS } from '../types'
import { useCommandPalette } from '../hooks/useCommandPalette'
import { useVoice } from '../hooks/useVoice'

const WORKER_IDS = ['backend', 'frontend', 'qa', 'devops', 'browser'] as const

interface HoverState {
  agentId: string
  x: number
  y: number
}

export function NexusScene() {
  const agents        = useNexusStore(s => s.agents)
  const edges         = useNexusStore(s => s.edges)
  const selectedAgent = useNexusStore(s => s.selectedAgent)

  const [hover, setHover] = useState<HoverState | null>(null)
  // justDone is now detected inside NeuralEdge via isActive true→false transition
  const { isSpeaking } = useVoice(null, () => {})

  const palette = useCommandPalette()

  const handleHoverEnter = useCallback((id: string, x: number, y: number) => {
    setHover({ agentId: id, x, y })
  }, [])

  const handleHoverLeave = useCallback(() => {
    setTimeout(() => setHover(null), 300)
  }, [])

  const canvasStyle = {
    background: '#020408',
    filter: selectedAgent ? 'blur(3px) brightness(0.6)' : 'none',
    transition: 'filter 300ms ease',
  } as React.CSSProperties

  const ceoPos = AGENT_POSITIONS['ceo']!

  return (
    <div style={{ width: '100vw', height: '100vh', position: 'relative' }}>
      {/* HUD layer — always on top of canvas */}
      <ModelPill />
      <SmartIsland />

      <Canvas
        camera={{ position: [0, 2, 10], fov: 60 }}
        style={canvasStyle}
        gl={{ antialias: true, alpha: false }}
      >
        <Background />

        {/* CEO arc reactor */}
        {agents['ceo'] && (
          <CeoNode
            isSpeaking={isSpeaking}
            onClick={() => {}}
          />
        )}

        {/* Worker nodes + edges */}
        {WORKER_IDS.map(id => {
          const agent = agents[id]
          if (!agent) return null
          const pos = AGENT_POSITIONS[id]!
          const edge = edges.find(e => e.to === id)
          const dimmed = !!selectedAgent && selectedAgent !== id
          return (
            <group key={id}>
              <NeuralEdge
                start={ceoPos}
                end={pos}
                isActive={edge?.isActive ?? false}
                workerId={id}
              />
              <AgentNode
                agent={agent}
                position={pos}
                dimmed={dimmed}
                onHoverEnter={handleHoverEnter}
                onHoverLeave={handleHoverLeave}
              />
            </group>
          )
        })}

        <CameraControls />
        <PostProcessing />
      </Canvas>

      {/* DOM overlays */}
      {selectedAgent && <AgentDetailView />}

      {hover && !selectedAgent && (
        <HoverCard agentId={hover.agentId} x={hover.x} y={hover.y} />
      )}

      <CommandPalette
        open={palette.open}
        query={palette.query}
        filtered={palette.filtered}
        onQueryChange={palette.setQuery}
        onAction={(id) => palette.runAction(id)}
        onClose={() => palette.setOpen(false)}
      />
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript — expect clean build**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npx tsc --noEmit 2>&1
```

Expected: zero errors. If errors remain, fix them before proceeding.

- [ ] **Step 3: Production build**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npm run build 2>&1 | tail -30
```

Expected: build succeeds, `app/static/` is updated.

- [ ] **Step 4: Smoke test — start dev server**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npm run dev &
sleep 3
curl -s http://127.0.0.1:5173/ | grep -o '<title>.*</title>'
```

Expected: returns an HTML title tag (page loads).

- [ ] **Step 5: Commit**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add nexus-ui/src/components/NexusScene.tsx
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "feat(nexus-ui): wire NexusScene — CEO arc reactor, PostProcessing, palette, island, hover"
```

---

## Task 19: Final build and deploy

**Files:**
- Modify: `nexus-ui/` (build output only)

- [ ] **Step 1: Full production build**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui
npm run build 2>&1
```

Expected output ends with something like:
```
✓ built in Xs
dist/index.html
dist/assets/index-[hash].js   ~465 kB │ gzip: ~145 kB
```

If build fails: run `npx tsc --noEmit` first to identify TypeScript errors, fix them, then rebuild.

- [ ] **Step 2: Verify static files updated**

```bash
ls -la /mnt/HC_Volume_105874680/virtual-company/app/static/assets/ | head -5
```

Expected: `index-[hash].js` with a recent timestamp.

- [ ] **Step 3: Restart the app container if running**

```bash
docker ps | grep virtual-company
```

If the container is running:
```bash
docker restart virtual-company 2>/dev/null || true
```

- [ ] **Step 4: End-to-end check**

```bash
sleep 5
curl -s http://127.0.0.1:3030/ | grep -o '<title>.*</title>'
```

Expected: returns an HTML title tag (FastAPI serving the new build).

- [ ] **Step 5: Visual checklist (open in browser)**

Open `http://127.0.0.1:3030` (or the public tunnel URL) and confirm:

- [ ] Gold arc reactor visible at center-front with rotating rings
- [ ] 5 worker icosahedra visible behind CEO in arc formation
- [ ] GPU bloom visible (glowing emissive surfaces have soft halos)
- [ ] Cortical wave ripples outward from CEO on floor
- [ ] Model pill top-left shows "⚡ Claude Sonnet"
- [ ] WS status shows "NEXUS ONLINE" or "OFFLINE"
- [ ] Smart island chip visible bottom-right
- [ ] ⌘K (or Ctrl+K) opens command palette
- [ ] Clicking a worker node: node shatters, glassmorphic hex panel appears
- [ ] Panel shows agent name in Orbitron font with agent color
- [ ] Back button dismisses panel, nodes restore brightness
- [ ] 🎤 button visible in panel input row (if Chrome/Edge)

- [ ] **Step 6: Commit build output**

```bash
git -C /mnt/HC_Volume_105874680/virtual-company add app/static/
git -C /mnt/HC_Volume_105874680/virtual-company commit -m "build(nexus-ui): neural command center production build"
```

---

## Known Limitations & Follow-Ups

| Item | Status | Notes |
|---|---|---|
| Idle edge heartbeat opacity animation | Deferred | `QuadraticBezierLine` doesn't expose material ref easily |
| Per-particle agent color for Class C data streaks | Simplified | All particles same color; requires vertex color buffer material |
| Orbitron font in drei `<Text>` | May need tuning | If CORS blocks woff2 URL, use `@fontsource/orbitron` package instead |
| Camera spring animation on node click | Not implemented | `CameraControls` programmatic spring requires ref + `setLookAt`; omitted to avoid camera fighting with user orbit. Panel entrance animation compensates. |
| TTS filler audio | Requires backend `/api/filler` | Backend already has this endpoint; frontend fetch is wired |
| Image drag-drop (Claude vision) | Out of scope | Backend not yet wired for vision in LangGraph graph |
