// nexus-ui/src/components/AgentNode.tsx
import { useRef, useEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { useSpring, animated } from '@react-spring/three'
import * as THREE from 'three'
import type { AgentState } from '../types'
import { AGENT_RADII, agentColor } from '../types'
import { ProgressRing } from './ProgressRing'
import { NodeLabel } from './NodeLabel'
import { useNexusStore } from '../store'

interface AgentNodeProps {
  agent: AgentState
  position: [number, number, number]
  dimmed: boolean
  onHoverEnter: (id: string, x: number, y: number) => void
  onHoverLeave: () => void
}

const RIM_VERTEX = `
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    vNormal = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`

const RIM_FRAGMENT = `
  uniform vec3 uColor;
  uniform float uIntensity;
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    float fres = pow(1.0 - max(dot(vNormal, vView), 0.0), 2.5);
    gl_FragColor = vec4(uColor * uIntensity, fres);
  }
`

/** Additive fresnel rim — the razor-thin glowing edge that sells the glass look. */
function FresnelRim({ radius, color, intensityRef }: {
  radius: number
  color: string
  intensityRef: React.MutableRefObject<number>
}) {
  const matRef = useRef<THREE.ShaderMaterial>(null!)
  const uniforms = useMemo(() => ({
    uColor: { value: new THREE.Color(color) },
    uIntensity: { value: 1.0 },
  }), [color])

  useFrame(() => {
    if (matRef.current) matRef.current.uniforms.uIntensity.value = intensityRef.current
  })

  return (
    <mesh scale={1.03}>
      <sphereGeometry args={[radius, 48, 48]} />
      <shaderMaterial ref={matRef} vertexShader={RIM_VERTEX} fragmentShader={RIM_FRAGMENT}
                      uniforms={uniforms} transparent depthWrite={false}
                      blending={THREE.AdditiveBlending} />
    </mesh>
  )
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
  const glassRef = useRef<THREE.Mesh>(null!)
  const coreRef = useRef<THREE.Mesh>(null!)
  const rimIntensity = useRef(1.0)
  const { status, id, name, role } = agent
  const radius = AGENT_RADII[id] ?? 0.6
  const color = agentColor(id)
  const selectAgent = useNexusStore(s => s.selectAgent)
  const resetAgentStatus = useNexusStore(s => s.resetAgentStatus)
  const lastCpIdx = agent.checkpoints.length

  const [shatterSpring, shatterApi] = useSpring(() => ({
    scale: 1,
    opacity: 1,
    config: { tension: 280, friction: 18 },
  }))

  const handleClick = () => {
    shatterApi.start({ scale: 1.6, opacity: 0 })
    selectAgent(id)
  }

  const selectedAgent = useNexusStore(s => s.selectedAgent)
  useEffect(() => {
    if (selectedAgent === null) {
      shatterApi.start({ scale: 1, opacity: 1 })
    }
  }, [selectedAgent, shatterApi])

  useEffect(() => {
    if (status !== 'done') return
    const timer = setTimeout(() => resetAgentStatus(id), 3000)
    return () => clearTimeout(timer)
  }, [status, id, resetAgentStatus])

  useFrame(() => {
    const t = Date.now() / 1000

    // Status → emissive intensity. Raised past the bloom threshold (0.3) when active.
    let emissive: number
    let rim: number
    let coreOpacity: number
    if (status === 'thinking') {
      emissive = 0.5 + ((Math.sin(t * Math.PI) + 1) / 2) * 0.7
      rim = 1.4
      coreOpacity = 0.6
    } else if (status === 'working') {
      emissive = 1.0 + ((Math.sin(t * Math.PI * 2.5) + 1) / 2) * 1.4
      rim = 2.0
      coreOpacity = 0.9
    } else if (status === 'done') {
      emissive = 3.0
      rim = 2.4
      coreOpacity = 1.0
    } else {
      emissive = dimmed ? 0.04 : 0.18
      rim = dimmed ? 0.3 : 0.9
      coreOpacity = dimmed ? 0.12 : 0.35
    }

    if (glassRef.current) {
      (glassRef.current.material as THREE.MeshPhysicalMaterial).emissiveIntensity = emissive
      glassRef.current.position.y = Math.sin(t * 1.0 + id.charCodeAt(0) * 0.5) * 0.08
    }
    if (coreRef.current) {
      (coreRef.current.material as THREE.MeshBasicMaterial).opacity = coreOpacity
      coreRef.current.position.y = Math.sin(t * 1.0 + id.charCodeAt(0) * 0.5) * 0.08
      coreRef.current.rotation.y += 0.01
    }
    rimIntensity.current = rim
  })

  const showCorona = status === 'thinking' || status === 'working'
  const coronaSpeed = status === 'working' ? 1.5 : 0.6

  return (
    <group position={position}>
      {/* Tinted glass shell */}
      <animated.mesh
        ref={glassRef}
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
        <sphereGeometry args={[radius, 48, 48]} />
        <animated.meshPhysicalMaterial
          color={color}
          emissive={color}
          emissiveIntensity={0.18}
          metalness={0.1}
          roughness={0.12}
          clearcoat={1}
          clearcoatRoughness={0.25}
          envMapIntensity={1.6}
          transparent
          opacity={shatterSpring.opacity.to(o => o * 0.32)}
        />
      </animated.mesh>

      {/* Inner energy core — visible through the glass */}
      <mesh ref={coreRef}>
        <icosahedronGeometry args={[radius * 0.4, 1]} />
        <meshBasicMaterial color={color} transparent opacity={0.35} toneMapped={false} wireframe />
      </mesh>

      <FresnelRim radius={radius} color={color} intensityRef={rimIntensity} />

      {showCorona && (
        <CoronaParticles count={12} orbitRadius={radius + 0.3} color={color} speed={coronaSpeed} />
      )}

      <ProgressRing agent={agent} nodeRadius={radius} lastCheckpointIndex={lastCpIdx} />

      <NodeLabel position={[0, -(radius + 0.45), 0]} name={name} role={role}
                 color={color} dimmed={dimmed} />
    </group>
  )
}
