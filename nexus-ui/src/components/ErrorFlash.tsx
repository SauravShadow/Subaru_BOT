// nexus-ui/src/components/ErrorFlash.tsx
import { useEffect, useState } from 'react'
import { useNexusStore } from '../store'

/** Brief red radial wash over the scene whenever an error event arrives. */
export function ErrorFlash() {
  const lastErrorTs = useNexusStore(s => s.lastErrorTs)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!lastErrorTs) return
    setVisible(true)
    const t = setTimeout(() => setVisible(false), 700)
    return () => clearTimeout(t)
  }, [lastErrorTs])

  if (!visible) return null
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 25, pointerEvents: 'none',
      background: 'radial-gradient(ellipse at center, transparent 40%, rgba(239,68,68,0.18) 100%)',
      animation: 'nexus-errorflash 700ms ease-out forwards',
    }}>
      <style>{'@keyframes nexus-errorflash { from { opacity: 1 } to { opacity: 0 } }'}</style>
    </div>
  )
}
