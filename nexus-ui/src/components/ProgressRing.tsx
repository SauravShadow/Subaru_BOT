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
