import { useNexusStore } from '../store'

const MODEL_LABELS: Record<string, string> = {
  claude: 'Claude Sonnet',
  gemini: 'Gemini Flash',
  tgpt:   'tgpt',
}

const MODEL_COLORS: Record<string, string> = {
  claude: '#f59e0b',
  gemini: '#3b82f6',
  tgpt:   '#475569',
}

export function ModelPill() {
  const wsModel = useNexusStore(s => s.wsModel)
  const wsStatus = useNexusStore(s => s.wsStatus)
  const color = MODEL_COLORS[wsModel] ?? '#475569'

  return (
    <div style={{
      position: 'fixed',
      top: 16,
      left: 16,
      zIndex: 10,
      display: 'flex',
      gap: 12,
      alignItems: 'center',
    }}>
      <div style={{
        fontFamily: 'Orbitron, sans-serif',
        fontSize: 11,
        color,
        background: 'rgba(5, 10, 20, 0.85)',
        border: `1px solid ${color}44`,
        borderRadius: 6,
        padding: '4px 10px',
        letterSpacing: '0.06em',
      }}>
        ⚡ {MODEL_LABELS[wsModel] ?? wsModel}
      </div>
      <div style={{
        fontSize: 11,
        color: wsStatus === 'connected' ? '#22c55e' : '#ef4444',
        background: 'rgba(5, 10, 20, 0.85)',
        border: `1px solid ${wsStatus === 'connected' ? '#22c55e44' : '#ef444444'}`,
        borderRadius: 6,
        padding: '4px 10px',
        fontFamily: 'Orbitron, sans-serif',
        letterSpacing: '0.06em',
      }}>
        ● {wsStatus === 'connected' ? 'NEXUS ONLINE' : 'OFFLINE'}
      </div>
    </div>
  )
}
