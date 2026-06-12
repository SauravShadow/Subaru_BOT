// nexus-ui/src/components/BrowserViewport.tsx
import { useNexusStore } from '../store'

const VIOLET = '#8b5cf6'

export function BrowserViewport() {
  const view    = useNexusStore(s => s.browserView)
  const visible = useNexusStore(s => s.browserVisible)
  const setVisible = useNexusStore(s => s.setBrowserVisible)

  if (!view || !visible) return null

  return (
    <div style={{
      position: 'fixed',
      top: 16,
      right: 16,
      width: 380,
      zIndex: 120,
      background: 'rgba(8, 14, 28, 0.92)',
      backdropFilter: 'blur(20px)',
      border: `1px solid ${VIOLET}66`,
      boxShadow: `0 0 32px ${VIOLET}33`,
      borderRadius: 10,
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '8px 12px', borderBottom: `1px solid ${VIOLET}33`,
      }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: VIOLET, boxShadow: `0 0 6px ${VIOLET}` }} />
        <span style={{
          flex: 1, fontFamily: 'Orbitron, sans-serif', fontSize: 10,
          color: VIOLET, letterSpacing: '0.1em',
        }}>
          MAYA — LIVE BROWSER
        </span>
        <button onClick={() => setVisible(false)} style={{
          background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 13,
        }}>✕</button>
      </div>
      <img
        src={`data:${view.mime};base64,${view.image}`}
        alt="browser"
        style={{ width: '100%', display: 'block' }}
      />
      <div style={{
        padding: '6px 12px', fontFamily: 'JetBrains Mono, monospace',
        fontSize: 10, color: '#94a3b8',
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>
        {view.caption ? `${view.caption} · ` : ''}{view.url}
      </div>
    </div>
  )
}
