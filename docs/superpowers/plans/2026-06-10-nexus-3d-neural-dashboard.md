# NEXUS 3D Neural Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing plain-JS UI (`app/static/index.html` + `app.js` + `style.css`) with a full-screen React Three Fiber dashboard — six 3D agent nodes, neural particle streams, live ProgressRing per node, and a click-to-zoom detail view with NodeFlowPanel checkpoint timeline.

**Architecture:** New `nexus-ui/` Vite+React project. `npm run build` writes to `app/static/` (no Dockerfile changes). FastAPI serves the SPA via a catch-all fallback route. Zustand store subscribes to the existing WebSocket protocol plus two new additive events (`worker_step`, `worker_checkpoint`) defined in the LangGraph design spec.

**Tech Stack:** Vite 5, React 18, TypeScript, `@react-three/fiber ^8`, `@react-three/drei ^9`, `three ^0.165`, `zustand ^4`, `@react-spring/three ^9`.

**Spec:** `docs/superpowers/specs/2026-06-10-nexus-3d-neural-dashboard-design.md`

---

## File Map

| Action | File | Purpose |
|---|---|---|
| Create | `nexus-ui/package.json` | Vite+R3F deps |
| Create | `nexus-ui/vite.config.ts` | outDir → `../app/static`, dev proxy `/ws` |
| Create | `nexus-ui/tsconfig.json` | strict TypeScript |
| Create | `nexus-ui/index.html` | Vite HTML entrypoint |
| Create | `nexus-ui/src/main.tsx` | React root mount |
| Create | `nexus-ui/src/types.ts` | All shared TS interfaces |
| Create | `nexus-ui/src/store.ts` | Zustand store + WebSocket hook |
| Create | `nexus-ui/src/components/Background.tsx` | Grid + particles + fog |
| Create | `nexus-ui/src/components/NeuralEdge.tsx` | Animated bezier particle stream |
| Create | `nexus-ui/src/components/ProgressRing.tsx` | Step-count arc ring on each node |
| Create | `nexus-ui/src/components/AgentNode.tsx` | 3D icosahedron + label + ProgressRing |
| Create | `nexus-ui/src/components/NodeFlowPanel.tsx` | Checkpoint timeline inside detail view |
| Create | `nexus-ui/src/components/AgentDetailView.tsx` | DOM overlay: terminal + chat |
| Create | `nexus-ui/src/components/NexusScene.tsx` | R3F Canvas root wiring everything together |
| Modify | `app/api/router.py` | Add SPA catch-all fallback route |

---

## Task 1: Project Setup

**Files:**
- Create: `nexus-ui/package.json`
- Create: `nexus-ui/vite.config.ts`
- Create: `nexus-ui/tsconfig.json`
- Create: `nexus-ui/index.html`

- [ ] **Step 1: Create nexus-ui/package.json**

```json
{
  "name": "nexus-ui",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@react-spring/three": "^9.7.3",
    "@react-three/drei": "^9.109.2",
    "@react-three/fiber": "^8.17.6",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "three": "^0.165.0",
    "zustand": "^4.5.4"
  },
  "devDependencies": {
    "@types/react": "^18.3.4",
    "@types/react-dom": "^18.3.0",
    "@types/three": "^0.165.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.2"
  }
}
```

- [ ] **Step 2: Create nexus-ui/vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../app/static',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/ws': { target: 'ws://127.0.0.1:3031', ws: true },
      '/api': { target: 'http://127.0.0.1:3031' },
    },
  },
})
```

- [ ] **Step 3: Create nexus-ui/tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

- [ ] **Step 4: Create nexus-ui/index.html**

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>NEXUS Command Center</title>
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      body { background: #050a14; overflow: hidden; }
      #root { width: 100vw; height: 100vh; }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Install dependencies**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npm install
```

Expected: node_modules created, no errors.

- [ ] **Step 6: Verify TypeScript compiles (will fail — no src/ yet)**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && mkdir -p src && echo 'export {}' > src/main.tsx && npx tsc --noEmit 2>&1 | head -5
```

Expected: exits cleanly or only missing-file errors. Fix any config errors before continuing.

- [ ] **Step 7: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add nexus-ui/
git commit -m "feat: scaffold nexus-ui Vite+React project with R3F deps"
```

---

## Task 2: Types + Zustand Store

**Files:**
- Create: `nexus-ui/src/types.ts`
- Create: `nexus-ui/src/store.ts`
- Create: `nexus-ui/src/main.tsx`

- [ ] **Step 1: Create nexus-ui/src/types.ts**

```typescript
// nexus-ui/src/types.ts

export type AgentStatus = 'idle' | 'thinking' | 'working' | 'done'

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

export const AGENT_POSITIONS: Record<string, [number, number, number]> = {
  ceo:      [0,  0.5,  4],
  backend:  [-3, 0,   -1],
  frontend: [-2, 0,   -3],
  qa:       [0,  0,   -2],
  devops:   [2,  0,   -1],
  browser:  [3,  0,   -3],
}

export const AGENT_RADII: Record<string, number> = {
  ceo: 0.9,
  backend: 0.6,
  frontend: 0.6,
  qa: 0.6,
  devops: 0.6,
  browser: 0.6,
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

- [ ] **Step 2: Create nexus-ui/src/store.ts**

```typescript
// nexus-ui/src/store.ts
import { create } from 'zustand'
import type { AgentState, EdgeState, Step, Checkpoint } from './types'

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

interface NexusStore {
  agents: Record<string, AgentState>
  edges: EdgeState[]
  selectedAgent: string | null
  wsStatus: 'connected' | 'offline'

  selectAgent: (id: string | null) => void
  setWsStatus: (s: 'connected' | 'offline') => void
  handleEvent: (event: Record<string, unknown>) => void
}

export const useNexusStore = create<NexusStore>((set, get) => ({
  agents: Object.fromEntries(
    ['ceo', ...WORKER_IDS].map(id => [id, defaultAgent(id)])
  ),
  edges: defaultEdges(),
  selectedAgent: null,
  wsStatus: 'offline',

  selectAgent: (id) => set({ selectedAgent: id }),
  setWsStatus: (s) => set({ wsStatus: s }),

  handleEvent: (event) => {
    const type = event.type as string
    const agentId = event.agent as string | undefined

    set(state => {
      const agents = { ...state.agents }
      const edges = [...state.edges]

      const updateAgent = (id: string, patch: Partial<AgentState>) => {
        agents[id] = { ...(agents[id] ?? defaultAgent(id)), ...patch }
      }

      switch (type) {
        case 'init': {
          const list = (event.agents as Array<{ id: string; name: string; role: string }>) ?? []
          list.forEach(a => {
            agents[a.id] = { ...defaultAgent(a.id, a.name, a.role), ...agents[a.id] }
          })
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
          }
          break

        case 'worker_done':
          if (agentId) {
            updateAgent(agentId, {
              status: 'done',
              stepCount: 0,
              recentSteps: [],
              checkpoints: [],
            })
            const edge = edges.find(e => e.to === agentId)
            if (edge) edge.isActive = false
          }
          break

        case 'worker_step': {
          if (!agentId) break
          const step: Step = {
            step: event.step as number,
            tool: event.tool as string,
            label: event.label as string,
            ts: Date.now(),
          }
          const prev = agents[agentId] ?? defaultAgent(agentId)
          const recentSteps = [...prev.recentSteps, step].slice(-20)
          updateAgent(agentId, {
            stepCount: event.step as number,
            recentSteps,
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
          const recentOutput = [...prev3.recentOutput, content].slice(-500)
          updateAgent(agentId, { recentOutput })
          break
        }

        case 'done':
          if (agentId) updateAgent(agentId, { status: 'idle' })
          break

        case 'error':
          if (agentId) updateAgent(agentId, { status: 'idle' })
          break
      }

      return { agents, edges }
    })
  },
}))

// ── WebSocket hook ─────────────────────────────────────────────────────────────

let _ws: WebSocket | null = null
let _retryDelay = 1000

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
      const data = JSON.parse(ev.data)
      useNexusStore.getState().handleEvent(data)
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

- [ ] **Step 3: Create nexus-ui/src/main.tsx**

```tsx
// nexus-ui/src/main.tsx
import { StrictMode, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { connectWebSocket } from './store'

function App() {
  useEffect(() => {
    connectWebSocket()
  }, [])

  return <div style={{ width: '100vw', height: '100vh', background: '#050a14' }} />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
)
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Verify Vite builds**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npm run build 2>&1 | tail -10
```

Expected: `built in Xs` with no errors. `app/static/` now has `index.html` and `assets/`.

- [ ] **Step 6: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add nexus-ui/src/
git commit -m "feat: add types.ts, Zustand store, WebSocket hook, and main.tsx"
```

---

## Task 3: Background (Grid + Particles + Fog)

**Files:**
- Create: `nexus-ui/src/components/Background.tsx`

- [ ] **Step 1: Create nexus-ui/src/components/Background.tsx**

```tsx
// nexus-ui/src/components/Background.tsx
import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

const PARTICLE_COUNT = 300
const RANGE = 20

function makePositions() {
  const pos = new Float32Array(PARTICLE_COUNT * 3)
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    pos[i * 3]     = (Math.random() - 0.5) * RANGE * 2
    pos[i * 3 + 1] = (Math.random() - 0.5) * RANGE * 2
    pos[i * 3 + 2] = (Math.random() - 0.5) * RANGE * 2
  }
  return pos
}

export function Background() {
  const pointsRef = useRef<THREE.Points>(null!)
  const posRef = useRef(makePositions())

  useFrame((_, delta) => {
    const pos = posRef.current
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      pos[i * 3 + 1] += delta * 0.3
      if (pos[i * 3 + 1] > RANGE) pos[i * 3 + 1] -= RANGE * 2
    }
    if (pointsRef.current) {
      (pointsRef.current.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true
    }
  })

  return (
    <>
      <fog attach="fog" args={['#050a14', 8, 40]} />
      <ambientLight intensity={0.3} />
      <gridHelper args={[40, 40, '#0ea5e966', '#0ea5e933']} position={[0, -4, 0]} />
      <points ref={pointsRef}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[posRef.current, 3]}
          />
        </bufferGeometry>
        <pointsMaterial color="#0ea5e9" size={0.05} transparent opacity={0.6} />
      </points>
    </>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add nexus-ui/src/components/Background.tsx
git commit -m "feat: add Background component (grid, particles, fog)"
```

---

## Task 4: NeuralEdge (Animated Bezier Particle Stream)

**Files:**
- Create: `nexus-ui/src/components/NeuralEdge.tsx`

- [ ] **Step 1: Create nexus-ui/src/components/NeuralEdge.tsx**

```tsx
// nexus-ui/src/components/NeuralEdge.tsx
import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { QuadraticBezierLine } from '@react-three/drei'
import * as THREE from 'three'

interface NeuralEdgeProps {
  start: [number, number, number]
  end: [number, number, number]
  isActive: boolean
}

const OFFSETS = [0, 0.33, 0.66]

function Particle({ curve, offset, active }: {
  curve: THREE.QuadraticBezierCurve3
  offset: number
  active: boolean
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
      <sphereGeometry args={[0.08, 6, 6]} />
      <meshStandardMaterial color="#00f0ff" emissive="#00f0ff" emissiveIntensity={2} />
    </mesh>
  )
}

export function NeuralEdge({ start, end, isActive }: NeuralEdgeProps) {
  const mid: [number, number, number] = [
    (start[0] + end[0]) / 2,
    (start[1] + end[1]) / 2 + 1.5,
    (start[2] + end[2]) / 2,
  ]

  const curve = new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(...start),
    new THREE.Vector3(...mid),
    new THREE.Vector3(...end),
  )

  return (
    <group>
      <QuadraticBezierLine
        start={start}
        mid={mid}
        end={end}
        color={isActive ? '#00f0ff' : '#1e293b'}
        lineWidth={isActive ? 1.5 : 0.5}
      />
      {OFFSETS.map((offset, i) => (
        <Particle key={i} curve={curve} offset={offset} active={isActive} />
      ))}
    </group>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add nexus-ui/src/components/NeuralEdge.tsx
git commit -m "feat: add NeuralEdge animated bezier particle stream"
```

---

## Task 5: ProgressRing

**Files:**
- Create: `nexus-ui/src/components/ProgressRing.tsx`

- [ ] **Step 1: Create nexus-ui/src/components/ProgressRing.tsx**

```tsx
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

  const [springs, api] = useSpring(() => ({
    scale: 1,
    config: { tension: 400, friction: 20 },
  }))

  // Pulse only when a NEW checkpoint arrives (not on mount)
  useEffect(() => {
    if (lastCheckpointIndex > prevCpIdx.current) {
      prevCpIdx.current = lastCheckpointIndex
      api.start({ scale: 1.4, onRest: () => api.start({ scale: 1 }) })
    }
  }, [lastCheckpointIndex, api])

  useFrame((_, delta) => {
    if (meshRef.current && status === 'working') {
      meshRef.current.rotation.z += delta * 0.8
    }
  })

  if (stepCount === 0) return null

  const innerR = nodeRadius + 0.12
  const outerR = nodeRadius + 0.22

  let color = '#00f0ff'
  let opacity = 0.7
  if (status === 'done') {
    color = '#22c55e'
    opacity = 0.9
  }

  const label = checkpoints.length > 0
    ? `${stepCount} steps · ${checkpoints.length} ✓`
    : `${stepCount} steps`

  return (
    <Billboard>
      <animated.mesh ref={meshRef} scale={springs.scale}>
        <ringGeometry args={[innerR, outerR, 48]} />
        <meshBasicMaterial color={color} transparent opacity={opacity} side={THREE.DoubleSide} />
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

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add nexus-ui/src/components/ProgressRing.tsx
git commit -m "feat: add ProgressRing 3D arc with checkpoint pulse animation"
```

---

## Task 6: AgentNode (3D Icosahedron + Label + ProgressRing)

**Files:**
- Create: `nexus-ui/src/components/AgentNode.tsx`

- [ ] **Step 1: Create nexus-ui/src/components/AgentNode.tsx**

```tsx
// nexus-ui/src/components/AgentNode.tsx
import { useRef, useState, useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import { Text } from '@react-three/drei'
import * as THREE from 'three'
import type { AgentState } from '../types'
import { AGENT_RADII } from '../types'
import { ProgressRing } from './ProgressRing'
import { useNexusStore } from '../store'

interface AgentNodeProps {
  agent: AgentState
  position: [number, number, number]
}

const STATUS_COLORS: Record<string, string> = {
  idle:     '#1e293b',
  thinking: '#7c3aed',
  working:  '#00f0ff',
  done:     '#22c55e',
}

export function AgentNode({ agent, position }: AgentNodeProps) {
  const meshRef = useRef<THREE.Mesh>(null!)
  const { status, id, name, role } = agent
  const radius = AGENT_RADII[id] ?? 0.6
  const selectAgent = useNexusStore(s => s.selectAgent)
  const [pulse, setPulse] = useState(0)
  const lastCpIdx = agent.checkpoints.length

  useEffect(() => {
    if (status === 'done') {
      const timer = setTimeout(() => {}, 1000)
      return () => clearTimeout(timer)
    }
  }, [status])

  useFrame((_, delta) => {
    if (!meshRef.current) return
    const mat = meshRef.current.material as THREE.MeshStandardMaterial
    const color = STATUS_COLORS[status] ?? '#1e293b'
    mat.color.set(color)
    mat.emissive.set(color)

    if (status === 'thinking') {
      const t = (Math.sin(Date.now() / 1000 * Math.PI) + 1) / 2
      mat.emissiveIntensity = 0.3 + t * 0.7
    } else if (status === 'working') {
      const t = (Math.sin(Date.now() / 500 * Math.PI) + 1) / 2
      mat.emissiveIntensity = 0.5 + t * 1.0
    } else if (status === 'done') {
      mat.emissiveIntensity = 1.5
    } else {
      mat.emissiveIntensity = 0.1
    }

    // Float animation
    meshRef.current.position.y = Math.sin(Date.now() / 1500 + id.charCodeAt(0)) * 0.08
  })

  return (
    <group position={position}>
      <mesh
        ref={meshRef}
        onClick={() => selectAgent(id)}
        onPointerOver={() => document.body.style.cursor = 'pointer'}
        onPointerOut={() => document.body.style.cursor = 'default'}
      >
        <icosahedronGeometry args={[radius, 1]} />
        <meshStandardMaterial
          color={STATUS_COLORS[status]}
          emissive={STATUS_COLORS[status]}
          emissiveIntensity={0.1}
          roughness={0.3}
          metalness={0.7}
          wireframe={false}
        />
      </mesh>

      {/* Outer halo when working */}
      {status === 'working' && (
        <mesh>
          <icosahedronGeometry args={[radius + 0.1, 1]} />
          <meshBasicMaterial color="#00f0ff" transparent opacity={0.15} wireframe />
        </mesh>
      )}

      <ProgressRing
        agent={agent}
        nodeRadius={radius}
        lastCheckpointIndex={lastCpIdx}
      />

      <Text
        position={[0, -(radius + 0.3), 0]}
        fontSize={0.18}
        color="#94a3b8"
        anchorX="center"
        anchorY="top"
      >
        {name}
      </Text>
      <Text
        position={[0, -(radius + 0.52), 0]}
        fontSize={0.12}
        color="#475569"
        anchorX="center"
        anchorY="top"
      >
        {role}
      </Text>
    </group>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add nexus-ui/src/components/AgentNode.tsx
git commit -m "feat: add AgentNode 3D icosahedron with status colors, halo, float animation"
```

---

## Task 7: NodeFlowPanel (Checkpoint Timeline)

**Files:**
- Create: `nexus-ui/src/components/NodeFlowPanel.tsx`

- [ ] **Step 1: Create nexus-ui/src/components/NodeFlowPanel.tsx**

```tsx
// nexus-ui/src/components/NodeFlowPanel.tsx
import { useEffect, useRef } from 'react'
import type { AgentState, Step, Checkpoint } from '../types'
import { TOOL_ICONS } from '../types'

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
    // Insert checkpoints that landed before or at this step
    while (cpIdx < checkpoints.length && checkpoints[cpIdx].step <= step.step) {
      items.push({ kind: 'checkpoint', data: checkpoints[cpIdx] })
      cpIdx++
    }
    items.push({ kind: 'step', data: step })
  }
  // Trailing checkpoints
  while (cpIdx < checkpoints.length) {
    items.push({ kind: 'checkpoint', data: checkpoints[cpIdx] })
    cpIdx++
  }
  return items
}

export function NodeFlowPanel({ agent }: NodeFlowPanelProps) {
  const { recentSteps, checkpoints } = agent
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [recentSteps.length, checkpoints.length])

  if (recentSteps.length === 0 && checkpoints.length === 0) return null

  const timeline = buildTimeline(recentSteps, checkpoints)

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        NODE FLOW
        <span style={styles.headerStats}>
          {recentSteps.length > 0 && `${agent.stepCount} steps`}
          {checkpoints.length > 0 && ` · ${checkpoints.length} ✓`}
        </span>
      </div>
      <div style={styles.list}>
        {timeline.map((item, i) =>
          item.kind === 'checkpoint' ? (
            <div key={`cp-${item.data.index}`} style={styles.checkpointRow}>
              <span style={styles.cpDiamond}>◆</span>
              <span style={styles.cpText}>
                <strong>Checkpoint {item.data.index}</strong> · step {item.data.step}
                <br />
                <span style={{ color: '#86efac' }}>{item.data.summary}</span>
              </span>
            </div>
          ) : (
            <div key={`step-${item.data.step}-${i}`} style={styles.stepRow}>
              <span style={styles.stepCircle}>○</span>
              <span style={styles.stepTool}>
                {TOOL_ICONS[item.data.tool] ?? '⚙'} {item.data.tool}
              </span>
              <span style={styles.stepLabel}>{item.data.label}</span>
            </div>
          )
        )}
        <div ref={bottomRef} />
      </div>
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
  headerStats: {
    color: '#94a3b8',
    fontWeight: 400,
  },
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
  stepCircle: {
    color: '#334155',
    minWidth: 10,
  },
  stepTool: {
    color: '#00f0ff',
    minWidth: 64,
    fontFamily: 'monospace',
  },
  stepLabel: {
    color: '#94a3b8',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: 220,
  },
  checkpointRow: {
    display: 'flex',
    gap: 8,
    alignItems: 'flex-start',
    padding: '4px 0',
    borderTop: '1px solid #1e293b',
  },
  cpDiamond: {
    color: '#22c55e',
    minWidth: 16,
    marginLeft: 2,
  },
  cpText: {
    color: '#94a3b8',
    fontSize: 11,
  },
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add nexus-ui/src/components/NodeFlowPanel.tsx
git commit -m "feat: add NodeFlowPanel checkpoint timeline component"
```

---

## Task 8: AgentDetailView (DOM Overlay)

**Files:**
- Create: `nexus-ui/src/components/AgentDetailView.tsx`

- [ ] **Step 1: Create nexus-ui/src/components/AgentDetailView.tsx**

```tsx
// nexus-ui/src/components/AgentDetailView.tsx
import { useEffect, useRef, useState, KeyboardEvent } from 'react'
import { useNexusStore, sendWsMessage } from '../store'
import { NodeFlowPanel } from './NodeFlowPanel'

export function AgentDetailView() {
  const selectedId = useNexusStore(s => s.selectedAgent)
  const selectAgent = useNexusStore(s => s.selectAgent)
  const agent = useNexusStore(s => selectedId ? s.agents[selectedId] : null)
  const [input, setInput] = useState('')
  const termRef = useRef<HTMLDivElement>(null)

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
    setInput('')
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleSend()
  }

  return (
    <div style={styles.overlay}>
      <div style={styles.panel}>
        {/* Header */}
        <div style={styles.header}>
          <button style={styles.backBtn} onClick={() => selectAgent(null)}>← Back</button>
          <span style={styles.agentTitle}>
            {agent.name.toUpperCase()} <span style={styles.roleBadge}>• {agent.role}</span>
          </span>
          <span style={styles.statusDot(agent.status)} />
        </div>

        <div style={styles.divider} />

        {/* Node flow panel */}
        <NodeFlowPanel agent={agent} />

        {/* Terminal log */}
        <div ref={termRef} style={styles.terminal}>
          {agent.recentOutput.length === 0 ? (
            <div style={styles.emptyLog}>No output yet…</div>
          ) : (
            agent.recentOutput.map((line, i) => (
              <div key={i} style={styles.logLine(line)}>{line}</div>
            ))
          )}
        </div>

        <div style={styles.divider} />

        {/* Chat input */}
        <div style={styles.inputRow}>
          <input
            style={styles.input}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
          />
          <button style={styles.sendBtn} onClick={handleSend}>Send</button>
        </div>
      </div>
    </div>
  )
}

const styles: Record<string, unknown> = {
  overlay: {
    position: 'fixed' as const,
    inset: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'rgba(5, 10, 20, 0.85)',
    backdropFilter: 'blur(4px)',
    zIndex: 100,
  } as React.CSSProperties,
  panel: {
    width: 540,
    maxHeight: '80vh',
    background: '#0d1117',
    border: '1px solid #1e293b',
    borderRadius: 12,
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
    padding: '16px 20px',
    gap: 0,
  } as React.CSSProperties,
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginBottom: 8,
  } as React.CSSProperties,
  backBtn: {
    background: 'none',
    border: '1px solid #334155',
    color: '#94a3b8',
    borderRadius: 6,
    padding: '4px 10px',
    cursor: 'pointer',
    fontSize: 12,
  } as React.CSSProperties,
  agentTitle: {
    flex: 1,
    color: '#e2e8f0',
    fontWeight: 700,
    fontSize: 14,
    letterSpacing: '0.08em',
  } as React.CSSProperties,
  roleBadge: {
    color: '#475569',
    fontWeight: 400,
  } as React.CSSProperties,
  statusDot: (status: string): React.CSSProperties => ({
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: status === 'working' ? '#00f0ff' : status === 'thinking' ? '#7c3aed' : status === 'done' ? '#22c55e' : '#334155',
  }),
  divider: {
    height: 1,
    background: '#1e293b',
    marginBottom: 10,
    marginTop: 4,
  } as React.CSSProperties,
  terminal: {
    flex: 1,
    overflowY: 'auto' as const,
    fontFamily: 'monospace',
    fontSize: 12,
    lineHeight: '1.6',
    minHeight: 120,
    maxHeight: 320,
    paddingBottom: 8,
  } as React.CSSProperties,
  emptyLog: {
    color: '#334155',
    fontStyle: 'italic',
    fontSize: 11,
  } as React.CSSProperties,
  logLine: (line: string): React.CSSProperties => ({
    color: (line.startsWith('Tool:') || line.startsWith('> Tool:')) ? '#00f0ff' : '#e2e8f0',
    whiteSpace: 'pre-wrap' as const,
    wordBreak: 'break-word' as const,
  }),
  inputRow: {
    display: 'flex',
    gap: 8,
    marginTop: 10,
  } as React.CSSProperties,
  input: {
    flex: 1,
    background: '#0f172a',
    border: '1px solid #334155',
    borderRadius: 6,
    color: '#e2e8f0',
    padding: '8px 12px',
    fontSize: 13,
    outline: 'none',
  } as React.CSSProperties,
  sendBtn: {
    background: '#00f0ff22',
    border: '1px solid #00f0ff66',
    color: '#00f0ff',
    borderRadius: 6,
    padding: '8px 16px',
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 600,
  } as React.CSSProperties,
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add nexus-ui/src/components/AgentDetailView.tsx
git commit -m "feat: add AgentDetailView DOM overlay with terminal log + NodeFlowPanel"
```

---

## Task 9: NexusScene (R3F Canvas Root)

**Files:**
- Create: `nexus-ui/src/components/NexusScene.tsx`
- Update: `nexus-ui/src/main.tsx`

- [ ] **Step 1: Create nexus-ui/src/components/NexusScene.tsx**

```tsx
// nexus-ui/src/components/NexusScene.tsx
import { Canvas } from '@react-three/fiber'
import { CameraControls } from '@react-three/drei'
import { Background } from './Background'
import { AgentNode } from './AgentNode'
import { NeuralEdge } from './NeuralEdge'
import { AgentDetailView } from './AgentDetailView'
import { useNexusStore } from '../store'
import { AGENT_POSITIONS } from '../types'

const WORKER_IDS = ['backend', 'frontend', 'qa', 'devops', 'browser'] as const

export function NexusScene() {
  const agents = useNexusStore(s => s.agents)
  const edges = useNexusStore(s => s.edges)
  const selectedAgent = useNexusStore(s => s.selectedAgent)
  const wsStatus = useNexusStore(s => s.wsStatus)
  const ceoPos = AGENT_POSITIONS['ceo'] ?? [0, 0.5, 4]

  return (
    <div style={{ width: '100vw', height: '100vh', position: 'relative' }}>
      {/* WS status badge */}
      <div style={{
        position: 'absolute', top: 16, right: 16, zIndex: 10,
        fontSize: 11, color: wsStatus === 'connected' ? '#22c55e' : '#ef4444',
        background: '#0d1117cc', borderRadius: 6, padding: '4px 10px',
        border: `1px solid ${wsStatus === 'connected' ? '#22c55e44' : '#ef444444'}`,
      }}>
        ● {wsStatus === 'connected' ? 'NEXUS ONLINE' : 'OFFLINE'}
      </div>

      <Canvas
        camera={{ position: [0, 2, 10], fov: 60 }}
        style={{ background: '#050a14' }}
        gl={{ antialias: true, alpha: false }}
      >
        <Background />
        <pointLight position={ceoPos} intensity={1.5} color="#00f0ff" />

        {/* CEO node */}
        {agents['ceo'] && (
          <AgentNode
            agent={agents['ceo']}
            position={AGENT_POSITIONS['ceo'] ?? [0, 0.5, 4]}
          />
        )}

        {/* Worker nodes + edges */}
        {WORKER_IDS.map(id => {
          const agent = agents[id]
          if (!agent) return null
          const pos = AGENT_POSITIONS[id] ?? [0, 0, 0]
          const edge = edges.find(e => e.to === id)
          return (
            <group key={id}>
              <NeuralEdge
                start={AGENT_POSITIONS['ceo'] ?? [0, 0.5, 4]}
                end={pos}
                isActive={edge?.isActive ?? false}
              />
              <AgentNode agent={agent} position={pos} />
            </group>
          )
        })}

        <CameraControls />
      </Canvas>

      {/* Detail overlay — rendered outside Canvas */}
      {selectedAgent && <AgentDetailView />}
    </div>
  )
}
```

- [ ] **Step 2: Update nexus-ui/src/main.tsx**

Replace the file contents:

```tsx
// nexus-ui/src/main.tsx
import { StrictMode, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { NexusScene } from './components/NexusScene'
import { connectWebSocket } from './store'

function App() {
  useEffect(() => {
    connectWebSocket()
  }, [])

  return <NexusScene />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
)
```

- [ ] **Step 3: Verify TypeScript compiles cleanly**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Run a full Vite build**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npm run build 2>&1 | tail -15
```

Expected: build success, `app/static/` updated. Bundle size logged.

- [ ] **Step 5: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add nexus-ui/src/components/NexusScene.tsx nexus-ui/src/main.tsx
git commit -m "feat: add NexusScene R3F Canvas root, wire all components"
```

---

## Task 10: FastAPI SPA Fallback + Serve Assets

**Files:**
- Modify: `app/api/router.py`

- [ ] **Step 1: Read app/api/router.py**

```bash
cat app/api/router.py
```

- [ ] **Step 2: Add SPA fallback route**

At the **end** of `app/api/router.py`, after all other routes, add:

```python
from fastapi.responses import FileResponse as _FileResponse
from pathlib import Path as _Path

_STATIC_DIR = _Path(__file__).parent.parent / "static"

@router.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """Catch-all: serve index.html for any unmatched GET (SPA client-side routing)."""
    index = _STATIC_DIR / "index.html"
    if index.exists():
        return _FileResponse(str(index))
    return _FileResponse(str(_Path(__file__).parent.parent / "static" / "index.html"))
```

- [ ] **Step 3: Verify FastAPI starts without error**

```bash
docker exec nexus-ceo python -c "from app.api.router import router; print('router OK, routes:', len(router.routes))"
```

Expected: prints route count.

- [ ] **Step 4: Build and serve**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npm run build && echo "Build OK"
docker restart nexus-ceo
sleep 5
curl -s 127.0.0.1:3030/ | head -5
```

Expected: HTML response with `<title>NEXUS Command Center</title>`.

- [ ] **Step 5: Commit**

```bash
cd /home/subaru/projects/virtual-company
git add app/api/router.py
git commit -m "feat: add SPA fallback route to serve nexus-ui from FastAPI"
```

---

## Task 11: Build Script + Dev Workflow Docs

**Files:**
- Create: `nexus-ui/README.md` — only if user requests it

This task adds a build alias to `docker-compose.yml` (optional) and verifies the full end-to-end UI workflow.

- [ ] **Step 1: Verify full build pipeline**

```bash
cd /home/subaru/projects/virtual-company/nexus-ui && npm run build 2>&1 | tail -5
```

Expected: success with bundle size < 600KB gzipped.

- [ ] **Step 2: Check static dir is populated**

```bash
ls -lh app/static/
ls -lh app/static/assets/
```

Expected: `index.html` + one `.js` file + one `.css` file.

- [ ] **Step 3: End-to-end smoke test**

```bash
curl -s 127.0.0.1:3030/ | grep -c "NEXUS Command Center"
```

Expected: `1` — the SPA HTML is served.

```bash
curl -s 127.0.0.1:3030/assets/ 2>&1 | head -3
```

Expected: returns content (not 404).

- [ ] **Step 4: Verify WebSocket connects (manual)**

Open a browser at `http://<server-ip>:3030/` and confirm:
- 3D scene renders with 6 nodes
- Status badge shows `● NEXUS ONLINE`
- Clicking a node opens AgentDetailView
- Clicking ← Back returns to the 3D map

- [ ] **Step 5: Final commit**

```bash
cd /home/subaru/projects/virtual-company
git add nexus-ui/
git commit -m "feat: complete NEXUS 3D neural dashboard UI build"
```

---

## Post-Build Checklist

- [ ] 6 agent nodes render in 3D space at correct positions
- [ ] CEO node is larger (radius 0.9) than workers (radius 0.6)
- [ ] Neural edges visible between CEO and each worker; particles animate when active
- [ ] Clicking a worker opens AgentDetailView with that agent's name
- [ ] Back button returns to 3D map
- [ ] Sending a task from the CEO detail view sends WebSocket message
- [ ] ProgressRing appears on an agent when `worker_step` events arrive
- [ ] NodeFlowPanel shows steps and checkpoints after a task runs
- [ ] WS disconnect shows `● OFFLINE` badge; reconnects automatically
