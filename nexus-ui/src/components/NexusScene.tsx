// nexus-ui/src/components/NexusScene.tsx
import { useState, useCallback } from 'react'
import { Canvas } from '@react-three/fiber'
import { CameraControls, AdaptiveDpr } from '@react-three/drei'
import { Background } from './Background'
import { CeoNode } from './CeoNode'
import { AgentNode } from './AgentNode'
import { NeuralEdge } from './NeuralEdge'
import { PostProcessing } from './PostProcessing'
import { AgentDetailView } from './AgentDetailView'
import { CommandPalette } from './CommandPalette'
import { SmartIsland } from './SmartIsland'
import { HoverCard } from './HoverCard'
import { ModelPill } from './ModelPill'
import { OpsDrawer } from './OpsDrawer'
import { BrowserViewport } from './BrowserViewport'
import { DesignPreviewPanel } from './DesignPreviewPanel'
import { SystemVitals } from './SystemVitals'
import { useNexusStore } from '../store'
import { AGENT_POSITIONS } from '../types'
import { useCommandPalette } from '../hooks/useCommandPalette'
import { useVoice } from '../hooks/useVoice'

const WORKER_IDS = ['backend', 'frontend', 'qa', 'devops', 'browser'] as const

interface HoverState {
  agentId: string
  x: number
  y: number
}

export function NexusScene() {
  const agents        = useNexusStore(s => s.agents)
  const edges         = useNexusStore(s => s.edges)
  const selectedAgent = useNexusStore(s => s.selectedAgent)
  const pendingApprovals = useNexusStore(s => s.pendingApprovals)

  const [hover, setHover] = useState<HoverState | null>(null)
  const [opsOpen, setOpsOpen] = useState(false)
  const { isSpeaking } = useVoice(null, () => {})

  const palette = useCommandPalette()

  const handleHoverEnter = useCallback((id: string, x: number, y: number) => {
    setHover({ agentId: id, x, y })
  }, [])

  const handleHoverLeave = useCallback(() => {
    setTimeout(() => setHover(null), 300)
  }, [])

  const ceoPos = AGENT_POSITIONS['ceo']!

  return (
    <div style={{ width: '100vw', height: '100vh', position: 'relative' }}>
      {/* HUD layer — always on top of canvas */}
      <ModelPill />
      <SmartIsland />
      <BrowserViewport />
      <DesignPreviewPanel />
      <SystemVitals />

      {/* OPS button — top-left, below ModelPill */}
      <button
        onClick={() => setOpsOpen(o => !o)}
        style={{
          position: 'fixed',
          top: 52,
          left: 16,
          background: opsOpen ? 'rgba(0,240,255,0.15)' : 'rgba(8,14,28,0.85)',
          border: `1px solid ${opsOpen ? '#00f0ff88' : '#1e293b'}`,
          color: opsOpen ? '#00f0ff' : '#64748b',
          borderRadius: 6,
          padding: '4px 10px',
          fontSize: 10,
          fontFamily: 'Orbitron, sans-serif',
          letterSpacing: '0.1em',
          cursor: 'pointer',
          zIndex: 150,
          backdropFilter: 'blur(8px)',
          transition: 'all 150ms',
        }}
      >
        OPS{pendingApprovals > 0 && (
          <span style={{
            marginLeft: 6, background: '#f59e0b', color: '#020408',
            borderRadius: 8, padding: '0 5px', fontSize: 9, fontWeight: 700,
          }}>{pendingApprovals}</span>
        )}
      </button>

      <OpsDrawer open={opsOpen} onClose={() => setOpsOpen(false)} />

      <Canvas
        camera={{ position: [0, 2, 10], fov: 60 }}
        style={{ background: '#020408' }}
        dpr={[1, 1.5]}
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
      >
        <AdaptiveDpr pixelated />
        <Background />

        {/* CEO arc reactor */}
        {agents['ceo'] && (
          <CeoNode
            isSpeaking={isSpeaking}
            onClick={() => {}}
          />
        )}

        {/* Worker nodes + edges */}
        {WORKER_IDS.map(id => {
          const agent = agents[id]
          if (!agent) return null
          const pos = AGENT_POSITIONS[id]!
          const edge = edges.find(e => e.to === id)
          const dimmed = !!selectedAgent && selectedAgent !== id
          return (
            <group key={id}>
              <NeuralEdge
                start={ceoPos}
                end={pos}
                isActive={edge?.isActive ?? false}
                workerId={id}
              />
              <AgentNode
                agent={agent}
                position={pos}
                dimmed={dimmed}
                onHoverEnter={handleHoverEnter}
                onHoverLeave={handleHoverLeave}
              />
            </group>
          )
        })}

        <CameraControls />
        <PostProcessing />
      </Canvas>

      {/* Dark overlay when panel is open — DO NOT use CSS filter on canvas, it kills WebGL */}
      {selectedAgent && (
        <div style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(2, 4, 8, 0.65)',
          backdropFilter: 'blur(4px)',
          zIndex: 90,
          pointerEvents: 'none',
        }} />
      )}

      {/* DOM overlays */}
      {selectedAgent && <AgentDetailView />}

      {hover && !selectedAgent && (
        <HoverCard agentId={hover.agentId} x={hover.x} y={hover.y} />
      )}

      <CommandPalette
        open={palette.open}
        query={palette.query}
        filtered={palette.filtered}
        onQueryChange={palette.setQuery}
        onAction={(id) => palette.runAction(id)}
        onClose={() => palette.setOpen(false)}
      />
    </div>
  )
}
