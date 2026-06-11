// nexus-ui/src/components/Background.tsx
import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

const PARTICLE_COUNT = 300
const RANGE = 20

function makePositions() {
  const pos = new Float32Array(PARTICLE_COUNT * 3)
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    pos[i * 3]     = (Math.random() - 0.5) * RANGE * 2
    pos[i * 3 + 1] = (Math.random() - 0.5) * RANGE * 2
    pos[i * 3 + 2] = (Math.random() - 0.5) * RANGE * 2
  }
  return pos
}

export function Background() {
  const pointsRef = useRef<THREE.Points>(null!)
  const posRef = useRef(makePositions())

  useFrame((_, delta) => {
    const pos = posRef.current
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      pos[i * 3 + 1] += delta * 0.3
      if (pos[i * 3 + 1] > RANGE) pos[i * 3 + 1] -= RANGE * 2
    }
    if (pointsRef.current) {
      (pointsRef.current.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true
    }
  })

  return (
    <>
      <fog attach="fog" args={['#050a14', 8, 40]} />
      <ambientLight intensity={0.3} />
      <gridHelper args={[40, 40, '#0ea5e966', '#0ea5e933']} position={[0, -4, 0]} />
      <points ref={pointsRef}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[posRef.current, 3]}
          />
        </bufferGeometry>
        <pointsMaterial color="#0ea5e9" size={0.05} transparent opacity={0.6} />
      </points>
    </>
  )
}
