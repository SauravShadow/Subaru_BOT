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
