import { useEffect, useRef } from 'react'
import type { PaletteAction } from '../hooks/useCommandPalette'

interface CommandPaletteProps {
  open: boolean
  query: string
  filtered: PaletteAction[]
  onQueryChange: (q: string) => void
  onAction: (id: string) => void
  onClose: () => void
}

export function CommandPalette({ open, query, filtered, onQueryChange, onAction, onClose }: CommandPaletteProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50)
  }, [open])

  if (!open) return null

  // Group actions
  const groups: Record<string, PaletteAction[]> = {}
  for (const action of filtered) {
    if (!groups[action.group]) groups[action.group] = []
    groups[action.group].push(action)
  }

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, zIndex: 190,
          background: 'rgba(2, 4, 8, 0.6)',
          backdropFilter: 'blur(4px)',
        }}
      />

      {/* Panel */}
      <div style={{
        position: 'fixed',
        top: '18%',
        left: '50%',
        transform: 'translateX(-50%)',
        width: 520,
        zIndex: 200,
        background: 'rgba(5, 10, 20, 0.95)',
        backdropFilter: 'blur(32px)',
        border: '1px solid rgba(0, 240, 255, 0.15)',
        borderRadius: 12,
        overflow: 'hidden',
        boxShadow: '0 0 60px rgba(0, 240, 255, 0.08)',
        animation: 'paletteIn 180ms cubic-bezier(0.16, 1, 0.3, 1)',
      }}>
        <style>{`
          @keyframes paletteIn {
            from { opacity: 0; transform: translateX(-50%) translateY(-8px); }
            to   { opacity: 1; transform: translateX(-50%) translateY(0); }
          }
        `}</style>

        {/* Search input */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px', borderBottom: '1px solid #1e293b' }}>
          <span style={{ color: '#475569', fontSize: 14, fontFamily: 'Orbitron, sans-serif' }}>⌘</span>
          <input
            ref={inputRef}
            value={query}
            onChange={e => onQueryChange(e.target.value)}
            placeholder="Search or command..."
            style={{
              flex: 1,
              background: 'none',
              border: 'none',
              outline: 'none',
              color: '#e2e8f0',
              fontSize: 14,
              fontFamily: 'Inter, sans-serif',
            }}
          />
          <span
            onClick={onClose}
            style={{ color: '#475569', fontSize: 11, cursor: 'pointer', padding: '2px 6px', border: '1px solid #334155', borderRadius: 4 }}
          >
            Esc
          </span>
        </div>

        {/* Actions */}
        <div style={{ maxHeight: 360, overflowY: 'auto', padding: '8px 0' }}>
          {Object.entries(groups).map(([group, items]) => (
            <div key={group}>
              <div style={{
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: '0.1em',
                color: '#334155',
                padding: '8px 16px 4px',
                fontFamily: 'Orbitron, sans-serif',
              }}>
                {group}
              </div>
              {items.map(action => (
                <div
                  key={action.id}
                  onClick={() => onAction(action.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    padding: '9px 16px',
                    cursor: 'pointer',
                    color: action.accent ?? '#94a3b8',
                    fontSize: 13,
                    transition: 'background 100ms',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,240,255,0.04)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  {action.accent && (
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: action.accent, flexShrink: 0 }} />
                  )}
                  {action.label}
                </div>
              ))}
            </div>
          ))}
          {filtered.length === 0 && (
            <div style={{ color: '#334155', fontSize: 13, padding: '12px 16px', fontStyle: 'italic' }}>
              No commands found
            </div>
          )}
        </div>
      </div>
    </>
  )
}
