// nexus-ui/src/components/DesignPreviewPanel.tsx
import { useNexusStore } from '../store'

const PINK = '#ec4899'

export function DesignPreviewPanel() {
  const ts      = useNexusStore(s => s.designPreviewTs)
  const visible = useNexusStore(s => s.designPreviewVisible)
  const setVisible = useNexusStore(s => s.setDesignPreviewVisible)

  if (!ts || !visible) return null

  return (
    <div style={{
      position: 'fixed',
      bottom: 16,
      left: 16,
      width: 420,
      height: 320,
      zIndex: 120,
      background: 'rgba(8, 14, 28, 0.92)',
      backdropFilter: 'blur(20px)',
      border: `1px solid ${PINK}66`,
      boxShadow: `0 0 32px ${PINK}26`,
      borderRadius: 10,
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '8px 12px', borderBottom: `1px solid ${PINK}33`,
      }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: PINK, boxShadow: `0 0 6px ${PINK}` }} />
        <span style={{ flex: 1, fontFamily: 'Orbitron, sans-serif', fontSize: 10, color: PINK, letterSpacing: '0.1em' }}>
          EMILIA — DESIGN PREVIEW
        </span>
        <a href={`/static/previews/index.html?t=${ts}`} target="_blank" rel="noreferrer"
           style={{ color: '#64748b', fontSize: 10, textDecoration: 'none', marginRight: 8 }}>
          open ↗
        </a>
        <button onClick={() => setVisible(false)} style={{
          background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 13,
        }}>✕</button>
      </div>
      <iframe
        key={ts}
        src={`/static/previews/index.html?t=${ts}`}
        title="design preview"
        sandbox="allow-scripts"
        style={{ flex: 1, border: 'none', background: '#fff' }}
      />
    </div>
  )
}
