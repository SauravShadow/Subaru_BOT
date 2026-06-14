// nexus-ui/src/components/ReactorRing.tsx
import { useMemo, useRef, useState, useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import { Billboard, Text } from '@react-three/drei'
import * as THREE from 'three'
import { useNexusStore } from '../store'

const BAR_COUNT = 48
const RADIUS = 1.7
const CEO_POS: [number, number, number] = [0, 0.5, 4]

export function ReactorRing() {
  const meshRef = useRef<THREE.InstancedMesh>(null!)
  const groupRef = useRef<THREE.Group>(null!)
  const busyCount = useNexusStore(s =>
    Object.values(s.agents).filter(a => a.status === 'working' || a.status === 'thinking').length
  )

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

  const [clock, setClock] = useState(() => new Date().toTimeString().slice(0, 5))
  useEffect(() => {
    const id = setInterval(() => setClock(new Date().toTimeString().slice(0, 5)), 60_000)
    return () => clearInterval(id)
  }, [])

  return (
    <group position={CEO_POS}>
      <group ref={groupRef}>
        <instancedMesh ref={meshRef} args={[undefined, undefined, BAR_COUNT]}>
          <boxGeometry args={[0.015, 0.06, 0.015]} />
          <meshStandardMaterial color="#00f0ff" emissive="#00f0ff" emissiveIntensity={1.6}
                                transparent opacity={0.85} />
        </instancedMesh>
      </group>
      <Billboard position={[0, 1.55, 0]}>
        <Text fontSize={0.12} color="#00f0ff" anchorX="center" anchorY="middle"
              letterSpacing={0.2} outlineWidth={0.005} outlineColor="#020408">
          {`${clock} · ${busyCount} ACTIVE`}
        </Text>
      </Billboard>
    </group>
  )
}
