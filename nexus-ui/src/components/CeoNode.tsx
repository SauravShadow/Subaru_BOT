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
