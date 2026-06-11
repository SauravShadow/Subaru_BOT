// nexus-ui/src/components/Background.tsx
import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useNexusStore } from '../store'

const PARTICLE_COUNT_A = 200
const PARTICLE_COUNT_B = 200
const PARTICLE_COUNT_C = 100
const TOTAL = PARTICLE_COUNT_A + PARTICLE_COUNT_B + PARTICLE_COUNT_C

const floorVertexShader = `
  uniform float uTime;
  varying float vDist;
  varying float vWave;

  void main() {
    // CEO is at world XZ = (0, 4). Plane is rotated -PI/2 on X.
    // For that rotation: world_z = -local_y, so CEO local_y = -4.
    float dist = length(position.xy - vec2(0.0, -4.0));
    float wave = sin(dist * 1.2 - uTime * 2.5) * 0.08;
    float attenuation = 1.0 - smoothstep(0.0, 18.0, dist);
    vWave = wave * attenuation;
    vDist = dist;

    vec3 pos = position;
    // Displace in local Z = world Y (upward) due to -PI/2 X rotation
    pos.z += vWave;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
  }
`

const floorFragmentShader = `
  varying float vDist;
  varying float vWave;

  void main() {
    float radialFade = 1.0 - smoothstep(12.0, 20.0, vDist);
    float brightness = 0.15 + max(0.0, vWave * 5.0) * 0.4;
    // #0ea5e9 = rgb(0.055, 0.647, 0.914)
    vec3 color = vec3(0.055, 0.647, 0.914);
    gl_FragColor = vec4(color, brightness * radialFade * 0.75);
  }
`

function makeAllPositions() {
  const pos = new Float32Array(TOTAL * 3)
  let i = 0

  // Class A: organic drift — random scatter
  for (; i < PARTICLE_COUNT_A; i++) {
    pos[i * 3]     = (Math.random() - 0.5) * 40
    pos[i * 3 + 1] = (Math.random() - 0.5) * 40
    pos[i * 3 + 2] = (Math.random() - 0.5) * 40
  }

  // Class B: orbit around CEO [0, 0.5, 4] at random radii
  for (; i < PARTICLE_COUNT_A + PARTICLE_COUNT_B; i++) {
    const theta = Math.random() * Math.PI * 2
    const phi = Math.random() * Math.PI
    const r = 3 + Math.random() * 8
    pos[i * 3]     = Math.sin(phi) * Math.cos(theta) * r
    pos[i * 3 + 1] = Math.cos(phi) * r * 0.5 + 0.5
    pos[i * 3 + 2] = Math.sin(phi) * Math.sin(theta) * r + 4
  }

  // Class C: data streaks — random XZ near center, full Y range
  for (; i < TOTAL; i++) {
    pos[i * 3]     = (Math.random() - 0.5) * 20
    pos[i * 3 + 1] = (Math.random() - 0.5) * 40
    pos[i * 3 + 2] = (Math.random() - 0.5) * 20
  }

  return pos
}

export function Background() {
  const pointsRef = useRef<THREE.Points>(null!)
  const floorRef = useRef<THREE.Mesh>(null!)
  const posRef = useRef(makeAllPositions())
  const timeRef = useRef(0)

  const agents = useNexusStore(s => s.agents)
  const ceoStatus = agents['ceo']?.status ?? 'idle'

  const ceoLightIntensity = ceoStatus === 'working' ? 5.0 : ceoStatus === 'thinking' ? 3.5 : 2.0

  const floorUniforms = useMemo(() => ({
    uTime: { value: 0 },
  }), [])

  useFrame((_, delta) => {
    timeRef.current += delta
    const t = timeRef.current
    const pos = posRef.current

    // Class A: upward drift + simple XZ noise
    for (let i = 0; i < PARTICLE_COUNT_A; i++) {
      pos[i * 3 + 1] += delta * 0.3
      pos[i * 3]     += Math.sin(t * 0.3 + i * 0.7) * delta * 0.05
      pos[i * 3 + 2] += Math.cos(t * 0.2 + i * 1.1) * delta * 0.05
      if (pos[i * 3 + 1] > 20) pos[i * 3 + 1] -= 40
    }

    // Class B: slow orbit around CEO
    for (let i = PARTICLE_COUNT_A; i < PARTICLE_COUNT_A + PARTICLE_COUNT_B; i++) {
      const speed = 0.08 + (i % 7) * 0.01
      const angle = t * speed + i * 0.314
      const r = 3 + (i % 5) + 3
      pos[i * 3]     = Math.cos(angle) * r
      pos[i * 3 + 2] = Math.sin(angle) * r + 4
      pos[i * 3 + 1] = Math.sin(t * 0.3 + i) * 2 + 0.5
    }

    // Class C: vertical streaks, only rendered if hasWorking (opacity set in material)
    for (let i = PARTICLE_COUNT_A + PARTICLE_COUNT_B; i < TOTAL; i++) {
      pos[i * 3 + 1] += delta * 2.0
      if (pos[i * 3 + 1] > 20) pos[i * 3 + 1] = -20
    }

    if (pointsRef.current) {
      (pointsRef.current.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true
    }

    // Update floor shader time
    if (floorRef.current) {
      const mat = floorRef.current.material as THREE.ShaderMaterial
      mat.uniforms.uTime.value = t
    }
  })

  return (
    <>
      <fog attach="fog" args={['#020408', 6, 35]} />
      <ambientLight intensity={0.15} />
      {/* CEO key light */}
      <pointLight position={[0, 0.5, 4]} color="#f59e0b" intensity={ceoLightIntensity} distance={12} />
      {/* Fill light */}
      <pointLight position={[-6, 4, -2]} color="#1e3a5f" intensity={0.8} distance={20} />
      {/* Rim light */}
      <pointLight position={[6, -2, -4]} color="#0c1a2e" intensity={0.4} distance={15} />

      {/* Cortical wave floor */}
      <mesh ref={floorRef} position={[0, -4, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[40, 40, 80, 80]} />
        <shaderMaterial
          vertexShader={floorVertexShader}
          fragmentShader={floorFragmentShader}
          uniforms={floorUniforms}
          transparent
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      {/* All particle classes in one Points object */}
      <points ref={pointsRef}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[posRef.current, 3]}
          />
        </bufferGeometry>
        <pointsMaterial
          color="#0ea5e9"
          size={0.05}
          transparent
          opacity={0.5}
          sizeAttenuation
        />
      </points>
    </>
  )
}
