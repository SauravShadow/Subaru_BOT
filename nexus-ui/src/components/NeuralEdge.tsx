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
