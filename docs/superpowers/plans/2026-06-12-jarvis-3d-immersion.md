# Jarvis 3D Immersion & Visual Overhaul Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Transform the NEXUS dashboard into a Jarvis-style command center — premium materials (glass nodes, energy-tube edges, reworked reactor core), crisp CSS typography, cinematic camera + boot sequence, in-scene holograms, and a global "Ask Subaru anything…" command bar as the master control console.

**Architecture:** Pure client-side additions to `nexus-ui` (rendered in the viewer's browser — zero server load on the 8 GB box). v2 adds a material/geometry overhaul (Tasks 3–7) ahead of the immersion work, because the gap-analysis feedback identified low-poly geometry, flat shading, thin lines, and in-scene 3D text as the reasons the scene reads "basic" — bloom already exists (`PostProcessing.tsx`: intensity 1.2, threshold 0.4) but node emissives (0.08) sit below the threshold, so nothing glows. All text moves to drei `<Html>` (CSS) overlays.

**Tech Stack:** react-three-fiber, @react-three/drei (`CameraControls`, `Html`, `Environment`, `Lightformer`, `AdaptiveDpr` — already installed), @react-three/postprocessing (already installed). **No new dependencies.** No network-loaded assets: the environment map is generated procedurally with `<Lightformer>` children.

**Prerequisite:** Plan A (`2026-06-12-pipeline-repairs-and-ui-connectivity.md`) — DONE. The holo browser screen and edge labels consume `browserView` and `workQueue` store state wired there.

**Performance budget (hard rules):** `dpr` capped at 1.5, `AdaptiveDpr` active, no shadows, no SSAO, **no `transmission` on materials** (it re-renders the scene to a texture every frame — glass is faked with env-map reflections + a fresnel rim shader), instanced meshes for repeated geometry, ≤ 3 pulse groups per active edge, `Environment resolution={64}`, textures/geometries disposed on replacement.

**Deferred to a future Plan C (need backend work, intentionally out of scope here):** per-task token/cost telemetry, memory inspector UI, worker→worker handoff edges, drag-to-assign, nightly Maya self-test routine, fixing the 4 pre-existing test failures in `tests/test_browser_playwright.py` + `tests/test_executor_gemini.py`.

**Project root:** `/mnt/HC_Volume_105874680/virtual-company`. Verification command for every UI task: `cd nexus-ui && npx tsc --noEmit` (expected: clean). nexus-ui has no unit-test runner; the final task is the integration verification.

---

### Task 1: Performance guard rails

**Files:**
- Modify: `nexus-ui/src/components/NexusScene.tsx` (Canvas props)

- [x] **Step 1: Cap device pixel ratio and enable adaptive degradation**

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

- [x] **Step 2: Typecheck**

Run: `cd nexus-ui && npx tsc --noEmit` — expected: clean.

- [x] **Step 3: Commit**

```bash
git add nexus-ui/src/components/NexusScene.tsx
git commit -m "perf(ui): dpr cap + AdaptiveDpr guard rails"
```

---

### Task 2: Dynamic orbital roster — N workers in an arc, custom agents included

**Files:**
- Modify: `nexus-ui/src/types.ts`, `nexus-ui/src/store.ts`, `nexus-ui/src/components/NexusScene.tsx`
- Modify (color lookups): `nexus-ui/src/components/HoverCard.tsx`, `nexus-ui/src/components/AgentDetailView.tsx`

Today `WORKER_IDS`/`AGENT_POSITIONS` hardcode 5 workers; hired agents can never render. This task also introduces `agentColor()`, which every later task uses.

- [x] **Step 1: Add layout + color helpers in `types.ts`**

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

- [x] **Step 2: Make edges dynamic on `init`**

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

- [x] **Step 3: Render the roster dynamically in `NexusScene.tsx`**

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

- [x] **Step 4: Switch color lookups to `agentColor()` in HoverCard + AgentDetailView**

In `HoverCard.tsx` and `AgentDetailView.tsx`, replace `AGENT_COLORS[id] ?? <fallback>` reads with `agentColor(id)` (import from `../types`). `AgentNode.tsx` and `NeuralEdge.tsx` are fully rewritten in Tasks 3 and 5 and adopt it there. Find them all:

```bash
grep -rn "AGENT_COLORS" nexus-ui/src/components nexus-ui/src/hooks
```

- [x] **Step 5: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src
git commit -m "feat(ui): dynamic orbital roster — hired agents render in the 3D scene"
```

---

### Task 3: Glass worker nodes — smooth spheres, fresnel rim, inner energy core, CSS labels

**Files:**
- Create: `nexus-ui/src/components/NodeLabel.tsx`
- Rewrite: `nexus-ui/src/components/AgentNode.tsx`

Fixes feedback items 1, 2 and 4 for workers: the faceted `icosahedronGeometry(r, 1)` opaque ball becomes a smooth tinted-glass sphere (`MeshPhysicalMaterial`, env reflections from Task 7) with a razor-thin additive fresnel rim, a glowing inner core, and labels rendered as crisp CSS via drei `<Html>` instead of in-scene 3D text. Emissive intensities are raised past the bloom threshold so active nodes actually glow.

- [x] **Step 1: Create the shared CSS label component**

```tsx
// nexus-ui/src/components/NodeLabel.tsx
import { Html } from '@react-three/drei'

interface Props {
  position: [number, number, number]
  name: string
  role: string
  color: string
  dimmed?: boolean
}

/** Crisp CSS typography anchored to a 3D position — replaces in-scene drei <Text>. */
export function NodeLabel({ position, name, role, color, dimmed }: Props) {
  return (
    <Html position={position} center distanceFactor={8} zIndexRange={[20, 0]}
          style={{ pointerEvents: 'none', userSelect: 'none' }}>
      <div style={{ textAlign: 'center', whiteSpace: 'nowrap',
                    opacity: dimmed ? 0.25 : 1, transition: 'opacity 200ms' }}>
        <div style={{
          fontFamily: 'Orbitron, sans-serif', fontSize: 13, fontWeight: 700,
          letterSpacing: '0.18em', color,
          textShadow: `0 0 10px ${color}aa, 0 0 2px #000`,
        }}>
          {name.toUpperCase()}
        </div>
        <div style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 9,
          color: '#94a3b8', letterSpacing: '0.08em', marginTop: 2,
        }}>
          {role}
        </div>
      </div>
    </Html>
  )
}
```

`zIndexRange={[20, 0]}` keeps labels under the DOM HUD (which starts at zIndex 30+).

- [x] **Step 2: Rewrite `AgentNode.tsx`**

Full replacement (keeps the existing shatter spring, corona particles, ProgressRing, hover/click contract):

```tsx
// nexus-ui/src/components/AgentNode.tsx
import { useRef, useEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { useSpring, animated } from '@react-spring/three'
import * as THREE from 'three'
import type { AgentState } from '../types'
import { AGENT_RADII, agentColor } from '../types'
import { ProgressRing } from './ProgressRing'
import { NodeLabel } from './NodeLabel'
import { useNexusStore } from '../store'

interface AgentNodeProps {
  agent: AgentState
  position: [number, number, number]
  dimmed: boolean
  onHoverEnter: (id: string, x: number, y: number) => void
  onHoverLeave: () => void
}

const RIM_VERTEX = `
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    vNormal = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`

const RIM_FRAGMENT = `
  uniform vec3 uColor;
  uniform float uIntensity;
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    float fres = pow(1.0 - max(dot(vNormal, vView), 0.0), 2.5);
    gl_FragColor = vec4(uColor * uIntensity, fres);
  }
`

/** Additive fresnel rim — the razor-thin glowing edge that sells the glass look. */
function FresnelRim({ radius, color, intensityRef }: {
  radius: number
  color: string
  intensityRef: React.MutableRefObject<number>
}) {
  const matRef = useRef<THREE.ShaderMaterial>(null!)
  const uniforms = useMemo(() => ({
    uColor: { value: new THREE.Color(color) },
    uIntensity: { value: 1.0 },
  }), [color])

  useFrame(() => {
    if (matRef.current) matRef.current.uniforms.uIntensity.value = intensityRef.current
  })

  return (
    <mesh scale={1.03}>
      <sphereGeometry args={[radius, 48, 48]} />
      <shaderMaterial ref={matRef} vertexShader={RIM_VERTEX} fragmentShader={RIM_FRAGMENT}
                      uniforms={uniforms} transparent depthWrite={false}
                      blending={THREE.AdditiveBlending} />
    </mesh>
  )
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

  useFrame(() => {
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
  const glassRef = useRef<THREE.Mesh>(null!)
  const coreRef = useRef<THREE.Mesh>(null!)
  const rimIntensity = useRef(1.0)
  const { status, id, name, role } = agent
  const radius = AGENT_RADII[id] ?? 0.6
  const color = agentColor(id)
  const selectAgent = useNexusStore(s => s.selectAgent)
  const resetAgentStatus = useNexusStore(s => s.resetAgentStatus)
  const lastCpIdx = agent.checkpoints.length

  const [shatterSpring, shatterApi] = useSpring(() => ({
    scale: 1,
    opacity: 1,
    config: { tension: 280, friction: 18 },
  }))

  const handleClick = () => {
    shatterApi.start({ scale: 1.6, opacity: 0 })
    selectAgent(id)
  }

  const selectedAgent = useNexusStore(s => s.selectedAgent)
  useEffect(() => {
    if (selectedAgent === null) {
      shatterApi.start({ scale: 1, opacity: 1 })
    }
  }, [selectedAgent, shatterApi])

  useEffect(() => {
    if (status !== 'done') return
    const timer = setTimeout(() => resetAgentStatus(id), 3000)
    return () => clearTimeout(timer)
  }, [status, id, resetAgentStatus])

  useFrame(() => {
    const t = Date.now() / 1000

    // Status → emissive intensity. Raised past the bloom threshold (0.3) when active.
    let emissive: number
    let rim: number
    let coreOpacity: number
    if (status === 'thinking') {
      emissive = 0.5 + ((Math.sin(t * Math.PI) + 1) / 2) * 0.7
      rim = 1.4
      coreOpacity = 0.6
    } else if (status === 'working') {
      emissive = 1.0 + ((Math.sin(t * Math.PI * 2.5) + 1) / 2) * 1.4
      rim = 2.0
      coreOpacity = 0.9
    } else if (status === 'done') {
      emissive = 3.0
      rim = 2.4
      coreOpacity = 1.0
    } else {
      emissive = dimmed ? 0.04 : 0.18
      rim = dimmed ? 0.3 : 0.9
      coreOpacity = dimmed ? 0.12 : 0.35
    }

    if (glassRef.current) {
      (glassRef.current.material as THREE.MeshPhysicalMaterial).emissiveIntensity = emissive
      glassRef.current.position.y = Math.sin(t * 1.0 + id.charCodeAt(0) * 0.5) * 0.08
    }
    if (coreRef.current) {
      (coreRef.current.material as THREE.MeshBasicMaterial).opacity = coreOpacity
      coreRef.current.position.y = Math.sin(t * 1.0 + id.charCodeAt(0) * 0.5) * 0.08
      coreRef.current.rotation.y += 0.01
    }
    rimIntensity.current = rim
  })

  const showCorona = status === 'thinking' || status === 'working'
  const coronaSpeed = status === 'working' ? 1.5 : 0.6

  return (
    <group position={position}>
      {/* Tinted glass shell */}
      <animated.mesh
        ref={glassRef}
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
        <sphereGeometry args={[radius, 48, 48]} />
        <animated.meshPhysicalMaterial
          color={color}
          emissive={color}
          emissiveIntensity={0.18}
          metalness={0.1}
          roughness={0.12}
          clearcoat={1}
          clearcoatRoughness={0.25}
          envMapIntensity={1.6}
          transparent
          opacity={shatterSpring.opacity.to(o => o * 0.32)}
        />
      </animated.mesh>

      {/* Inner energy core — visible through the glass */}
      <mesh ref={coreRef}>
        <icosahedronGeometry args={[radius * 0.4, 1]} />
        <meshBasicMaterial color={color} transparent opacity={0.35} toneMapped={false} wireframe />
      </mesh>

      <FresnelRim radius={radius} color={color} intensityRef={rimIntensity} />

      {showCorona && (
        <CoronaParticles count={12} orbitRadius={radius + 0.3} color={color} speed={coronaSpeed} />
      )}

      <ProgressRing agent={agent} nodeRadius={radius} lastCheckpointIndex={lastCpIdx} />

      <NodeLabel position={[0, -(radius + 0.45), 0]} name={name} role={role}
                 color={color} dimmed={dimmed} />
    </group>
  )
}
```

Note: the old icosahedron survives only as the *inner wireframe core*, where faceting reads as intentional tech detail instead of cheap geometry.

- [x] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/NodeLabel.tsx nexus-ui/src/components/AgentNode.tsx
git commit -m "feat(ui): glass worker nodes — fresnel rim, inner core, CSS labels"
```

---

### Task 4: Reactor core rework — layered orbital ring system with energy core

**Files:**
- Rewrite: `nexus-ui/src/components/CeoNode.tsx`

Fixes feedback item: "solid yellow ball with flat rings" → a small white-hot core inside two counter-rotating wireframe shells, a 40-particle volumetric glow fog, the existing three tori, and CSS labels.

- [x] **Step 1: Rewrite `CeoNode.tsx`**

```tsx
// nexus-ui/src/components/CeoNode.tsx
import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useNexusStore } from '../store'
import { AGENT_POSITIONS } from '../types'
import { NodeLabel } from './NodeLabel'

interface CeoNodeProps {
  isSpeaking: boolean
  onClick: () => void
}

const FOG_COUNT = 40

/** Volumetric-looking particle glow inside the reactor shells. */
function CoreFog() {
  const ref = useRef<THREE.Points>(null!)
  const positions = useMemo(() => {
    const pos = new Float32Array(FOG_COUNT * 3)
    for (let i = 0; i < FOG_COUNT; i++) {
      const theta = Math.random() * Math.PI * 2
      const phi = Math.random() * Math.PI
      const r = 0.1 + Math.random() * 0.32
      pos[i * 3]     = Math.sin(phi) * Math.cos(theta) * r
      pos[i * 3 + 1] = Math.cos(phi) * r
      pos[i * 3 + 2] = Math.sin(phi) * Math.sin(theta) * r
    }
    return pos
  }, [])

  useFrame((state) => {
    if (ref.current) ref.current.rotation.y = state.clock.elapsedTime * 0.4
  })

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial color="#fbbf24" size={0.045} transparent opacity={0.55}
                      sizeAttenuation depthWrite={false}
                      blending={THREE.AdditiveBlending} />
    </points>
  )
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
  const shellARef = useRef<THREE.Mesh>(null!)
  const shellBRef = useRef<THREE.Mesh>(null!)
  const lightRef = useRef<THREE.PointLight>(null!)

  const status = useNexusStore(s => s.agents['ceo']?.status ?? 'idle')
  const selectAgent = useNexusStore(s => s.selectAgent)
  const position = AGENT_POSITIONS['ceo']!

  const speeds = useMemo(() => {
    if (status === 'working')  return { r1: 3.0,  r2: -2.0, r3: 1.2,  sh: 2.2 }
    if (status === 'thinking') return { r1: 1.8,  r2: -1.2, r3: 0.75, sh: 1.4 }
    return                            { r1: 0.6,  r2: -0.4, r3: 0.25, sh: 0.5 }
  }, [status])

  useFrame((_, delta) => {
    if (ring1Ref.current) ring1Ref.current.rotation.z += delta * speeds.r1
    if (ring2Ref.current) ring2Ref.current.rotation.y += delta * speeds.r2
    if (ring3Ref.current) ring3Ref.current.rotation.x += delta * speeds.r3
    if (shellARef.current) {
      shellARef.current.rotation.y += delta * speeds.sh
      shellARef.current.rotation.x += delta * speeds.sh * 0.4
    }
    if (shellBRef.current) {
      shellBRef.current.rotation.y -= delta * speeds.sh * 0.7
      shellBRef.current.rotation.z += delta * speeds.sh * 0.3
    }
    if (lightRef.current) {
      const t = Date.now() / 1000
      lightRef.current.intensity = status === 'thinking'
        ? 2.5 + Math.sin(t * Math.PI) * 0.5
        : status === 'working'
        ? 3.0 + Math.sin(t * Math.PI * 2) * 1.0
        : 2.0
    }
  })

  return (
    <group position={position}>
      {/* White-hot energy core (small + overbright → blooms hard) */}
      <mesh
        onClick={() => { onClick(); selectAgent('ceo') }}
        onPointerOver={() => { document.body.style.cursor = 'pointer' }}
        onPointerOut={() => { document.body.style.cursor = 'default' }}
      >
        <sphereGeometry args={[0.16, 32, 32]} />
        <meshBasicMaterial color="#fff3c4" toneMapped={false} />
      </mesh>

      <CoreFog />

      {/* Counter-rotating wireframe shells around the core */}
      <mesh ref={shellARef}>
        <icosahedronGeometry args={[0.32, 1]} />
        <meshBasicMaterial color="#f59e0b" wireframe transparent opacity={0.5} />
      </mesh>
      <mesh ref={shellBRef}>
        <icosahedronGeometry args={[0.43, 1]} />
        <meshBasicMaterial color="#fbbf24" wireframe transparent opacity={0.28} />
      </mesh>

      <pointLight ref={lightRef} color="#f59e0b" intensity={2.0} distance={12} />

      {/* Existing tori — kept, speeds unchanged */}
      <mesh ref={ring1Ref}>
        <torusGeometry args={[0.55, 0.03, 16, 64]} />
        <meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={2.5} />
      </mesh>
      <mesh ref={ring2Ref} rotation={[Math.PI * 0.31, 0, 0]}>
        <torusGeometry args={[0.8, 0.025, 16, 64]} />
        <meshStandardMaterial color="#fbbf24" emissive="#fbbf24" emissiveIntensity={2.0} />
      </mesh>
      <mesh ref={ring3Ref} rotation={[0, 0, Math.PI * 0.17]}>
        <torusGeometry args={[1.05, 0.02, 16, 64]} />
        <meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={1.5}
                              transparent opacity={0.6} />
      </mesh>

      {isSpeaking && <AudioWaveformRing radius={1.2} color="#fbbf24" />}

      <NodeLabel position={[0, -1.55, 0]} name="Subaru Natsuki"
                 role="Chief Executive Officer" color="#f59e0b" />
    </group>
  )
}
```

- [x] **Step 2: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/CeoNode.tsx
git commit -m "feat(ui): reactor core rework — wireframe shells, core fog, white-hot center"
```

---

### Task 5: Neural energy tubes — thick translucent conduits with light-capsule pulses

**Files:**
- Rewrite: `nexus-ui/src/components/NeuralEdge.tsx`

Fixes feedback item 3: `QuadraticBezierLine` (0.5–1.5 *pixel* width) becomes a real `TubeGeometry` conduit — dark and semi-transparent at rest; when active, an elongated glowing capsule races down the tube with a fading trail. Keeps the existing ReverseBurst on completion.

- [x] **Step 1: Rewrite `NeuralEdge.tsx`**

```tsx
// nexus-ui/src/components/NeuralEdge.tsx
import { useRef, useMemo, useState, useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { agentColor } from '../types'

interface NeuralEdgeProps {
  start: [number, number, number]
  end:   [number, number, number]
  isActive: boolean
  workerId: string
}

const UP = new THREE.Vector3(0, 1, 0)
const PULSE_OFFSETS = [0, 0.33, 0.66]

/** A glowing capsule head + two fading trail spheres, racing down the curve. */
function Pulse({ curve, offset, color }: {
  curve: THREE.QuadraticBezierCurve3
  offset: number
  color: string
}) {
  const head = useRef<THREE.Mesh>(null!)
  const trail1 = useRef<THREE.Mesh>(null!)
  const trail2 = useRef<THREE.Mesh>(null!)
  const tRef = useRef(offset)

  useFrame((_, delta) => {
    tRef.current = (tRef.current + delta / 1.8) % 1
    const t = tRef.current
    if (head.current) {
      head.current.position.copy(curve.getPoint(t))
      head.current.quaternion.setFromUnitVectors(UP, curve.getTangent(t))
    }
    if (trail1.current) trail1.current.position.copy(curve.getPoint(Math.max(0, t - 0.035)))
    if (trail2.current) trail2.current.position.copy(curve.getPoint(Math.max(0, t - 0.07)))
  })

  return (
    <group>
      <mesh ref={head}>
        <capsuleGeometry args={[0.03, 0.22, 4, 8]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={3.2}
                              toneMapped={false} />
      </mesh>
      <mesh ref={trail1}>
        <sphereGeometry args={[0.022, 6, 6]} />
        <meshBasicMaterial color={color} transparent opacity={0.45} />
      </mesh>
      <mesh ref={trail2}>
        <sphereGeometry args={[0.014, 6, 6]} />
        <meshBasicMaterial color={color} transparent opacity={0.2} />
      </mesh>
    </group>
  )
}

function ReverseBurst({ curve }: { curve: THREE.QuadraticBezierCurve3 }) {
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
          mesh.position.copy(curve.getPoint(Math.max(0, next)))
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

export function NeuralEdge({ start, end, isActive, workerId }: NeuralEdgeProps) {
  const [showBurst, setShowBurst] = useState(false)
  const burstKey = useRef(0)
  const prevActiveRef = useRef(isActive)

  const color = agentColor(workerId)

  const mid: [number, number, number] = [
    (start[0] + end[0]) / 2,
    (start[1] + end[1]) / 2 + 1.5,
    (start[2] + end[2]) / 2,
  ]

  const curve = useMemo(() => new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(...start),
    new THREE.Vector3(...mid),
    new THREE.Vector3(...end),
  ), [start[0], start[1], start[2], end[0], end[1], end[2], mid[0], mid[1], mid[2]])

  const tubeGeometry = useMemo(() => new THREE.TubeGeometry(curve, 40, 0.014, 8, false), [curve])
  useEffect(() => () => tubeGeometry.dispose(), [tubeGeometry])

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
      {/* The conduit — dark translucent at rest, lit from within when active */}
      <mesh geometry={tubeGeometry}>
        <meshStandardMaterial color="#0b1426" emissive={color}
                              emissiveIntensity={isActive ? 0.5 : 0.06}
                              transparent opacity={isActive ? 0.5 : 0.22} />
      </mesh>

      {isActive && PULSE_OFFSETS.map((offset, i) => (
        <Pulse key={i} curve={curve} offset={offset} color={color} />
      ))}

      {showBurst && <ReverseBurst key={burstKey.current} curve={curve} />}
    </group>
  )
}
```

- [x] **Step 2: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/NeuralEdge.tsx
git commit -m "feat(ui): neural energy tubes — TubeGeometry conduits with capsule pulses"
```

---

### Task 6: Atmosphere & bloom retune — procedural env reflections, contrast, error flash

**Files:**
- Modify: `nexus-ui/src/components/Background.tsx`, `nexus-ui/src/components/PostProcessing.tsx`, `nexus-ui/src/store.ts`
- Create: `nexus-ui/src/components/ErrorFlash.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

Fixes feedback item "lack of contrast & scale": darker floor, tighter fog, env-map reflections that make the Task 3 glass actually reflect something, bloom that picks up the new emissive ranges, and a red mood flash on errors.

- [x] **Step 1: Add a procedural environment + darker floor in `Background.tsx`**

Add imports:

```tsx
import { Environment, Lightformer } from '@react-three/drei'
```

In the returned fragment, after the `<fog ...>` line, add (no network fetch — `Lightformer` children render into the env map locally):

```tsx
      <Environment resolution={64}>
        <Lightformer intensity={2} position={[0, 4, -9]} scale={[10, 1, 1]} color="#00f0ff" />
        <Lightformer intensity={1.2} position={[-5, 1, -1]} scale={[2, 0.5, 1]}
                     rotation-y={Math.PI / 2} color="#1e3a5f" />
        <Lightformer intensity={1.5} position={[5, -1, -1]} scale={[2, 0.5, 1]}
                     rotation-y={-Math.PI / 2} color="#f59e0b" />
      </Environment>
```

Tighten the fog (same line):

```tsx
      <fog attach="fog" args={['#020408', 7, 30]} />
```

In `floorFragmentShader`, replace the brightness line to darken the floor so neon pops:

```glsl
    float brightness = 0.09 + max(0.0, vWave * 5.0) * 0.4;
```

- [x] **Step 2: Retune Bloom in `PostProcessing.tsx`**

Replace the `<Bloom ...>` props:

```tsx
      <Bloom
        intensity={1.35}
        luminanceThreshold={0.3}
        luminanceSmoothing={0.9}
        mipmapBlur
      />
```

(Keep ChromaticAberration and Vignette unchanged.)

- [x] **Step 3: Track errors in the store**

In `store.ts`, add to the `NexusStore` interface:

```typescript
  lastErrorTs: number | null
```

Initial value in the `create` call: `lastErrorTs: null,`. Then extend the `case 'error'` branch in `handleEvent`:

```typescript
        case 'error':
          if (agentId) updateAgent(agentId, { status: 'idle' })
          addNotif(`⚠ ${agents[agentId ?? '']?.name ?? agentId ?? 'system'}: ${String(event.message ?? 'error').slice(0, 60)}`, 'system')
          return { agents, edges, notifications, lastErrorTs: Date.now() }
```

- [x] **Step 4: Create the error mood flash (DOM — zero GPU cost)**

```tsx
// nexus-ui/src/components/ErrorFlash.tsx
import { useEffect, useState } from 'react'
import { useNexusStore } from '../store'

/** Brief red radial wash over the scene whenever an error event arrives. */
export function ErrorFlash() {
  const lastErrorTs = useNexusStore(s => s.lastErrorTs)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!lastErrorTs) return
    setVisible(true)
    const t = setTimeout(() => setVisible(false), 700)
    return () => clearTimeout(t)
  }, [lastErrorTs])

  if (!visible) return null
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 25, pointerEvents: 'none',
      background: 'radial-gradient(ellipse at center, transparent 40%, rgba(239,68,68,0.18) 100%)',
      animation: 'nexus-errorflash 700ms ease-out forwards',
    }}>
      <style>{'@keyframes nexus-errorflash { from { opacity: 1 } to { opacity: 0 } }'}</style>
    </div>
  )
}
```

- [x] **Step 5: Mount `<ErrorFlash />`** in `NexusScene.tsx`'s HUD layer (next to `<SystemVitals />`).

- [x] **Step 6: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/Background.tsx nexus-ui/src/components/PostProcessing.tsx nexus-ui/src/store.ts nexus-ui/src/components/ErrorFlash.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): atmosphere retune — procedural env reflections, darker floor, mipmap bloom, error flash"
```

---

### Task 7: Camera director — fly-to on select, idle auto-orbit

**Files:**
- Create: `nexus-ui/src/components/CameraDirector.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

The single biggest "feels basic" motion fix: the camera must move with intent.

- [x] **Step 1: Create the component**

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

- [x] **Step 2: Wire into `NexusScene.tsx`**

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

(Reuse `positionFor` in the Task 2 roster loop to avoid duplicated layout math.)

- [x] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/CameraDirector.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): cinematic camera — fly-to on select, idle auto-orbit"
```

---

### Task 8: Boot sequence + offline banner

**Files:**
- Create: `nexus-ui/src/components/BootOverlay.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

- [x] **Step 1: Create the component**

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

- [x] **Step 2: Mount as the last child in `NexusScene.tsx`'s root div:** `<BootOverlay />`.

- [x] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/BootOverlay.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): boot sequence + uplink-lost banner"
```

---

### Task 9: Reactor data ring — orbiting activity bars + CSS clock readout

**Files:**
- Create: `nexus-ui/src/components/ReactorRing.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

A rotating instanced ring of 48 bars around the CEO whose heights respond to live agent activity. One instanced mesh = one draw call. The clock readout uses `<Html>` (CSS), not 3D text.

- [x] **Step 1: Create the component**

```tsx
// nexus-ui/src/components/ReactorRing.tsx
import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
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
      <Html position={[0, 1.55, 0]} center distanceFactor={8} zIndexRange={[20, 0]}
            style={{ pointerEvents: 'none', userSelect: 'none' }}>
        <div style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#00f0ff',
          letterSpacing: '0.3em', whiteSpace: 'nowrap',
          textShadow: '0 0 8px rgba(0,240,255,0.7)',
        }}>
          {clock} · {busyCount} ACTIVE
        </div>
      </Html>
    </group>
  )
}
```

(The clock string re-renders whenever store state changes — minute-accurate is fine; no timer needed.)

- [x] **Step 2: Mount inside the Canvas in `NexusScene.tsx`**, after `<CeoNode ... />`: `<ReactorRing />`.

- [x] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/ReactorRing.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): reactor data ring — instanced activity bars + CSS clock"
```

---

### Task 10: Edge task labels — what is flowing, not just that it flows (CSS chips)

**Files:**
- Create: `nexus-ui/src/components/EdgeTaskLabel.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

- [x] **Step 1: Create the component**

```tsx
// nexus-ui/src/components/EdgeTaskLabel.tsx
import { Html } from '@react-three/drei'
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
  const color = agentColor(workerId)

  return (
    <Html position={mid} center distanceFactor={9} zIndexRange={[20, 0]}
          style={{ pointerEvents: 'none', userSelect: 'none' }}>
      <div style={{
        maxWidth: 240, textAlign: 'center',
        fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color,
        background: 'rgba(2, 4, 8, 0.55)', border: `1px solid ${color}33`,
        borderRadius: 6, padding: '3px 8px',
        textShadow: '0 0 6px currentColor',
      }}>
        {item.task.length > 60 ? item.task.slice(0, 60) + '…' : item.task}
      </div>
    </Html>
  )
}
```

- [x] **Step 2: Mount per worker** in `NexusScene.tsx`'s roster loop, inside the `<group key={id}>` next to `<NeuralEdge ...>`:

```tsx
              <EdgeTaskLabel workerId={id} start={ceoPos} end={pos} />
```

- [x] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/EdgeTaskLabel.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): floating task labels on active delegation edges"
```

---

### Task 11: Holo browser screen — Maya's live frames as a 3D hologram

**Files:**
- Create: `nexus-ui/src/components/HoloBrowser.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

The signature Jarvis feature: the live CDP screencast (already in `browserView` from Plan A) becomes a glowing screen floating above Maya. The DOM `BrowserViewport` panel remains for close inspection; this is the ambient version. Caption is CSS via `<Html>`.

- [x] **Step 1: Create the component**

```tsx
// nexus-ui/src/components/HoloBrowser.tsx
import { useEffect, useMemo, useRef, useState } from 'react'
import { Billboard, Html } from '@react-three/drei'
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
      <Html position={[0, -0.95, 0]} center distanceFactor={8} zIndexRange={[20, 0]}
            style={{ pointerEvents: 'none', userSelect: 'none' }}>
        <div style={{
          maxWidth: 280, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: VIOLET,
          textShadow: `0 0 6px ${VIOLET}99`,
        }}>
          {(view.caption ? `${view.caption} · ` : '') + view.url.slice(0, 70)}
        </div>
      </Html>
    </Billboard>
  )
}
```

- [x] **Step 2: Mount above Maya** in `NexusScene.tsx`'s roster loop, inside `<group key={id}>`:

```tsx
              {id === 'browser' && <HoloBrowser position={pos} />}
```

- [x] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/HoloBrowser.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): holographic live browser screen above Maya"
```

---

### Task 12: Global command bar — "CEO | Ask Subaru anything…"

**Files:**
- Create: `nexus-ui/src/components/CommandBar.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`, `nexus-ui/src/components/SystemVitals.tsx`

The master control console from the original 2D dashboard, reimagined for the 3D scene: a glowing input bar fixed at bottom-center. Type a natural-language prompt, hit Enter, and watch Subaru fire a neural pulse to the right worker (the delegation flow from Plan A does the rest). A target chip on the left (default `CEO`) lets you message any agent 1:1 — this rides the `agent` field routing fixed in Plan A Task 4. `/` focuses the bar; the bar pulses in the target's color while the CEO is thinking/working.

- [x] **Step 1: Create the component**

```tsx
// nexus-ui/src/components/CommandBar.tsx
import { useEffect, useRef, useState } from 'react'
import { useNexusStore, sendWsMessage } from '../store'
import { agentColor } from '../types'
import { useVoice } from '../hooks/useVoice'

export function CommandBar() {
  const agents = useNexusStore(s => s.agents)
  const ceoStatus = useNexusStore(s => s.agents['ceo']?.status ?? 'idle')
  const wsStatus = useNexusStore(s => s.wsStatus)
  const [text, setText] = useState('')
  const [target, setTarget] = useState('ceo')
  const [pickerOpen, setPickerOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const voice = useVoice(target, (t) => {
    sendWsMessage({ type: 'message', agent: target, text: t })
  })

  const send = () => {
    const t = text.trim()
    if (!t || wsStatus !== 'connected') return
    sendWsMessage({ type: 'message', agent: target, text: t })
    setText('')
  }

  // '/' focuses the bar (unless already typing somewhere); Escape blurs.
  // 'nexus-focus-cmdbar' is dispatched by the wake-word hook (Task 14).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/') return
      const el = document.activeElement
      if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) return
      e.preventDefault()
      inputRef.current?.focus()
    }
    const onFocusReq = () => inputRef.current?.focus()
    window.addEventListener('keydown', onKey)
    window.addEventListener('nexus-focus-cmdbar', onFocusReq)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('nexus-focus-cmdbar', onFocusReq)
    }
  }, [])

  const tColor = agentColor(target)
  const busy = ceoStatus === 'thinking' || ceoStatus === 'working'
  const firstName = agents[target]?.name?.split(' ')[0] ?? target

  return (
    <div style={{
      position: 'fixed', bottom: 18, left: '50%', transform: 'translateX(-50%)',
      zIndex: 130, width: 'min(680px, calc(100vw - 360px))',
    }}>
      {/* Agent target picker */}
      {pickerOpen && (
        <div style={{
          position: 'absolute', bottom: 54, left: 0, minWidth: 240,
          background: 'rgba(8, 14, 28, 0.96)', backdropFilter: 'blur(24px)',
          border: '1px solid rgba(0, 240, 255, 0.18)', borderRadius: 10,
          overflow: 'hidden', boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
        }}>
          {Object.entries(agents).map(([id, a]) => (
            <button key={id}
              onClick={() => { setTarget(id); setPickerOpen(false); inputRef.current?.focus() }}
              style={{
                display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                background: id === target ? `${agentColor(id)}14` : 'none',
                border: 'none', padding: '8px 14px', cursor: 'pointer', textAlign: 'left',
              }}>
              <span style={{
                width: 8, height: 8, borderRadius: '50%',
                background: agentColor(id), boxShadow: `0 0 6px ${agentColor(id)}`,
              }} />
              <span style={{ color: '#e2e8f0', fontSize: 12, fontFamily: 'Inter, sans-serif' }}>
                {a.name}
              </span>
              <span style={{ color: '#475569', fontSize: 10, marginLeft: 'auto' }}>{a.role}</span>
            </button>
          ))}
        </div>
      )}

      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px',
        background: 'rgba(8, 14, 28, 0.88)', backdropFilter: 'blur(24px) saturate(1.4)',
        border: `1px solid ${busy ? tColor : 'rgba(0, 240, 255, 0.18)'}`,
        borderRadius: 12, transition: 'border-color 300ms, box-shadow 300ms',
        boxShadow: busy ? `0 0 24px ${tColor}44` : '0 0 18px rgba(0, 240, 255, 0.08)',
        animation: busy ? 'cmdbar-pulse 1.6s ease-in-out infinite' : 'none',
      }}>
        <style>{`@keyframes cmdbar-pulse { 50% { box-shadow: 0 0 36px ${tColor}66 } }`}</style>

        {/* Target chip */}
        <button onClick={() => setPickerOpen(o => !o)} style={{
          background: `${tColor}16`, border: `1px solid ${tColor}55`, color: tColor,
          borderRadius: 8, padding: '5px 12px', fontSize: 10, cursor: 'pointer',
          fontFamily: 'Orbitron, sans-serif', letterSpacing: '0.12em', whiteSpace: 'nowrap',
          textShadow: `0 0 8px ${tColor}88`,
        }}>
          {target === 'ceo' ? 'CEO' : firstName.toUpperCase()} ▾
        </button>

        <input
          ref={inputRef}
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') send()
            if (e.key === 'Escape') inputRef.current?.blur()
          }}
          placeholder={target === 'ceo' ? 'Ask Subaru anything…' : `Message ${firstName}…`}
          style={{
            flex: 1, background: 'transparent', border: 'none', outline: 'none',
            color: '#e2e8f0', fontSize: 14, fontFamily: 'Inter, sans-serif',
          }}
        />

        {voice.hasSpeechRecognition && (
          <button
            onClick={() => voice.isListening ? voice.stopListening() : voice.startListening()}
            title={voice.isListening ? 'Stop recording' : 'Voice input'}
            style={{
              background: voice.isListening ? `${tColor}22` : 'none',
              border: `1px solid ${voice.isListening ? tColor : '#334155'}`,
              color: voice.isListening ? tColor : '#94a3b8',
              borderRadius: 8, padding: '5px 10px', cursor: 'pointer', fontSize: 13,
            }}>
            {voice.isListening ? '◉' : '🎤'}
          </button>
        )}

        <button onClick={send} disabled={wsStatus !== 'connected'} style={{
          background: wsStatus === 'connected' ? `${tColor}1e` : '#1e293b',
          border: `1px solid ${wsStatus === 'connected' ? `${tColor}66` : '#334155'}`,
          color: wsStatus === 'connected' ? tColor : '#475569',
          borderRadius: 8, padding: '5px 14px', fontSize: 11, fontWeight: 700,
          cursor: wsStatus === 'connected' ? 'pointer' : 'default',
          fontFamily: 'Orbitron, sans-serif', letterSpacing: '0.08em',
        }}>
          SEND
        </button>
      </div>
    </div>
  )
}
```

`width: min(680px, calc(100vw - 360px))` keeps it clear of the SmartIsland chip (bottom-right) on narrow windows.

- [x] **Step 2: Move SystemVitals up out of the way**

In `SystemVitals.tsx`, change the container's `bottom: 16` to `bottom: 74` (it now sits directly above the command bar).

- [x] **Step 3: Mount `<CommandBar />`** in `NexusScene.tsx`'s HUD layer (next to `<SystemVitals />`).

- [x] **Step 4: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/CommandBar.tsx nexus-ui/src/components/SystemVitals.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): global command bar — CEO | Ask Subaru anything"
```

---

### Task 13: Actionable HUD — clickable queue items and notifications

**Files:**
- Modify: `nexus-ui/src/store.ts`, `nexus-ui/src/components/SmartIsland.tsx`, `nexus-ui/src/components/NexusScene.tsx`, `nexus-ui/src/components/OpsDrawer.tsx`

Every glowing thing becomes a control: clicking a queue row flies to that worker (CameraDirector reacts to `selectAgent`); clicking an approval/email/routine notification opens the right OpsDrawer tab.

- [x] **Step 1: Add an ops-open request channel to the store**

In `store.ts`, add to the `NexusStore` interface:

```typescript
  opsRequest: { tab: 'routines' | 'skills' | 'approvals' | 'email' | 'team'; ts: number } | null
  openOps: (tab: 'routines' | 'skills' | 'approvals' | 'email' | 'team') => void
```

Initial value + action in the `create` call:

```typescript
  opsRequest: null,
  openOps: (tab) => set({ opsRequest: { tab, ts: Date.now() } }),
```

- [x] **Step 2: Let NexusScene + OpsDrawer honor the request**

In `NexusScene.tsx` (which owns the local `opsOpen` state):

```tsx
  const opsRequest = useNexusStore(s => s.opsRequest)
  useEffect(() => { if (opsRequest) setOpsOpen(true) }, [opsRequest])
```

(import `useEffect`). Pass the request down:

```tsx
      <OpsDrawer open={opsOpen} onClose={() => setOpsOpen(false)} requestedTab={opsRequest} />
```

In `OpsDrawer.tsx`, extend the props and sync the tab:

```tsx
export function OpsDrawer({ open, onClose, requestedTab }: {
  open: boolean
  onClose: () => void
  requestedTab?: { tab: OpsTab; ts: number } | null
}) {
```

```tsx
  useEffect(() => {
    if (requestedTab) setTab(requestedTab.tab)
  }, [requestedTab])
```

- [x] **Step 3: Make SmartIsland rows clickable**

In `SmartIsland.tsx`, pull the actions:

```tsx
  const selectAgent = useNexusStore(s => s.selectAgent)
  const openOps     = useNexusStore(s => s.openOps)
```

Queue rows — add to the row `div`:

```tsx
                  onClick={() => { if (item.agent) { selectAgent(item.agent); setExpanded(false) } }}
```

and add `cursor: item.agent ? 'pointer' : 'default'` to its style object.

Notification rows — add to the row `div`:

```tsx
                  onClick={() => {
                    if (n.type === 'approval') openOps('approvals')
                    else if (n.type === 'email') openOps('email')
                    else if (n.type === 'routine') openOps('routines')
                  }}
```

and `cursor: ['approval', 'email', 'routine'].includes(n.type) ? 'pointer' : 'default'` in its style.

- [x] **Step 4: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/store.ts nexus-ui/src/components/SmartIsland.tsx nexus-ui/src/components/NexusScene.tsx nexus-ui/src/components/OpsDrawer.tsx
git commit -m "feat(ui): actionable HUD — clickable queue rows and notifications"
```

---

### Task 14: Wake word + palette free-text fallback

**Files:**
- Create: `nexus-ui/src/hooks/useWakeWord.ts`
- Modify: `nexus-ui/src/hooks/useCommandPalette.ts`, `nexus-ui/src/components/NexusScene.tsx`

Two ways to talk without touching the bar: say "Nexus …" / "Subaru …" (continuous listening, **off by default**, Chrome-only — toggled from the ⌘K palette), or type anything unmatched into the ⌘K palette and pick "Ask Subaru".

- [x] **Step 1: Create the wake-word hook**

```typescript
// nexus-ui/src/hooks/useWakeWord.ts
import { useEffect } from 'react'
import { sendWsMessage } from '../store'

const WAKE_KEY = 'nexus-wake-enabled'
const WAKE_RE = /\b(nexus|subaru)\b[,.]?\s*/i

export function isWakeEnabled(): boolean {
  try { return localStorage.getItem(WAKE_KEY) === 'true' } catch { return false }
}

export function toggleWakeWord(): boolean {
  const next = !isWakeEnabled()
  try { localStorage.setItem(WAKE_KEY, String(next)) } catch { /* ignore */ }
  // Reload-free toggle: the hook below polls this flag on each recognition cycle.
  return next
}

/**
 * Continuous wake-word listener. When a final transcript contains "nexus"/"subaru":
 * - if there's a command after the wake word → send it straight to the CEO
 * - if the wake word is alone → focus the command bar
 * Chrome-only (webkitSpeechRecognition); silently inert elsewhere.
 */
export function useWakeWord() {
  useEffect(() => {
    const SR = (window as unknown as { webkitSpeechRecognition?: new () => unknown }).webkitSpeechRecognition
      ?? (window as unknown as { SpeechRecognition?: new () => unknown }).SpeechRecognition
    if (!SR) return

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let recog: any = null
    let stopped = false

    const start = () => {
      if (stopped || !isWakeEnabled()) {
        // Re-check the toggle every 3s while disabled
        if (!stopped) setTimeout(start, 3000)
        return
      }
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        recog = new (SR as any)()
        recog.continuous = true
        recog.interimResults = false
        recog.lang = 'en-US'
        recog.onresult = (e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal?: boolean }> }) => {
          const last = e.results[e.results.length - 1]
          const transcript = (last?.[0]?.transcript ?? '').trim()
          const m = WAKE_RE.exec(transcript)
          if (!m) return
          const command = transcript.slice(m.index + m[0].length).trim()
          if (command) {
            sendWsMessage({ type: 'message', agent: 'ceo', text: command })
          } else {
            window.dispatchEvent(new Event('nexus-focus-cmdbar'))
          }
        }
        recog.onend = () => { if (!stopped) setTimeout(start, 500) }   // auto-restart
        recog.onerror = () => { /* onend fires next and restarts */ }
        recog.start()
      } catch { /* mic blocked — stay inert */ }
    }

    start()
    return () => {
      stopped = true
      try { recog?.stop() } catch { /* ignore */ }
    }
  }, [])
}
```

- [x] **Step 2: Palette — free-text "Ask Subaru" + wake toggle**

In `useCommandPalette.ts`, import `sendWsMessage` alongside the existing store imports, and `toggleWakeWord` from `./useWakeWord`:

```typescript
import { useNexusStore, connectWebSocket, sendWsMessage } from '../store'
import { toggleWakeWord } from './useWakeWord'
```

Add to the `actions` array:

```typescript
    { id: 'wake-toggle', label: 'Toggle wake word ("Nexus …")', group: 'VOICE' },
```

Replace the `filtered` computation so unmatched queries become an ask-the-CEO action:

```typescript
  const matched = query.trim()
    ? actions.filter(a => a.label.toLowerCase().includes(query.toLowerCase()))
    : actions
  const filtered: PaletteAction[] = matched.length > 0 ? matched : [
    { id: 'ask-subaru', label: `Ask Subaru: "${query.trim()}"`, group: 'COMMAND', accent: '#f59e0b' },
  ]
```

In `runAction`, handle both new ids **before** the query is cleared (move `setQuery('')` after the dispatch):

```typescript
  const runAction = useCallback((id: string, toggleTts?: () => void) => {
    setOpen(false)

    if (id.startsWith('agent-')) {
      selectAgent(id.replace('agent-', ''))
    } else if (id === 'queue-show') {
      setIslandTab('queue')
    } else if (id === 'notif-show') {
      setIslandTab('notifications')
    } else if (id === 'tts-toggle') {
      toggleTts?.()
    } else if (id === 'wake-toggle') {
      toggleWakeWord()
    } else if (id === 'ask-subaru') {
      const text = query.trim()
      if (text) sendWsMessage({ type: 'message', agent: 'ceo', text })
    } else if (id === 'ws-reconnect') {
      connectWebSocket()
    }

    setQuery('')
  }, [selectAgent, setIslandTab, query])
```

- [x] **Step 3: Activate the listener** — call `useWakeWord()` at the top of the `NexusScene` component body (import from `../hooks/useWakeWord`).

- [x] **Step 4: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/hooks/useWakeWord.ts nexus-ui/src/hooks/useCommandPalette.ts nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): wake word listener + palette free-text ask-subaru"
```

---

### Task 15: Film finish — scanlines + noise + HUD corner frame

**Files:**
- Modify: `nexus-ui/src/components/PostProcessing.tsx`
- Create: `nexus-ui/src/components/HudFrame.tsx`
- Modify: `nexus-ui/src/components/NexusScene.tsx`

- [x] **Step 1: Add Scanline + Noise effects**

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

- [x] **Step 2: Create the HUD frame**

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

- [x] **Step 3: Mount `<HudFrame />`** in `NexusScene.tsx`'s HUD layer.

- [x] **Step 4: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/components/PostProcessing.tsx nexus-ui/src/components/HudFrame.tsx nexus-ui/src/components/NexusScene.tsx
git commit -m "feat(ui): scanline+noise film finish and HUD corner frame"
```

---

### Task 16 (optional): UI sound blips via WebAudio — no assets, off by default

**Files:**
- Create: `nexus-ui/src/hooks/useSfx.ts`
- Modify: `nexus-ui/src/components/NexusScene.tsx`, `nexus-ui/src/hooks/useCommandPalette.ts`

- [x] **Step 1: Create the hook**

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

- [x] **Step 2: Wire it** — call `useSfx()` at the top of `NexusScene`, and add a palette action in `useCommandPalette.ts`'s `actions` array:

```typescript
    { id: 'sfx-toggle', label: 'Toggle UI sounds', group: 'SYSTEM' },
```

with the handler in `runAction`:

```typescript
    } else if (id === 'sfx-toggle') {
      toggleSfx()
```

(import `toggleSfx` from `./useSfx`).

- [x] **Step 3: Typecheck + commit**

```bash
cd nexus-ui && npx tsc --noEmit && cd ..
git add nexus-ui/src/hooks/useSfx.ts nexus-ui/src/components/NexusScene.tsx nexus-ui/src/hooks/useCommandPalette.ts
git commit -m "feat(ui): optional WebAudio status blips (off by default)"
```

---

### Task 17: Build, deploy, verify — visuals, controls and frame rate

**Files:** none

- [x] **Step 1: Production build**

```bash
cd /mnt/HC_Volume_105874680/virtual-company/nexus-ui && npm run build
```

Expected: success; bundle delta small (no new deps).

- [x] **Step 2: Deploy**

```bash
cd /mnt/HC_Volume_105874680/virtual-company && docker compose up -d --build
docker ps --format "{{.Names}} {{.Status}}" | grep virtual-company
curl -s -m 5 http://127.0.0.1:3031/ | grep -o 'index-[A-Za-z0-9]*\.js'
```

Expected: container Up; served bundle hash changed from `index-BA5fFRqQ.js`.

- [x] **Step 3: Visual verification checklist (in the browser)**

1. Hard-reload → boot sequence types 4 lines → "ALL SYSTEMS NOMINAL" → fades to scene.
2. **Materials:** worker nodes are smooth tinted glass with a thin glowing rim and a wireframe core inside; reflections shift as the camera moves; nothing looks like a flat low-poly ball.
3. **Reactor:** white-hot center, particle fog, two counter-rotating wireframe shells inside the tori.
4. **Edges:** visible dark conduits at rest; on delegation a bright capsule with a fading trail races down the tube.
5. **Typography:** all labels (agent names, clock, edge tasks, holo caption) are crisp CSS — zoom in and confirm no blurry 3D text remains.
6. **Command bar:** bottom-center reads `CEO ▾ | Ask Subaru anything…`. Type "create a hello2.txt file" → Enter → CEO thinking → pulse down an edge → task completes; bar pulses while CEO is busy. Switch the chip to Reinhard → message goes 1:1 (no CEO graph). `/` focuses the bar.
7. **Actionable HUD:** click a queue row → camera flies to that worker; click an approval notification → OpsDrawer opens on APPROVALS.
8. **Palette:** ⌘K, type gibberish like "deploy the rezero site" → "Ask Subaru: …" action appears and sends on Enter.
9. **Wake word (Chrome):** toggle via palette, say "Nexus, what's the system status?" → message sent to CEO.
10. Camera idles in a slow orbit; click Reinhard → glide; Back → return home.
11. Cyan data ring rotates with the CSS clock readout; spins faster while agents work.
12. Give Maya a browse task → hologram above her with live frames; fades 90s after the last frame.
13. Scanlines/grain on dark areas; corner brackets + "N E X U S" title; error event → brief red edge flash.
14. `docker restart virtual-company` → "UPLINK LOST" banner blinks, then reconnects.

- [x] **Step 4: Frame-rate check** — devtools → Performance → record 10s idle and 10s with a running task. Expected ≥ 45 fps on an integrated GPU at 1080p. If below, apply in order: `Background.tsx` particle counts 200/200/100 → 120/120/60; `ReactorRing` `BAR_COUNT` 48 → 32; `NeuralEdge` tube `tubularSegments` 40 → 24; drop `<Noise>`.

- [x] **Step 5: Commit final build**

```bash
git add -A && git commit -m "build: jarvis 3d immersion + visual overhaul production build"
```
