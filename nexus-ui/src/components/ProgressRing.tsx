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
