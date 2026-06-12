// nexus-ui/src/components/SystemVitals.tsx
import { useEffect, useState } from 'react'

interface Health { app: boolean; bark: boolean; browser: boolean; email: boolean }
interface Storage { used_gb: number; max_gb: number; percent: number }

function Dot({ ok, label }: { ok: boolean; label: string }) {
  const c = ok ? '#22c55e' : '#ef4444'
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginRight: 10 }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: c, boxShadow: `0 0 5px ${c}` }} />
      <span style={{ color: '#64748b', fontSize: 9 }}>{label}</span>
    </span>
  )
}

export function SystemVitals() {
  const [health, setHealth] = useState<Health | null>(null)
  const [storage, setStorage] = useState<Storage | null>(null)

  useEffect(() => {
    const load = () => {
      fetch('/api/health').then(r => r.json()).then(setHealth).catch(() => setHealth(null))
      fetch('/api/storage').then(r => r.json()).then(setStorage).catch(() => {})
    }
    load()
    const id = setInterval(load, 60_000)
    return () => clearInterval(id)
  }, [])

  return (
    <div style={{
      position: 'fixed', bottom: 16, left: '50%', transform: 'translateX(-50%)',
      zIndex: 40, padding: '6px 14px',
      background: 'rgba(8, 14, 28, 0.85)', backdropFilter: 'blur(12px)',
      border: '1px solid rgba(0, 240, 255, 0.12)', borderRadius: 8,
      fontFamily: 'JetBrains Mono, monospace', whiteSpace: 'nowrap',
    }}>
      <Dot ok={!!health?.app} label="CORE" />
      <Dot ok={!!health?.bark} label="VOICE" />
      <Dot ok={!!health?.browser} label="BROWSER" />
      <Dot ok={!!health?.email} label="EMAIL" />
      {storage && (
        <span style={{ color: storage.percent > 85 ? '#ef4444' : '#64748b', fontSize: 9 }}>
          DISK {storage.percent}%
        </span>
      )}
    </div>
  )
}
