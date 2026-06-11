// nexus-ui/src/components/NexusScene.tsx
import { Canvas } from '@react-three/fiber'
import { CameraControls } from '@react-three/drei'
import { Background } from './Background'
import { AgentNode } from './AgentNode'
import { NeuralEdge } from './NeuralEdge'
import { AgentDetailView } from './AgentDetailView'
import { useNexusStore } from '../store'
import { AGENT_POSITIONS } from '../types'

const WORKER_IDS = ['backend', 'frontend', 'qa', 'devops', 'browser'] as const

export function NexusScene() {
  const agents = useNexusStore(s => s.agents)
  const edges = useNexusStore(s => s.edges)
  const selectedAgent = useNexusStore(s => s.selectedAgent)
  const wsStatus = useNexusStore(s => s.wsStatus)
  const ceoPos = AGENT_POSITIONS['ceo'] ?? [0, 0.5, 4]

  return (
    <div style={{ width: '100vw', height: '100vh', position: 'relative' }}>
      {/* WS status badge */}
      <div style={{
        position: 'absolute', top: 16, right: 16, zIndex: 10,
        fontSize: 11, color: wsStatus === 'connected' ? '#22c55e' : '#ef4444',
        background: '#0d1117cc', borderRadius: 6, padding: '4px 10px',
        border: `1px solid ${wsStatus === 'connected' ? '#22c55e44' : '#ef444444'}`,
      }}>
        ● {wsStatus === 'connected' ? 'NEXUS ONLINE' : 'OFFLINE'}
      </div>

      <Canvas
        camera={{ position: [0, 2, 10], fov: 60 }}
        style={{ background: '#050a14' }}
        gl={{ antialias: true, alpha: false }}
      >
        <Background />
        <pointLight position={ceoPos} intensity={1.5} color="#00f0ff" />

        {/* CEO node */}
        {agents['ceo'] && (
          <AgentNode
            agent={agents['ceo']}
            position={AGENT_POSITIONS['ceo'] ?? [0, 0.5, 4]}
          />
        )}

        {/* Worker nodes + edges */}
        {WORKER_IDS.map(id => {
          const agent = agents[id]
          if (!agent) return null
          const pos = AGENT_POSITIONS[id] ?? [0, 0, 0]
          const edge = edges.find(e => e.to === id)
          return (
            <group key={id}>
              <NeuralEdge
                start={AGENT_POSITIONS['ceo'] ?? [0, 0.5, 4]}
                end={pos}
                isActive={edge?.isActive ?? false}
              />
              <AgentNode agent={agent} position={pos} />
            </group>
          )
        })}

        <CameraControls />
      </Canvas>

      {/* Detail overlay — rendered outside Canvas */}
      {selectedAgent && <AgentDetailView />}
    </div>
  )
}
