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
