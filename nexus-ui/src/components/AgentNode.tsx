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

  const handleClick = () => {
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
