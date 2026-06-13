// nexus-ui/src/components/BootOverlay.tsx
import { useEffect, useState } from 'react'
import { useNexusStore } from '../store'

const LINES = [
  'NEXUS NEURAL COMMAND CENTER v2',
  'INITIALIZING ARC REACTOR .......... OK',
  'LOADING AGENT ROSTER .............. OK',
  'ESTABLISHING UPLINK ...............',
]

export function BootOverlay() {
  const wsStatus = useNexusStore(s => s.wsStatus)
  const [shown, setShown] = useState(() => sessionStorage.getItem('nexus-booted') !== '1')
  const [lineCount, setLineCount] = useState(0)
  const [fading, setFading] = useState(false)

  // Typewriter: reveal one line every 350ms
  useEffect(() => {
    if (!shown || lineCount >= LINES.length) return
    const t = setTimeout(() => setLineCount(c => c + 1), 350)
    return () => clearTimeout(t)
  }, [shown, lineCount])

  // When all lines shown AND ws connected → flash final line, fade out
  useEffect(() => {
    if (!shown || fading) return
    if (lineCount >= LINES.length && wsStatus === 'connected') {
      setFading(true)
      sessionStorage.setItem('nexus-booted', '1')
      setTimeout(() => setShown(false), 900)
    }
  }, [shown, fading, lineCount, wsStatus])

  return (
    <>
      {shown && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 300,
          background: '#020408',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          opacity: fading ? 0 : 1,
          transition: 'opacity 800ms ease',
          pointerEvents: fading ? 'none' : 'auto',
        }}>
          <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 13, color: '#00f0ff', lineHeight: 2 }}>
            {LINES.slice(0, lineCount).map((l, i) => <div key={i}>{l}</div>)}
            {lineCount >= LINES.length && wsStatus === 'connected' && (
              <div style={{ color: '#f59e0b', fontFamily: 'Orbitron, sans-serif', marginTop: 8, letterSpacing: '0.2em' }}>
                ALL SYSTEMS NOMINAL
              </div>
            )}
          </div>
        </div>
      )}

      {/* Offline banner — visible whenever WS drops after boot */}
      {!shown && wsStatus === 'offline' && (
        <div style={{
          position: 'fixed', top: 16, left: '50%', transform: 'translateX(-50%)',
          zIndex: 250, padding: '5px 16px',
          background: 'rgba(40, 8, 8, 0.9)', border: '1px solid #ef4444',
          borderRadius: 6, color: '#ef4444',
          fontFamily: 'Orbitron, sans-serif', fontSize: 10, letterSpacing: '0.15em',
          animation: 'nexus-blink 1.2s ease-in-out infinite',
        }}>
          UPLINK LOST — RECONNECTING
          <style>{'@keyframes nexus-blink { 50% { opacity: 0.4 } }'}</style>
        </div>
      )}
    </>
  )
}
