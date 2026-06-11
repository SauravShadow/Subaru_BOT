// nexus-ui/src/components/NeuralEdge.tsx
import { useRef, useMemo, useState, useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import { QuadraticBezierLine } from '@react-three/drei'
import * as THREE from 'three'
import { AGENT_COLORS } from '../types'

interface NeuralEdgeProps {
  start: [number, number, number]
  end:   [number, number, number]
  isActive: boolean
  workerId: string
}

const OFFSETS = [0, 0.2, 0.4, 0.6, 0.8]

function Particle({ curve, offset, active, color }: {
  curve: THREE.QuadraticBezierCurve3
  offset: number
  active: boolean
  color: string
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
      <sphereGeometry args={[0.07, 6, 6]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={2.5} />
    </mesh>
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
          const pos = curve.getPoint(Math.max(0, next))
          mesh.position.copy(pos)
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

  const color = AGENT_COLORS[workerId] ?? '#00f0ff'

  const mid: [number, number, number] = [
    (start[0] + end[0]) / 2,
    (start[1] + end[1]) / 2 + 1.5,
    (start[2] + end[2]) / 2,
  ]

  // Memoized curve — no longer recreated every render
  const curve = useMemo(() => new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(...start),
    new THREE.Vector3(...mid),
    new THREE.Vector3(...end),
  ), [start[0], start[1], start[2], end[0], end[1], end[2], mid[0], mid[1], mid[2]])

  // Detect isActive true→false transition to trigger reverse burst
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
      <QuadraticBezierLine
        start={start}
        mid={mid}
        end={end}
        color={isActive ? color : '#1e293b'}
        lineWidth={isActive ? 1.5 : 0.5}
        transparent
        opacity={isActive ? 1.0 : undefined}
      />

      {isActive && OFFSETS.map((offset, i) => (
        <Particle key={i} curve={curve} offset={offset} active color={color} />
      ))}

      {showBurst && <ReverseBurst key={burstKey.current} curve={curve} />}
    </group>
  )
}
