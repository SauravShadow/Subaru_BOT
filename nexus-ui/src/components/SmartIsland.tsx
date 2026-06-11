import { useNexusStore } from '../store'

const TAB_LABELS = {
  notifications: 'NOTIFS',
  queue: 'QUEUE',
  active: 'ACTIVE',
} as const

export function SmartIsland() {
  const expanded     = useNexusStore(s => s.islandExpanded)
  const tab          = useNexusStore(s => s.islandTab)
  const setExpanded  = useNexusStore(s => s.setIslandExpanded)
  const setTab       = useNexusStore(s => s.setIslandTab)
  const notifications = useNexusStore(s => s.notifications)
  const workQueue    = useNexusStore(s => s.workQueue)
  const agents       = useNexusStore(s => s.agents)

  const activeWorkers = Object.values(agents).filter(a => a.status === 'working' && a.id !== 'ceo')
  const pendingCount = workQueue.filter(q => q.status === 'pending' || q.status === 'active').length

  const chipLabel = [
    activeWorkers.length > 0 && `${activeWorkers.length} active`,
    pendingCount > 0 && `${pendingCount} queued`,
    !activeWorkers.length && !pendingCount && 'Idle',
  ].filter(Boolean).join(' · ')

  const STATUS_COLORS: Record<string, string> = {
    pending:   '#f59e0b',
    active:    '#00f0ff',
    blocked:   '#ef4444',
    completed: '#22c55e',
  }

  return (
    <div style={{
      position: 'fixed',
      bottom: 24,
      right: 24,
      zIndex: 50,
      fontFamily: 'Inter, sans-serif',
    }}>
      {expanded ? (
        <div style={{
          width: 320,
          background: 'rgba(8, 14, 28, 0.92)',
          backdropFilter: 'blur(20px)',
          border: '1px solid rgba(0, 240, 255, 0.12)',
          borderRadius: 10,
          overflow: 'hidden',
          boxShadow: '0 0 30px rgba(0, 240, 255, 0.06)',
          animation: 'islandIn 200ms cubic-bezier(0.16, 1, 0.3, 1)',
        }}>
          <style>{`
            @keyframes islandIn {
              from { opacity: 0; transform: translateY(8px); }
              to   { opacity: 1; transform: translateY(0); }
            }
          `}</style>

          {/* Tabs */}
          <div style={{ display: 'flex', borderBottom: '1px solid #1e293b' }}>
            {(['notifications', 'queue', 'active'] as const).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                style={{
                  flex: 1,
                  background: tab === t ? 'rgba(0, 240, 255, 0.08)' : 'none',
                  border: 'none',
                  borderBottom: tab === t ? '2px solid #00f0ff' : '2px solid transparent',
                  color: tab === t ? '#00f0ff' : '#475569',
                  padding: '10px 0',
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: '0.08em',
                  cursor: 'pointer',
                  fontFamily: 'Orbitron, sans-serif',
                }}
              >
                {TAB_LABELS[t]}
              </button>
            ))}
            <button
              onClick={() => setExpanded(false)}
              style={{
                background: 'none', border: 'none',
                color: '#334155', cursor: 'pointer',
                padding: '10px 12px', fontSize: 12,
              }}
            >
              ×
            </button>
          </div>

          {/* Content */}
          <div style={{ maxHeight: 220, overflowY: 'auto', padding: '8px 0' }}>
            {tab === 'notifications' && (
              notifications.length === 0 ? (
                <div style={{ color: '#334155', fontSize: 12, padding: '12px 14px', fontStyle: 'italic' }}>
                  No notifications yet
                </div>
              ) : notifications.map(n => (
                <div key={n.id} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                  padding: '8px 14px', borderBottom: '1px solid #0d1117', fontSize: 12,
                }}>
                  <span style={{ color: '#e2e8f0', flex: 1 }}>
                    {n.type === 'done' && '✓ '}
                    {n.type === 'delegation' && '⚡ '}
                    {n.type === 'queue' && '📋 '}
                    {n.text}
                  </span>
                  <span style={{ color: '#334155', fontSize: 10, marginLeft: 8, whiteSpace: 'nowrap' }}>
                    {Math.round((Date.now() - n.ts) / 60000)}m ago
                  </span>
                </div>
              ))
            )}

            {tab === 'queue' && (
              workQueue.length === 0 ? (
                <div style={{ color: '#334155', fontSize: 12, padding: '12px 14px', fontStyle: 'italic' }}>
                  No tasks in queue
                </div>
              ) : workQueue.map((item, i) => (
                <div key={item.id} style={{
                  display: 'flex', gap: 8, alignItems: 'center',
                  padding: '8px 14px', borderBottom: '1px solid #0d1117', fontSize: 12,
                }}>
                  <span style={{ color: '#475569', minWidth: 20 }}>[{i + 1}]</span>
                  <span style={{ color: '#e2e8f0', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.task}
                  </span>
                  <span style={{ color: STATUS_COLORS[item.status] ?? '#475569', fontSize: 10, whiteSpace: 'nowrap' }}>
                    {item.status}
                  </span>
                </div>
              ))
            )}

            {tab === 'active' && (
              activeWorkers.length === 0 ? (
                <div style={{ color: '#334155', fontSize: 12, padding: '12px 14px', fontStyle: 'italic' }}>
                  No active workers
                </div>
              ) : activeWorkers.map(a => {
                const lastStep = a.recentSteps[a.recentSteps.length - 1]
                return (
                  <div key={a.id} style={{
                    display: 'flex', gap: 8, alignItems: 'center',
                    padding: '8px 14px', borderBottom: '1px solid #0d1117', fontSize: 12,
                  }}>
                    <span style={{ color: '#00f0ff', minWidth: 80, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {lastStep ? `${lastStep.tool}` : '...'}
                    </span>
                    <span style={{ color: '#94a3b8', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {a.name}
                    </span>
                    <span style={{ color: '#475569', fontSize: 10 }}>
                      {lastStep ? `${Math.round((Date.now() - lastStep.ts) / 1000)}s` : ''}
                    </span>
                  </div>
                )
              })
            )}
          </div>
        </div>
      ) : (
        <button
          onClick={() => setExpanded(true)}
          style={{
            background: 'rgba(8, 14, 28, 0.92)',
            backdropFilter: 'blur(16px)',
            border: '1px solid rgba(0, 240, 255, 0.15)',
            borderRadius: 20,
            color: activeWorkers.length > 0 ? '#00f0ff' : '#475569',
            padding: '6px 14px',
            fontSize: 11,
            cursor: 'pointer',
            fontFamily: 'Inter, sans-serif',
            boxShadow: activeWorkers.length > 0 ? '0 0 12px rgba(0, 240, 255, 0.15)' : 'none',
          }}
        >
          ● {chipLabel}
        </button>
      )}
    </div>
  )
}
