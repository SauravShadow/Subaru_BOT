// nexus-ui/src/components/HudFrame.tsx
const CYAN = 'rgba(0, 240, 255, 0.35)'

function Corner({ style }: { style: React.CSSProperties }) {
  return <div style={{
    position: 'fixed', width: 26, height: 26, zIndex: 30, pointerEvents: 'none', ...style,
  }} />
}

export function HudFrame() {
  const b = `2px solid ${CYAN}`
  return (
    <>
      <Corner style={{ top: 10, left: 10, borderTop: b, borderLeft: b }} />
      <Corner style={{ top: 10, right: 10, borderTop: b, borderRight: b }} />
      <Corner style={{ bottom: 10, left: 10, borderBottom: b, borderLeft: b }} />
      <Corner style={{ bottom: 10, right: 10, borderBottom: b, borderRight: b }} />
      <div style={{
        position: 'fixed', top: 14, left: '50%', transform: 'translateX(-50%)',
        zIndex: 30, pointerEvents: 'none',
        fontFamily: 'Orbitron, sans-serif', fontSize: 10, letterSpacing: '0.45em',
        color: 'rgba(0, 240, 255, 0.55)',
      }}>
        N E X U S
      </div>
    </>
  )
}
