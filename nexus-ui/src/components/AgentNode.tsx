// nexus-ui/src/components/AgentNode.tsx
import { useRef, useEffect } from 'react'
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
  const lastCpIdx = agent.checkpoints.length

  useEffect(() => {
    if (status === 'done') {
      const timer = setTimeout(() => {}, 1000)
      return () => clearTimeout(timer)
    }
  }, [status])

  useFrame(() => {
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
        onPointerOver={() => { document.body.style.cursor = 'pointer' }}
        onPointerOut={() => { document.body.style.cursor = 'default' }}
      >
        <icosahedronGeometry args={[radius, 1]} />
        <meshStandardMaterial
          color={STATUS_COLORS[status]}
          emissive={STATUS_COLORS[status]}
          emissiveIntensity={0.1}
          roughness={0.3}
          metalness={0.7}
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
