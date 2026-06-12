# Jarvis 3D Immersion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the NEXUS dashboard from "3D scene with panels" into a Jarvis-style immersive command center: cinematic camera, boot sequence, reactor data ring, in-scene holograms fed by live events, and a film-grain HUD finish.

**Architecture:** Pure client-side additions to `nexus-ui` (rendered in the viewer's browser — zero server load on the 8 GB box). New components mount inside the existing R3F `<Canvas>` or the DOM HUD layer. Dynamic roster layout replaces the hardcoded 5-worker constants so hired agents materialize in the scene.

**Tech Stack:** react-three-fiber, @react-three/drei (`CameraControls`, `Billboard`, `Text`, `AdaptiveDpr` — already installed), @react-three/postprocessing (already installed). **No new dependencies.**

**Prerequisite:** Plan A (`2026-06-12-pipeline-repairs-and-ui-connectivity.md`) — the holo browser screen and edge labels consume `browserView` and `workQueue` store state wired there.

**Performance budget (hard rules for this plan):** `dpr` capped at 1.5, `AdaptiveDpr` active, no shadows, no SSAO, instanced meshes for any repeated geometry, total new particles ≤ 200, textures disposed on replacement. Verification in the final task includes a devtools FPS check.

**Project root:** `/mnt/HC_Volume_105874680/virtual-company`.

---

### Task 1: Performance guard rails

**Files:**
- Modify: `nexus-ui/src/components/NexusScene.tsx:82-86` (Canvas props)

- [ ] **Step 1: Cap device pixel ratio and enable adaptive degradation**

```tsx
import { CameraControls, AdaptiveDpr } from '@react-three/drei'
```

```tsx
      <Canvas
        camera={{ position: [0, 2, 10], fov: 60 }}
        style={{ background: '#020408' }}
        dpr={[1, 1.5]}
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
      >
        <AdaptiveDpr pixelated />
```

- [ ] **Step 2: Typecheck**

Run: `cd nexus-ui && npx tsc --noEmit` — expected: clean.

- [ ] **Step 3: Commit**

```bash
git add nexus-ui/src/components/NexusScene.tsx
git commit -m "perf(ui): dpr cap + AdaptiveDpr guard rails"
```

---

### Task 2: Dynamic orbital roster — N workers in an arc, custom agents included

**Files:**
- Modify: `nexus-ui/src/types.ts`, `nexus-ui/src/store.ts`, `nexus-ui/src/components/NexusScene.tsx`
- Modify (color lookups): `nexus-ui/src/components/AgentNode.tsx`, `NeuralEdge.tsx`, `HoverCard.tsx`, `AgentDetailView.tsx`

Today `WORKER_IDS`/`AGENT_POSITIONS` hardcode 5 workers; hired agents can never render.

- [ ] **Step 1: Add layout + color helpers in `types.ts`**

Keep the existing `AGENT_POSITIONS` and `AGENT_COLORS` exports (other code references them), and add:

```typescript
export const CEO_POSITION: [number, number, number] = [0, 0.5, 4]

/** Place worker `index` of `total` on a 200° arc behind the CEO, radius 5.5. */
export function workerPosition(index: number, total: number): [number, number, number] {
  const arc = (200 * Math.PI) / 180
  const start = Math.PI / 2 + arc / 2
  const angle = total <= 1 ? Math.PI / 2 : start - (arc * index) / (total - 1)
  const r = 5.5
  return [Math.cos(angle) * r, 0, CEO_POSITION[2] - Math.sin(angle) * r]
}

const FALLBACK_PALETTE = ['#22d3ee', '#a3e635', '#fb7185', '#fbbf24', '#34d399', '#818cf8']

/** Identity color for any agent id — known agents keep their color, custom ids hash into a palette. */
export function agentColor(id: string): string {
  if (AGENT_COLORS[id]) return AGENT_COLORS[id]
  let h = 0
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return FALLBACK_PALETTE[h % FALLBACK_PALETTE.length]
}
```

- [ ] **Step 2: Make edges dynamic on `init`**

In `store.ts` `case 'init'`, after hydrating agents, rebuild edges from the live roster instead of only resetting `isActive`:

```typescript
        case 'init': {
          const list = (event.agents as Array<{ id: string; name: string; role: string }>) ?? []
          list.forEach(a => {
            agents[a.id] = { ...defaultAgent(a.id, a.name, a.role), ...agents[a.id] }
          })
          const workerIds = list.map(a => a.id).filter(id => id !== 'ceo')
          const rebuilt = (workerIds.length ? workerIds : WORKER_IDS).map(id => ({
            from: 'ceo' as const, to: id, isActive: false,
          }))
          return { agents, edges: rebuilt, notifications }
        }
```

- [ ] **Step 3: Render the roster dynamically in `NexusScene.tsx`**

Replace the hardcoded `WORKER_IDS.map(...)` block:

```tsx
      {(() => {
        const workerIds = Object.keys(agents).filter(id => id !== 'ceo')
        return workerIds.map((id, i) => {
          const agent = agents[id]
          const pos = AGENT_POSITIONS[id] ?? workerPosition(i, workerIds.length)
          const edge = edges.find(e => e.to === id)
          const dimmed = !!selectedAgent && selectedAgent !== id
          return (
            <group key={id}>
              <NeuralEdge start={ceoPos} end={pos} isActive={edge?.isActive ?? false} workerId={id} />
              <AgentNode agent={agent} position={pos} dimmed={dimmed}
                         onHoverEnter={handleHoverEnter} onHoverLeave={handleHoverLeave} />
            </group>
          )
        })
      })()}
```

Import `workerPosition` from `../types`. Known agents keep their spec positions (`AGENT_POSITIONS[id] ??` fallback), so the existing scene is unchanged until a 6th agent is hired.

- [ ] **Step 4: Switch color lookups to `agentColor()`**

In `AgentNode.tsx`, `NeuralEdge.tsx`, `HoverCard.tsx`, `AgentDetailView.tsx`: replace every `AGENT_COLORS[id] ?? <fallback>` / direct `AGENT_COLORS[...]` read with `agentColor(id)` (import from `../types`). Grep to find them all:

```bash
grep -rn "AGENT_COLORS" nexus-ui/src/components nexus-ui/src/hooks
```

- [ ] **Step 5: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src
git commit -m "feat(ui): dynamic orbital roster — hired agents render in the 3D scene"
```

---

### Task 3: Camera director — fly-to on select, idle auto-orbit

**Files:**
- Create: `nexus-ui/src/components/CameraDirector.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

The single biggest "feels basic" fix: the camera must move with intent.

- [ ] **Step 1: Create the component**

```tsx
// nexus-ui/src/components/CameraDirector.tsx
import { useEffect, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import type { CameraControls } from '@react-three/drei'
import { useNexusStore } from '../store'

const HOME = { pos: [0, 2, 10] as const, target: [0, 0.5, 0] as const }

interface Props {
  controlsRef: React.RefObject<CameraControls | null>
  positionFor: (id: string) => [number, number, number]
}

export function CameraDirector({ controlsRef, positionFor }: Props) {
  const selectedAgent = useNexusStore(s => s.selectedAgent)
  const agents = useNexusStore(s => s.agents)
  const lastInteraction = useRef(Date.now())

  // Any user interaction pauses the idle orbit for 8s
  useEffect(() => {
    const bump = () => { lastInteraction.current = Date.now() }
    window.addEventListener('pointerdown', bump)
    window.addEventListener('wheel', bump)
    return () => {
      window.removeEventListener('pointerdown', bump)
      window.removeEventListener('wheel', bump)
    }
  }, [])

  // Fly to the selected agent; return home on deselect
  useEffect(() => {
    const controls = controlsRef.current
    if (!controls) return
    if (selectedAgent && selectedAgent !== 'ceo') {
      const [x, y, z] = positionFor(selectedAgent)
      // Camera slides 35% toward the agent, slightly above, looking at it
      controls.setLookAt(x * 0.35, y + 1.6, z + 4.2, x, y + 0.2, z, true)
    } else if (selectedAgent === 'ceo') {
      controls.setLookAt(0, 1.4, 7.5, 0, 0.5, 4, true)
    } else {
      controls.setLookAt(...HOME.pos, ...HOME.target, true)
    }
  }, [selectedAgent, controlsRef, positionFor])

  // Slow idle orbit when nothing selected, nobody working, no recent input
  useFrame((_, delta) => {
    const controls = controlsRef.current
    if (!controls || selectedAgent) return
    const anyBusy = Object.values(agents).some(a => a.status === 'working' || a.status === 'thinking')
    if (anyBusy) return
    if (Date.now() - lastInteraction.current < 8000) return
    controls.azimuthAngle += delta * 0.025
  })

  return null
}
```

- [ ] **Step 2: Wire into `NexusScene.tsx`**

```tsx
import { useRef } from 'react'
import type { CameraControls as CameraControlsImpl } from '@react-three/drei'
```

In the component body:

```tsx
  const controlsRef = useRef<CameraControlsImpl>(null)
  const workerIds = Object.keys(agents).filter(id => id !== 'ceo')
  const positionFor = useCallback((id: string): [number, number, number] =>
    AGENT_POSITIONS[id] ?? workerPosition(workerIds.indexOf(id), workerIds.length),
  [workerIds.join(',')])
```

Inside the Canvas replace `<CameraControls />` with:

```tsx
        <CameraControls ref={controlsRef} makeDefault smoothTime={0.45} />
        <CameraDirector controlsRef={controlsRef} positionFor={positionFor} />
```

(Reuse `positionFor` for the roster render from Task 2 to avoid duplicated layout math.)

- [ ] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/CameraDirector.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): cinematic camera — fly-to on select, idle auto-orbit"
```

---

### Task 4: Boot sequence + offline banner

**Files:**
- Create: `nexus-ui/src/components/BootOverlay.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

- [ ] **Step 1: Create the component**

```tsx
// nexus-ui/src/components/BootOverlay.tsx
import { useEffect, useState } from 'react'
import { useNexusStore } from '../store'

const LINES = [
  'NEXUS NEURAL COMMAND CENTER v2',
  'INITIALIZING ARC REACTOR .......... OK',
  'LOADING AGENT ROSTER .............. OK',
  'ESTABLISHING UPLINK ...............',
]

export function BootOverlay() {
  const wsStatus = useNexusStore(s => s.wsStatus)
  const [shown, setShown] = useState(() => sessionStorage.getItem('nexus-booted') !== '1')
  const [lineCount, setLineCount] = useState(0)
  const [fading, setFading] = useState(false)

  // Typewriter: reveal one line every 350ms
  useEffect(() => {
    if (!shown || lineCount >= LINES.length) return
    const t = setTimeout(() => setLineCount(c => c + 1), 350)
    return () => clearTimeout(t)
  }, [shown, lineCount])

  // When all lines shown AND ws connected → flash final line, fade out
  useEffect(() => {
    if (!shown || fading) return
    if (lineCount >= LINES.length && wsStatus === 'connected') {
      setFading(true)
      sessionStorage.setItem('nexus-booted', '1')
      setTimeout(() => setShown(false), 900)
    }
  }, [shown, fading, lineCount, wsStatus])

  return (
    <>
      {shown && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 300,
          background: '#020408',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          opacity: fading ? 0 : 1,
          transition: 'opacity 800ms ease',
          pointerEvents: fading ? 'none' : 'auto',
        }}>
          <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 13, color: '#00f0ff', lineHeight: 2 }}>
            {LINES.slice(0, lineCount).map((l, i) => <div key={i}>{l}</div>)}
            {lineCount >= LINES.length && wsStatus === 'connected' && (
              <div style={{ color: '#f59e0b', fontFamily: 'Orbitron, sans-serif', marginTop: 8, letterSpacing: '0.2em' }}>
                ALL SYSTEMS NOMINAL
              </div>
            )}
          </div>
        </div>
      )}

      {/* Offline banner — visible whenever WS drops after boot */}
      {!shown && wsStatus === 'offline' && (
        <div style={{
          position: 'fixed', top: 16, left: '50%', transform: 'translateX(-50%)',
          zIndex: 250, padding: '5px 16px',
          background: 'rgba(40, 8, 8, 0.9)', border: '1px solid #ef4444',
          borderRadius: 6, color: '#ef4444',
          fontFamily: 'Orbitron, sans-serif', fontSize: 10, letterSpacing: '0.15em',
          animation: 'nexus-blink 1.2s ease-in-out infinite',
        }}>
          UPLINK LOST — RECONNECTING
          <style>{'@keyframes nexus-blink { 50% { opacity: 0.4 } }'}</style>
        </div>
      )}
    </>
  )
}
```

- [ ] **Step 2: Mount as the last child in `NexusScene.tsx`'s root div:** `<BootOverlay />`.

- [ ] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/BootOverlay.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): boot sequence + uplink-lost banner"
```

---

### Task 5: Reactor data ring — orbiting activity bars + clock

**Files:**
- Create: `nexus-ui/src/components/ReactorRing.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

A rotating instanced ring of 48 bars around the CEO whose heights respond to live agent activity — the Jarvis "data orbiting the core" look. One instanced mesh = one draw call.

- [ ] **Step 1: Create the component**

```tsx
// nexus-ui/src/components/ReactorRing.tsx
import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Text } from '@react-three/drei'
import * as THREE from 'three'
import { useNexusStore } from '../store'

const BAR_COUNT = 48
const RADIUS = 1.7
const CEO_POS: [number, number, number] = [0, 0.5, 4]

export function ReactorRing() {
  const meshRef = useRef<THREE.InstancedMesh>(null!)
  const groupRef = useRef<THREE.Group>(null!)
  const agents = useNexusStore(s => s.agents)

  const busyCount = Object.values(agents)
    .filter(a => a.status === 'working' || a.status === 'thinking').length

  const dummy = useMemo(() => new THREE.Object3D(), [])
  const phases = useMemo(
    () => Array.from({ length: BAR_COUNT }, () => Math.random() * Math.PI * 2), [])

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime
    if (groupRef.current) groupRef.current.rotation.y += delta * (0.15 + busyCount * 0.12)
    if (!meshRef.current) return
    for (let i = 0; i < BAR_COUNT; i++) {
      const angle = (i / BAR_COUNT) * Math.PI * 2
      const activity = 0.06 + Math.abs(Math.sin(t * (1 + busyCount) + phases[i])) * (0.08 + busyCount * 0.1)
      dummy.position.set(Math.cos(angle) * RADIUS, 0, Math.sin(angle) * RADIUS)
      dummy.scale.set(1, activity / 0.06, 1)
      dummy.rotation.set(0, -angle, 0)
      dummy.updateMatrix()
      meshRef.current.setMatrixAt(i, dummy.matrix)
    }
    meshRef.current.instanceMatrix.needsUpdate = true
  })

  const clock = new Date().toTimeString().slice(0, 5)

  return (
    <group position={CEO_POS}>
      <group ref={groupRef}>
        <instancedMesh ref={meshRef} args={[undefined, undefined, BAR_COUNT]}>
          <boxGeometry args={[0.015, 0.06, 0.015]} />
          <meshStandardMaterial color="#00f0ff" emissive="#00f0ff" emissiveIntensity={1.6}
                                transparent opacity={0.85} />
        </instancedMesh>
      </group>
      <Text position={[0, 1.55, 0]} fontSize={0.11} color="#00f0ff"
            anchorX="center" anchorY="middle" letterSpacing={0.25}>
        {`${clock}  ·  ${busyCount} ACTIVE`}
      </Text>
    </group>
  )
}
```

(The clock string re-renders whenever store state changes — minute-accurate is fine; no timer needed.)

- [ ] **Step 2: Mount inside the Canvas in `NexusScene.tsx`**, after `<CeoNode ... />`: `<ReactorRing />`.

- [ ] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/ReactorRing.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): reactor data ring — instanced activity bars + clock"
```

---

### Task 6: Edge task labels — what is flowing, not just that it flows

**Files:**
- Create: `nexus-ui/src/components/EdgeTaskLabel.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

- [ ] **Step 1: Create the component**

```tsx
// nexus-ui/src/components/EdgeTaskLabel.tsx
import { Billboard, Text } from '@react-three/drei'
import { useNexusStore } from '../store'
import { agentColor } from '../types'

interface Props {
  workerId: string
  start: [number, number, number]
  end: [number, number, number]
}

export function EdgeTaskLabel({ workerId, start, end }: Props) {
  const item = useNexusStore(s =>
    s.workQueue.find(q => q.agent === workerId && q.status === 'active'))
  if (!item) return null

  const mid: [number, number, number] = [
    (start[0] + end[0]) / 2,
    (start[1] + end[1]) / 2 + 0.45,
    (start[2] + end[2]) / 2,
  ]

  return (
    <Billboard position={mid}>
      <Text fontSize={0.085} color={agentColor(workerId)} anchorX="center"
            maxWidth={2.4} textAlign="center" outlineWidth={0.004} outlineColor="#020408">
        {item.task.length > 60 ? item.task.slice(0, 60) + '…' : item.task}
      </Text>
    </Billboard>
  )
}
```

- [ ] **Step 2: Mount per worker** in `NexusScene.tsx`'s roster loop, inside the `<group key={id}>` next to `<NeuralEdge ...>`:

```tsx
              <EdgeTaskLabel workerId={id} start={ceoPos} end={pos} />
```

- [ ] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/EdgeTaskLabel.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): floating task labels on active delegation edges"
```

---

### Task 7: Holo browser screen — Maya's live frames as a 3D hologram

**Files:**
- Create: `nexus-ui/src/components/HoloBrowser.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

The signature Jarvis feature: the live CDP screencast (already in `browserView` from Plan A) becomes a glowing screen floating above Maya in the scene. The DOM `BrowserViewport` panel remains for close inspection; this is the ambient version.

- [ ] **Step 1: Create the component**

```tsx
// nexus-ui/src/components/HoloBrowser.tsx
import { useEffect, useMemo, useRef, useState } from 'react'
import { Billboard, Text } from '@react-three/drei'
import * as THREE from 'three'
import { useNexusStore } from '../store'

const VIOLET = '#8b5cf6'
const FRESH_MS = 90_000   // hide hologram 90s after the last frame

interface Props {
  position: [number, number, number]   // Maya's node position
}

export function HoloBrowser({ position }: Props) {
  const view = useNexusStore(s => s.browserView)
  const [, forceTick] = useState(0)
  const texRef = useRef<THREE.Texture | null>(null)

  // Build a texture from the latest frame; dispose the previous one
  const texture = useMemo(() => {
    if (!view) return null
    const img = new Image()
    const tex = new THREE.Texture(img)
    tex.colorSpace = THREE.SRGBColorSpace
    img.onload = () => { tex.needsUpdate = true }
    img.src = `data:${view.mime};base64,${view.image}`
    return tex
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view?.ts])

  useEffect(() => {
    const prev = texRef.current
    texRef.current = texture
    return () => { prev?.dispose() }
  }, [texture])

  // Re-evaluate freshness once after the window passes
  useEffect(() => {
    if (!view) return
    const id = setTimeout(() => forceTick(n => n + 1), FRESH_MS + 1000)
    return () => clearTimeout(id)
  }, [view?.ts])

  if (!view || !texture) return null
  if (Date.now() - view.ts > FRESH_MS) return null

  const holoPos: [number, number, number] = [position[0], position[1] + 2.1, position[2]]

  return (
    <Billboard position={holoPos}>
      {/* Glow frame */}
      <mesh position={[0, 0, -0.01]}>
        <planeGeometry args={[2.56, 1.66]} />
        <meshBasicMaterial color={VIOLET} transparent opacity={0.25} />
      </mesh>
      {/* The live screen */}
      <mesh>
        <planeGeometry args={[2.4, 1.5]} />
        <meshBasicMaterial map={texture} transparent opacity={0.92} toneMapped={false} />
      </mesh>
      <Text position={[0, -0.92, 0]} fontSize={0.08} color={VIOLET} anchorX="center"
            maxWidth={2.4} outlineWidth={0.004} outlineColor="#020408">
        {(view.caption ? `${view.caption} · ` : '') + view.url.slice(0, 70)}
      </Text>
    </Billboard>
  )
}
```

- [ ] **Step 2: Mount above Maya** in `NexusScene.tsx`'s roster loop, inside `<group key={id}>`:

```tsx
              {id === 'browser' && <HoloBrowser position={pos} />}
```

- [ ] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/HoloBrowser.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): holographic live browser screen above Maya"
```

---

### Task 8: Film finish — scanlines + noise + HUD corner frame

**Files:**
- Modify: `nexus-ui/src/components/PostProcessing.tsx`
- Create: `nexus-ui/src/components/HudFrame.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

- [ ] **Step 1: Add Scanline + Noise effects**

In `PostProcessing.tsx`, extend the composer (both effects ship with `@react-three/postprocessing` — no new deps):

```tsx
import { EffectComposer, Bloom, ChromaticAberration, Vignette, Noise, Scanline } from '@react-three/postprocessing'
import { BlendFunction } from 'postprocessing'
```

Inside the existing `<EffectComposer>`, after `<Vignette ...>`:

```tsx
      <Scanline blendFunction={BlendFunction.OVERLAY} density={1.1} opacity={0.045} />
      <Noise premultiply opacity={0.05} />
```

- [ ] **Step 2: Create the HUD frame**

```tsx
// nexus-ui/src/components/HudFrame.tsx
const CYAN = 'rgba(0, 240, 255, 0.35)'

function Corner({ style }: { style: React.CSSProperties }) {
  return <div style={{
    position: 'fixed', width: 26, height: 26, zIndex: 30, pointerEvents: 'none', ...style,
  }} />
}

export function HudFrame() {
  const b = `2px solid ${CYAN}`
  return (
    <>
      <Corner style={{ top: 10, left: 10, borderTop: b, borderLeft: b }} />
      <Corner style={{ top: 10, right: 10, borderTop: b, borderRight: b }} />
      <Corner style={{ bottom: 10, left: 10, borderBottom: b, borderLeft: b }} />
      <Corner style={{ bottom: 10, right: 10, borderBottom: b, borderRight: b }} />
      <div style={{
        position: 'fixed', top: 14, left: '50%', transform: 'translateX(-50%)',
        zIndex: 30, pointerEvents: 'none',
        fontFamily: 'Orbitron, sans-serif', fontSize: 10, letterSpacing: '0.45em',
        color: 'rgba(0, 240, 255, 0.55)',
      }}>
        N E X U S
      </div>
    </>
  )
}
```

- [ ] **Step 3: Mount `<HudFrame />`** in `NexusScene.tsx`'s HUD layer.

- [ ] **Step 4: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/PostProcessing.tsx nexus-ui/src/components/HudFrame.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): scanline+noise film finish and HUD corner frame"
```

---

### Task 9 (optional): UI sound blips via WebAudio — no assets, off by default

**Files:**
- Create: `nexus-ui/src/hooks/useSfx.ts`
- Modify: `nexus-ui/src/components/NexusScene.tsx`, `nexus-ui/src/hooks/useCommandPalette.ts`

- [ ] **Step 1: Create the hook**

```typescript
// nexus-ui/src/hooks/useSfx.ts
import { useEffect } from 'react'
import { useNexusStore } from '../store'

const SFX_KEY = 'nexus-sfx-enabled'
let _ctx: AudioContext | null = null

function blip(freq: number, duration = 0.09, gain = 0.04) {
  try {
    if (localStorage.getItem(SFX_KEY) !== 'true') return
    _ctx = _ctx ?? new AudioContext()
    const osc = _ctx.createOscillator()
    const g = _ctx.createGain()
    osc.type = 'sine'
    osc.frequency.value = freq
    g.gain.setValueAtTime(gain, _ctx.currentTime)
    g.gain.exponentialRampToValueAtTime(0.0001, _ctx.currentTime + duration)
    osc.connect(g).connect(_ctx.destination)
    osc.start()
    osc.stop(_ctx.currentTime + duration)
  } catch { /* audio blocked — ignore */ }
}

export function toggleSfx(): boolean {
  const next = localStorage.getItem(SFX_KEY) !== 'true'
  localStorage.setItem(SFX_KEY, String(next))
  return next
}

/** Subscribes to store transitions and plays matching blips. */
export function useSfx() {
  useEffect(() => useNexusStore.subscribe((state, prev) => {
    for (const id of Object.keys(state.agents)) {
      const cur = state.agents[id]?.status
      const old = prev.agents[id]?.status
      if (cur === old) continue
      if (cur === 'working') blip(520)
      else if (cur === 'done') blip(880, 0.14)
      else if (cur === 'thinking') blip(330)
    }
  }), [])
}
```

- [ ] **Step 2: Wire it** — call `useSfx()` at the top of `NexusScene`, and add a palette action in `useCommandPalette.ts`'s `ACTIONS` array:

```typescript
  { id: 'sfx-toggle', label: 'Toggle UI sounds', group: 'SYSTEM', action: () => { toggleSfx() } },
```

(import `toggleSfx` from `./useSfx`).

- [ ] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/hooks/useSfx.ts nexus-ui/src/components/NexusScene.tsx nexus-ui/src/hooks/useCommandPalette.ts
git commit -m "feat(ui): optional WebAudio status blips (off by default)"
```

---

### Task 10: Build, deploy, verify — visuals and frame rate

**Files:** none

- [ ] **Step 1: Production build**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npm run build
```

Expected: success; bundle delta should be small (no new deps).

- [ ] **Step 2: Deploy**

```bash
cd /mnt/HC_Volume_105874680/virtual-company && docker compose up -d --build
docker ps --format "{{.Names}} {{.Status}}" | grep virtual-company
curl -s -m 5 http://127.0.0.1:3031/ | grep -o 'index-[A-Za-z0-9]*\.js'
```

Expected: container Up; the served bundle hash changed from `index-CqjvjNr9.js`.

- [ ] **Step 3: Visual verification checklist (in the browser)**

1. Hard-reload → boot sequence types 4 lines → "ALL SYSTEMS NOMINAL" → fades to scene.
2. Camera slowly orbits when idle; click Reinhard → camera glides toward him, panel opens; Back → camera returns home.
3. Cyan data ring rotates around the arc reactor with the clock readout.
4. Send a CEO task → edge labels show the actual task text; ring spins faster while agents work.
5. Give Maya a browse task → hologram screen appears above her with live frames; it fades 90s after the last frame.
6. Scanlines/grain visible on dark areas; corner brackets + "N E X U S" title present.
7. Kill the WS (`docker restart virtual-company`) → "UPLINK LOST" banner blinks, then reconnects.

- [ ] **Step 4: Frame-rate check** — devtools → Performance → record 10s idle and 10s with a running task. Expected ≥ 45 fps on an integrated GPU at 1080p. If below: reduce `Background.tsx` particle counts (200/200/100 → 120/120/60) and `ReactorRing` `BAR_COUNT` 48 → 32.

- [ ] **Step 5: Commit final build**

```bash
git add -A && git commit -m "build: jarvis 3d immersion production build"
```
