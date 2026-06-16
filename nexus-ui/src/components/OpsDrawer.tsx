import { useState, useEffect, useCallback } from 'react'
import { useNexusStore } from '../store'

type OpsTab = 'routines' | 'skills' | 'approvals' | 'email' | 'team'

interface Routine {
  id: string
  name: string
  description: string
  schedule: string
  enabled: boolean
  last_run: string | null
  last_status: string | null
  run_count: number
}

interface SkillEntry {
  id: string
  name?: string
  description?: string
  version?: string
}

interface Approval {
  file_path: string
  agent: string
  diff: string
  created_at?: string
}

interface EmailTask { id: string; subject: string; from: string; status: string; updated: string }
interface AgentInfo { name: string; title: string; description: string }

const ACCENT = '#00f0ff'


function TabButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active ? `${ACCENT}18` : 'none',
        border: 'none',
        borderBottom: active ? `2px solid ${ACCENT}` : '2px solid transparent',
        color: active ? ACCENT : '#64748b',
        padding: '6px 8px',
        fontSize: 10,
        fontFamily: 'Orbitron, sans-serif',
        letterSpacing: '0.05em',
        cursor: 'pointer',
        transition: 'all 150ms',
        flexShrink: 0,
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </button>
  )
}

function StatusBadge({ status }: { status: string | null }) {
  if (!status) return null
  const color = status === 'ok' ? '#22c55e' : status === 'error' ? '#ef4444' : '#f59e0b'
  return (
    <span style={{
      display: 'inline-block',
      padding: '1px 6px',
      borderRadius: 4,
      background: `${color}22`,
      color,
      fontSize: 10,
      border: `1px solid ${color}44`,
    }}>
      {status}
    </span>
  )
}

function DrawerInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const [focused, setFocused] = useState(false)
  return (
    <input
      {...props}
      onFocus={(e) => { setFocused(true); props.onFocus?.(e) }}
      onBlur={(e) => { setFocused(false); props.onBlur?.(e) }}
      style={{
        background: '#0a101e',
        border: `1px solid ${focused ? `${ACCENT}88` : '#1e293b'}`,
        borderRadius: 8,
        color: '#e2e8f0',
        padding: '7px 10px',
        fontSize: 11,
        outline: 'none',
        width: '100%',
        fontFamily: 'Inter, sans-serif',
        transition: 'all 200ms ease',
        boxShadow: focused ? `0 0 10px ${ACCENT}22` : 'none',
        boxSizing: 'border-box',
        ...props.style,
      }}
    />
  )
}

function HireForm({ onHired }: { onHired: () => void }) {
  const [form, setForm] = useState({ id: '', name: '', role: '', stack: '' })
  const hire = async () => {
    if (!form.id || !form.name || !form.role) return
    await fetch('/api/hire', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...form, title: form.role }),
    }).catch(() => null)
    setForm({ id: '', name: '', role: '', stack: '' })
    onHired()
  }
  return (
    <div style={{ background: '#0f172a', border: '1px dashed #334155', borderRadius: 8, padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ fontFamily: 'Orbitron, sans-serif', color: '#64748b', fontSize: 10, letterSpacing: '0.1em' }}>HIRE CONTRACTOR</span>
      <DrawerInput placeholder="id (e.g. data_analyst)" value={form.id} onChange={e => setForm({ ...form, id: e.target.value })} />
      <DrawerInput placeholder="Name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
      <DrawerInput placeholder="Role (e.g. Data Analyst)" value={form.role} onChange={e => setForm({ ...form, role: e.target.value })} />
      <DrawerInput placeholder="Stack (e.g. pandas, SQL)" value={form.stack} onChange={e => setForm({ ...form, stack: e.target.value })} />
      <button onClick={hire} style={{ background: '#22c55e18', border: '1px solid #22c55e44', color: '#22c55e', borderRadius: 5, padding: '4px 0', fontSize: 11, cursor: 'pointer', fontFamily: 'Orbitron, sans-serif' }}>+ HIRE</button>
    </div>
  )
}

export function OpsDrawer({ open, onClose, requestedTab }: {
  open: boolean
  onClose: () => void
  requestedTab?: { tab: OpsTab; ts: number } | null
}) {
  const [tab, setTab] = useState<OpsTab>('routines')

  useEffect(() => {
    if (requestedTab) setTab(requestedTab.tab)
  }, [requestedTab])
  const [routines, setRoutines] = useState<Routine[]>([])
  const [skills, setSkills] = useState<{ tools: SkillEntry[]; learned: SkillEntry[] }>({ tools: [], learned: [] })
  const [approvals, setApprovals] = useState<Record<string, Approval>>({})
  const [emailTasks, setEmailTasks] = useState<EmailTask[]>([])
  const [agents, setAgents] = useState<Record<string, AgentInfo>>({})
  const [loading, setLoading] = useState(false)
  const [runningId, setRunningId] = useState<string | null>(null)
  const [expandedDiffs, setExpandedDiffs] = useState<Record<string, boolean>>({})

  const fetchAll = useCallback(() => {
    if (!open) return
    setLoading(true)
    Promise.all([
      fetch('/api/routines').then(r => r.json()).catch(() => []),
      fetch('/api/skills').then(r => r.json()).catch(() => ({ tools: [], learned: [] })),
      fetch('/api/approvals').then(r => r.json()).catch(() => ({})),
      fetch('/api/email-tasks').then(r => r.json()).catch(() => []),
      fetch('/api/agents').then(r => r.json()).catch(() => ({})),
    ]).then(([r, s, a, e, ag]) => {
      setRoutines(Array.isArray(r) ? r : [])
      setSkills(s && typeof s === 'object' ? s : { tools: [], learned: [] })
      setApprovals(a && typeof a === 'object' ? a : {})
      setEmailTasks(Array.isArray(e) ? e : [])
      setAgents(ag && typeof ag === 'object' ? ag : {})
      useNexusStore.getState().setPendingApprovals(Object.keys(a && typeof a === 'object' ? a : {}).length)
      setLoading(false)
    })
  }, [open])

  useEffect(() => { fetchAll() }, [fetchAll])

  const runRoutine = async (id: string) => {
    setRunningId(id)
    await fetch(`/api/routines/${id}/run`, { method: 'POST' }).catch(() => null)
    setTimeout(() => { setRunningId(null); fetchAll() }, 2000)
  }

  const [newRoutine, setNewRoutine] = useState({ id: '', name: '', agent: 'ceo', schedule: '0 9 * * *', prompt: '' })
  const [logsFor, setLogsFor] = useState<string | null>(null)
  const [logs, setLogs] = useState<Array<{ status: string; output: string; timestamp: string }>>([])

  const createRoutine = async () => {
    if (!newRoutine.id || !newRoutine.name || !newRoutine.prompt) return
    await fetch('/api/routines', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newRoutine),
    }).catch(() => null)
    setNewRoutine({ id: '', name: '', agent: 'ceo', schedule: '0 9 * * *', prompt: '' })
    fetchAll()
  }

  const deleteRoutine = async (id: string) => {
    await fetch(`/api/routines/${id}`, { method: 'DELETE' }).catch(() => null)
    fetchAll()
  }

  const toggleRoutine = async (r: Routine) => {
    await fetch(`/api/routines/${r.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !r.enabled }),
    }).catch(() => null)
    fetchAll()
  }

  const showLogs = async (id: string) => {
    if (logsFor === id) { setLogsFor(null); return }
    const data = await fetch(`/api/routines/${id}/logs?limit=5`).then(r => r.json()).catch(() => [])
    setLogs(Array.isArray(data) ? data : [])
    setLogsFor(id)
  }

  const applyApproval = async (id: string) => {
    await fetch(`/api/approvals/${id}/apply`, { method: 'POST' }).catch(() => null)
    fetchAll()
  }

  const denyApproval = async (id: string) => {
    await fetch(`/api/approvals/${id}/deny`, { method: 'POST' }).catch(() => null)
    fetchAll()
  }

  const approvalEntries = Object.entries(approvals)
  const learnedSkills = skills.learned ?? []

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        bottom: 0,
        width: 360,
        zIndex: 200,
        transform: open ? 'translateX(0)' : 'translateX(-100%)',
        transition: 'transform 260ms cubic-bezier(0.16,1,0.3,1)',
        display: 'flex',
        flexDirection: 'column',
        background: 'rgba(8, 12, 24, 0.96)',
        backdropFilter: 'blur(32px) saturate(1.5)',
        borderRight: `1px solid ${ACCENT}28`,
        boxShadow: `4px 0 40px rgba(0,0,0,0.6), inset -1px 0 0 ${ACCENT}18`,
      }}
    >
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        padding: '16px 20px 12px',
        borderBottom: '1px solid #1e293b',
        gap: 10,
        flexShrink: 0,
      }}>
        <span style={{
          fontFamily: 'Orbitron, sans-serif',
          color: ACCENT,
          fontSize: 13,
          fontWeight: 700,
          letterSpacing: '0.12em',
          flex: 1,
        }}>
          OPS CENTER
        </span>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: '1px solid #334155',
            color: '#64748b',
            borderRadius: 6,
            padding: '3px 8px',
            cursor: 'pointer',
            fontSize: 12,
          }}
        >
          ✕
        </button>
      </div>

      {/* Tabs */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid #1e293b',
        flexShrink: 0,
        overflowX: 'auto',
      }}>
        <TabButton label="ROUTINES" active={tab === 'routines'} onClick={() => setTab('routines')} />
        <TabButton label="SKILLS" active={tab === 'skills'} onClick={() => setTab('skills')} />
        <TabButton label={`APPROVALS${approvalEntries.length > 0 ? ` (${approvalEntries.length})` : ''}`} active={tab === 'approvals'} onClick={() => setTab('approvals')} />
        <TabButton label="EMAIL" active={tab === 'email'} onClick={() => setTab('email')} />
        <TabButton label="TEAM" active={tab === 'team'} onClick={() => setTab('team')} />
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>
        {loading && (
          <div style={{ color: '#475569', fontSize: 12, textAlign: 'center', padding: '32px 0', fontFamily: 'JetBrains Mono, monospace' }}>
            Loading…
          </div>
        )}

        {!loading && tab === 'routines' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ background: '#0f172a', border: '1px dashed #334155', borderRadius: 8, padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontFamily: 'Orbitron, sans-serif', color: '#64748b', fontSize: 10, letterSpacing: '0.1em' }}>NEW ROUTINE</span>
              <DrawerInput placeholder="id (e.g. daily_report)" value={newRoutine.id} onChange={e => setNewRoutine({ ...newRoutine, id: e.target.value })} />
              <DrawerInput placeholder="Name" value={newRoutine.name} onChange={e => setNewRoutine({ ...newRoutine, name: e.target.value })} />
              <DrawerInput placeholder="Cron schedule (e.g. 0 9 * * *)" value={newRoutine.schedule} onChange={e => setNewRoutine({ ...newRoutine, schedule: e.target.value })} />
              <DrawerInput placeholder="Agent (e.g. ceo)" value={newRoutine.agent} onChange={e => setNewRoutine({ ...newRoutine, agent: e.target.value })} />
              <DrawerInput placeholder="Prompt" value={newRoutine.prompt} onChange={e => setNewRoutine({ ...newRoutine, prompt: e.target.value })} />
              <button onClick={createRoutine} style={{
                background: `${ACCENT}18`, border: `1px solid ${ACCENT}44`, color: ACCENT,
                borderRadius: 5, padding: '4px 0', fontSize: 11, cursor: 'pointer', fontFamily: 'Orbitron, sans-serif',
              }}>+ CREATE</button>
            </div>
            {routines.length === 0 && (
              <div style={{ color: '#334155', fontSize: 12, fontStyle: 'italic', padding: '24px 0' }}>
                No routines configured
              </div>
            )}
            {routines.map(r => (
              <div key={r.id} style={{
                background: '#0f172a',
                border: '1px solid #1e293b',
                borderRadius: 8,
                padding: '12px 14px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{
                    fontFamily: 'JetBrains Mono, monospace',
                    color: r.enabled ? '#e2e8f0' : '#475569',
                    fontSize: 12,
                    fontWeight: 600,
                    flex: 1,
                  }}>
                    {r.name}
                  </span>
                  <StatusBadge status={r.last_status} />
                </div>
                {r.description && (
                  <div style={{ color: '#64748b', fontSize: 11, marginBottom: 6 }}>{r.description}</div>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{
                    fontFamily: 'JetBrains Mono, monospace',
                    color: '#475569',
                    fontSize: 10,
                    flex: 1,
                  }}>
                    {r.schedule} · runs {r.run_count}×
                  </span>
                  <button
                    onClick={() => runRoutine(r.id)}
                    disabled={runningId === r.id}
                    style={{
                      background: runningId === r.id ? '#1e293b' : `${ACCENT}18`,
                      border: `1px solid ${ACCENT}44`,
                      color: runningId === r.id ? '#475569' : ACCENT,
                      borderRadius: 5,
                      padding: '3px 10px',
                      fontSize: 10,
                      cursor: runningId === r.id ? 'default' : 'pointer',
                      fontFamily: 'Orbitron, sans-serif',
                      letterSpacing: '0.06em',
                    }}
                  >
                    {runningId === r.id ? 'RUNNING…' : 'RUN'}
                  </button>
                  <button onClick={() => showLogs(r.id)} style={{
                    background: 'none', border: '1px solid #334155', color: '#94a3b8',
                    borderRadius: 5, padding: '3px 8px', fontSize: 10, cursor: 'pointer',
                    fontFamily: 'Orbitron, sans-serif',
                  }}>LOGS</button>
                  <button onClick={() => toggleRoutine(r)} style={{
                    background: 'none',
                    border: `1px solid ${r.enabled ? '#22c55e44' : '#334155'}`,
                    color: r.enabled ? '#22c55e' : '#64748b',
                    borderRadius: 5, padding: '3px 8px', fontSize: 10, cursor: 'pointer',
                    fontFamily: 'Orbitron, sans-serif',
                  }}>{r.enabled ? 'ON' : 'OFF'}</button>
                  <button onClick={() => deleteRoutine(r.id)} style={{
                    background: 'none', border: '1px solid #ef444444', color: '#ef4444',
                    borderRadius: 5, padding: '3px 8px', fontSize: 10, cursor: 'pointer',
                  }}>✕</button>
                </div>
                {r.last_run && (
                  <div style={{ color: '#334155', fontSize: 10, marginTop: 4, fontFamily: 'JetBrains Mono, monospace' }}>
                    Last: {r.last_run.slice(0, 16).replace('T', ' ')}
                  </div>
                )}
                {logsFor === r.id && logs.map((l, i) => (
                  <div key={i} style={{ background: '#020408', border: '1px solid #1e293b', borderRadius: 4, padding: 6, fontSize: 10, color: '#94a3b8', fontFamily: 'JetBrains Mono, monospace', marginTop: 4 }}>
                    <span style={{ color: l.status === 'success' ? '#22c55e' : '#ef4444' }}>{l.status}</span>
                    {' · '}{l.timestamp.slice(0, 16).replace('T', ' ')}
                    <div style={{ whiteSpace: 'pre-wrap', maxHeight: 80, overflowY: 'auto' }}>{l.output.slice(0, 300)}</div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}

        {!loading && tab === 'skills' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {learnedSkills.length === 0 && (
              <div style={{ color: '#334155', fontSize: 12, fontStyle: 'italic', padding: '24px 0' }}>
                No custom skills installed
              </div>
            )}
            {learnedSkills.map(s => (
              <div key={s.id} style={{
                background: '#0f172a',
                border: '1px solid #1e293b',
                borderRadius: 8,
                padding: '12px 14px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                  <span style={{ color: '#e2e8f0', fontSize: 12, fontWeight: 600, flex: 1, fontFamily: 'JetBrains Mono, monospace' }}>
                    {s.name ?? s.id}
                  </span>
                  {s.version && (
                    <span style={{ color: '#475569', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' }}>
                      v{s.version}
                    </span>
                  )}
                </div>
                {s.description && (
                  <div style={{ color: '#64748b', fontSize: 11 }}>{s.description}</div>
                )}
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  <button onClick={async () => { await fetch(`/api/skills/${s.id}/rollback`, { method: 'POST' }).catch(() => null); fetchAll() }}
                    style={{ background: 'none', border: '1px solid #334155', color: '#94a3b8', borderRadius: 5, padding: '2px 8px', fontSize: 10, cursor: 'pointer' }}>
                    ROLLBACK
                  </button>
                  <button onClick={async () => { await fetch(`/api/skills/${s.id}`, { method: 'DELETE' }).catch(() => null); fetchAll() }}
                    style={{ background: 'none', border: '1px solid #ef444444', color: '#ef4444', borderRadius: 5, padding: '2px 8px', fontSize: 10, cursor: 'pointer' }}>
                    DELETE
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && tab === 'email' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <button onClick={async () => { await fetch('/api/email-tasks/poll', { method: 'POST' }).catch(() => null); setTimeout(fetchAll, 2000) }}
              style={{ background: `${ACCENT}18`, border: `1px solid ${ACCENT}44`, color: ACCENT, borderRadius: 5, padding: '4px 10px', fontSize: 10, cursor: 'pointer', fontFamily: 'Orbitron, sans-serif', alignSelf: 'flex-start' }}>
              POLL INBOX NOW
            </button>
            {emailTasks.length === 0 && (
              <div style={{ color: '#334155', fontSize: 12, fontStyle: 'italic', padding: '24px 0' }}>No email tasks yet</div>
            )}
            {emailTasks.map(t => (
              <div key={t.id} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ flex: 1, color: '#e2e8f0', fontSize: 12, fontFamily: 'JetBrains Mono, monospace' }}>{t.subject}</span>
                  <StatusBadge status={t.status === 'done' ? 'ok' : t.status === 'error' ? 'error' : t.status} />
                </div>
                <div style={{ color: '#475569', fontSize: 10, marginTop: 2 }}>{t.from} · {t.updated.slice(0, 16).replace('T', ' ')}</div>
              </div>
            ))}
          </div>
        )}

        {!loading && tab === 'team' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {Object.entries(agents).map(([id, a]) => (
              <div key={id} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ color: '#e2e8f0', fontSize: 12, fontWeight: 600 }}>{a.name}</div>
                  <div style={{ color: '#64748b', fontSize: 10 }}>{a.title}</div>
                </div>
                {!['ceo', 'backend', 'frontend', 'qa', 'devops', 'browser'].includes(id) && (
                  <button onClick={async () => { await fetch(`/api/hire/${id}`, { method: 'DELETE' }).catch(() => null); fetchAll() }}
                    style={{ background: 'none', border: '1px solid #ef444444', color: '#ef4444', borderRadius: 5, padding: '2px 8px', fontSize: 10, cursor: 'pointer' }}>
                    FIRE
                  </button>
                )}
              </div>
            ))}
            <HireForm onHired={fetchAll} />
          </div>
        )}

        {!loading && tab === 'approvals' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {approvalEntries.length === 0 && (
              <div style={{ color: '#334155', fontSize: 12, fontStyle: 'italic', padding: '24px 0' }}>
                No pending approvals
              </div>
            )}
            {approvalEntries.map(([id, a]) => (
              <div key={id} style={{
                background: '#0f172a',
                border: '1px solid #f59e0b44',
                borderRadius: 8,
                padding: '12px 14px',
              }}>
                <div style={{ color: '#f59e0b', fontSize: 11, fontFamily: 'JetBrains Mono, monospace', fontWeight: 600, marginBottom: 4 }}>
                  {a.file_path}
                </div>
                <div style={{ color: '#64748b', fontSize: 11, marginBottom: 8 }}>
                  Requested by <span style={{ color: '#94a3b8' }}>{a.agent}</span>
                </div>
                {a.diff && (
                  <div style={{ position: 'relative', marginBottom: 8 }}>
                    <pre
                      onClick={() => setExpandedDiffs(prev => ({ ...prev, [id]: !prev[id] }))}
                      style={{
                        background: '#020408',
                        border: `1px solid ${expandedDiffs[id] ? '#f59e0b66' : '#1e293b'}`,
                        borderRadius: 4,
                        padding: '8px',
                        fontSize: 10,
                        color: '#94a3b8',
                        fontFamily: 'JetBrains Mono, monospace',
                        overflowX: 'auto',
                        overflowY: 'auto',
                        maxHeight: expandedDiffs[id] ? 500 : 120,
                        whiteSpace: 'pre',
                        cursor: 'pointer',
                        transition: 'max-height 200ms ease, border-color 200ms ease',
                      }}
                    >
                      {expandedDiffs[id] ? a.diff : (a.diff.length > 500 ? `${a.diff.slice(0, 500)}\n\n… (click to expand)` : a.diff)}
                    </pre>
                  </div>
                )}
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    onClick={() => applyApproval(id)}
                    style={{
                      background: '#22c55e18',
                      border: '1px solid #22c55e44',
                      color: '#22c55e',
                      borderRadius: 5,
                      padding: '4px 12px',
                      fontSize: 11,
                      cursor: 'pointer',
                      fontFamily: 'Orbitron, sans-serif',
                      letterSpacing: '0.06em',
                    }}
                  >
                    APPLY
                  </button>
                  <button
                    onClick={() => denyApproval(id)}
                    style={{
                      background: '#ef444418',
                      border: '1px solid #ef444444',
                      color: '#ef4444',
                      borderRadius: 5,
                      padding: '4px 12px',
                      fontSize: 11,
                      cursor: 'pointer',
                      fontFamily: 'Orbitron, sans-serif',
                      letterSpacing: '0.06em',
                    }}
                  >
                    DENY
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}


      </div>

      {/* Footer refresh */}
      <div style={{
        padding: '8px 16px',
        borderTop: '1px solid #1e293b',
        display: 'flex',
        justifyContent: 'flex-end',
        flexShrink: 0,
      }}>
        <button
          onClick={fetchAll}
          style={{
            background: 'none',
            border: '1px solid #334155',
            color: '#475569',
            borderRadius: 5,
            padding: '3px 10px',
            fontSize: 10,
            cursor: 'pointer',
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          ↻ refresh
        </button>
      </div>
    </div>
  )
}
