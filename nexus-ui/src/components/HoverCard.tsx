// nexus-ui/src/components/HoverCard.tsx
import { useEffect, useRef } from 'react'
import { useNexusStore } from '../store'
import { AGENT_COLORS } from '../types'

interface HoverCardProps {
  agentId: string
  x: number
  y: number
}

export function HoverCard({ agentId, x, y }: HoverCardProps) {
  const agent = useNexusStore(s => s.agents[agentId])
  const wsModel = useNexusStore(s => s.wsModel)
  const ref = useRef<HTMLDivElement>(null)

  // Keep card on screen
  useEffect(() => {
    if (!ref.current) return
    const el = ref.current
    const rect = el.getBoundingClientRect()
    if (x + rect.width + 16 > window.innerWidth) {
      el.style.left = `${x - rect.width - 8}px`
    }
  })

  if (!agent) return null
  const color = AGENT_COLORS[agentId] ?? '#00f0ff'
  const lastOutput = agent.recentOutput[agent.recentOutput.length - 1] ?? '—'
  const truncated = lastOutput.length > 48 ? lastOutput.slice(0, 48) + '…' : lastOutput

  const modelLabels: Record<string, string> = {
    claude: 'Claude Sonnet',
    gemini: 'Gemini Flash',
    tgpt: 'tgpt',
  }

  return (
    <div
      ref={ref}
      style={{
        position: 'fixed',
        left: x + 16,
        top: y + 8,
        zIndex: 300,
        background: 'rgba(8, 14, 28, 0.95)',
        backdropFilter: 'blur(16px)',
        border: `1px solid ${color}40`,
        boxShadow: `0 0 20px ${color}20`,
        borderRadius: 8,
        padding: '10px 14px',
        minWidth: 200,
        pointerEvents: 'none',
      }}
    >
      <div style={{
        fontFamily: 'Orbitron, sans-serif',
        color,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: '0.08em',
        marginBottom: 6,
      }}>
        {agent.name.toUpperCase()}
        <span style={{ color: '#475569', fontWeight: 400, marginLeft: 8, fontFamily: 'Inter, sans-serif' }}>
          {agent.role}
        </span>
      </div>
      <div style={{ height: 1, background: '#1e293b', marginBottom: 6 }} />
      <div style={{ fontSize: 11, color: '#94a3b8', lineHeight: 1.6 }}>
        <div><span style={{ color: '#475569' }}>Status:</span> {agent.status}</div>
        {agent.stepCount > 0 && (
          <div>
            <span style={{ color: '#475569' }}>Steps:</span> {agent.stepCount}
            {agent.checkpoints.length > 0 && ` · Checkpoints: ${agent.checkpoints.length}`}
          </div>
        )}
        <div><span style={{ color: '#475569' }}>Backend:</span> {modelLabels[wsModel]}</div>
        {agent.recentOutput.length > 0 && (
          <div style={{ color: '#475569', marginTop: 4, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' }}>
            {truncated}
          </div>
        )}
      </div>
    </div>
  )
}
