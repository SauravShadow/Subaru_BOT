import React, { useState, useEffect, useRef } from 'react'

interface CallHistory {
  id: string
  direction: string
  number: string
  goal: string
  outcome: string
  summary: string
  started_at: string
}

interface TranscriptTurn {
  speaker: string
  text: string
  timestamp?: string
}

interface ActiveCallState {
  call_id: string
  number: string
  goal: string
  status: string
  transcript: TranscriptTurn[]
  summary?: string
}

const LANGUAGE_OPTIONS = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'Hindi' },
  { value: 'es', label: 'Spanish' },
  { value: 'fr', label: 'French' },
  { value: 'de', label: 'German' },
]

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    prep: '#f59e0b', dialing: '#3b82f6', connected: '#22c55e', ended: '#6b7280'
  }
  return (
    <span
      style={{
        display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
        background: colors[status] ?? '#6b7280', marginRight: 6,
        boxShadow: status === 'connected' ? '0 0 6px #22c55e' : 'none',
      }}
    />
  )
}

export default function CallPanel() {
  const [number, setNumber] = useState('')
  const [goal, setGoal] = useState('')
  const [language, setLanguage] = useState('en')
  const [calling, setCalling] = useState(false)
  const [activeCall, setActiveCall] = useState<ActiveCallState | null>(null)
  const [history, setHistory] = useState<CallHistory[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [transcript, setTranscript] = useState<TranscriptTurn[] | null>(null)
  const [searchQ, setSearchQ] = useState('')
  const [filterDirection, setFilterDirection] = useState('')
  const [filterOutcome, setFilterOutcome] = useState('')
  const transcriptEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchHistory()
  }, [])

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [activeCall?.transcript])

  // Live-poll the active call so status (dialing → connected → ended) and the
  // conversation transcript stream in real time.
  useEffect(() => {
    const id = activeCall?.call_id
    if (!id || activeCall?.status === 'ended') return
    const timer = setInterval(async () => {
      try {
        const r = await fetch(`/api/calls/${id}/live`)
        const d = await r.json()
        setActiveCall(prev => (prev && prev.call_id === id)
          ? { ...prev, status: d.status, transcript: (d.transcript?.length ? d.transcript : prev.transcript) }
          : prev)
        if (d.status === 'ended') fetchHistory()
      } catch { /* transient network error — keep polling */ }
    }, 1500)
    return () => clearInterval(timer)
  }, [activeCall?.call_id, activeCall?.status])

  const fetchHistory = async (q?: string) => {
    try {
      let url = '/api/calls/history?limit=50'
      if (filterDirection) url += `&direction=${filterDirection}`
      if (filterOutcome) url += `&outcome=${filterOutcome}`
      const resp = await fetch(q ? `/api/calls/search?q=${encodeURIComponent(q)}` : url)
      setHistory(await resp.json())
    } catch (e) { console.error('Failed to fetch call history', e) }
  }

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchQ(e.target.value)
    fetchHistory(e.target.value || undefined)
  }

  const handleCall = async () => {
    if (!number.trim() || !goal.trim() || calling) return
    setCalling(true)
    setActiveCall({ call_id: '', number, goal, status: 'prep', transcript: [] })
    try {
      const resp = await fetch('/api/calls/outbound', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ number, goal, language }),
      })
      const data = await resp.json()
      if (data.error) {
        setActiveCall(prev => prev ? { ...prev, status: 'ended', summary: `Error: ${data.error}` } : null)
      } else {
        setActiveCall(prev => prev ? { ...prev, call_id: data.call_id, status: 'dialing' } : null)
      }
    } catch (e) {
      setActiveCall(prev => prev ? { ...prev, status: 'ended', summary: 'Network error' } : null)
    } finally {
      setCalling(false)
    }
  }

  const loadTranscript = async (callId: string) => {
    if (expandedId === callId) {
      setExpandedId(null); setTranscript(null); return
    }
    setExpandedId(callId)
    try {
      const resp = await fetch(`/api/calls/${callId}/transcript`)
      const data = await resp.json()
      setTranscript(data.transcript || [])
    } catch { setTranscript([]) }
  }

  const statusLabel: Record<string, string> = {
    prep: 'Preparing script...', dialing: 'Dialing...', connected: 'Connected', ended: 'Ended'
  }

  return (
    <div style={{ padding: 20, fontFamily: 'monospace', color: '#e2e8f0', maxWidth: 600, margin: '0 auto' }}>
      <h2 style={{ color: '#22c55e', marginBottom: 16, fontSize: 18 }}>📞 Call Panel</h2>

      {/* Outbound call form */}
      <div style={{ background: '#1e293b', borderRadius: 8, padding: 16, marginBottom: 20, border: '1px solid #334155' }}>
        <input
          placeholder="+91 98XXXXXXXX"
          value={number}
          onChange={e => setNumber(e.target.value)}
          style={{ width: '100%', padding: '8px 12px', marginBottom: 8, background: '#0f172a', border: '1px solid #475569', borderRadius: 6, color: '#e2e8f0', fontSize: 14, boxSizing: 'border-box' }}
        />
        <textarea
          placeholder="Goal: e.g. Book a table for 2 at 7pm at Spice Garden"
          value={goal}
          onChange={e => setGoal(e.target.value)}
          rows={2}
          style={{ width: '100%', padding: '8px 12px', marginBottom: 8, background: '#0f172a', border: '1px solid #475569', borderRadius: 6, color: '#e2e8f0', fontSize: 14, resize: 'none', boxSizing: 'border-box' }}
        />
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <select value={language} onChange={e => setLanguage(e.target.value)}
            style={{ flex: 1, padding: '6px 10px', background: '#0f172a', border: '1px solid #475569', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }}>
            {LANGUAGE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <button
          onClick={handleCall}
          disabled={calling || !number.trim() || !goal.trim()}
          style={{ width: '100%', padding: '10px 0', background: calling ? '#374151' : '#22c55e', color: '#000', fontWeight: 700, border: 'none', borderRadius: 6, cursor: calling ? 'not-allowed' : 'pointer', fontSize: 14 }}>
          {calling ? 'Initiating call...' : '📞 Call'}
        </button>
      </div>

      {/* Active call live view */}
      {activeCall && (
        <div style={{ background: '#1e293b', borderRadius: 8, padding: 16, marginBottom: 20, border: '1px solid #22c55e' }}>
          <div style={{ marginBottom: 10, fontSize: 13, color: '#94a3b8' }}>
            <StatusDot status={activeCall.status} />
            <strong style={{ color: '#e2e8f0' }}>{activeCall.number}</strong>
            {' — '}{statusLabel[activeCall.status] ?? activeCall.status}
          </div>
          <div style={{ maxHeight: 220, overflowY: 'auto' }}>
            {activeCall.transcript.map((t, i) => (
              <div key={i} style={{ marginBottom: 6, fontSize: 13 }}>
                <span style={{ color: t.speaker === 'nexus' ? '#22c55e' : '#94a3b8', marginRight: 6 }}>
                  {t.speaker === 'nexus' ? '🤖 NEXUS:' : '🗣 Them:'}
                </span>
                <span style={{ color: '#e2e8f0' }}>{t.text}</span>
              </div>
            ))}
            {activeCall.status === 'ended' && activeCall.summary && (
              <div style={{ marginTop: 10, padding: '8px 10px', background: '#0f172a', borderRadius: 6, fontSize: 12, color: '#94a3b8' }}>
                ✅ {activeCall.summary}
              </div>
            )}
            <div ref={transcriptEndRef} />
          </div>
        </div>
      )}

      {/* Search + filters */}
      <div style={{ marginBottom: 12, display: 'flex', gap: 8 }}>
        <input
          placeholder="🔍 Search calls..."
          value={searchQ}
          onChange={handleSearch}
          style={{ flex: 2, padding: '7px 12px', background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', fontSize: 13 }}
        />
        <select value={filterDirection} onChange={e => { setFilterDirection(e.target.value); fetchHistory() }}
          style={{ flex: 1, padding: '7px 10px', background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', fontSize: 12 }}>
          <option value="">All directions</option>
          <option value="outbound">Outbound</option>
          <option value="inbound">Inbound</option>
        </select>
        <select value={filterOutcome} onChange={e => { setFilterOutcome(e.target.value); fetchHistory() }}
          style={{ flex: 1, padding: '7px 10px', background: '#1e293b', border: '1px solid #334155', borderRadius: 6, color: '#e2e8f0', fontSize: 12 }}>
          <option value="">All outcomes</option>
          <option value="success">Success</option>
          <option value="failed">Failed</option>
        </select>
      </div>

      {/* Call history */}
      <div>
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1 }}>
          Call History
        </div>
        {history.length === 0 && (
          <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 20 }}>No calls yet.</div>
        )}
        {history.map(call => (
          <div key={call.id} style={{ marginBottom: 8 }}>
            <div
              onClick={() => loadTranscript(call.id)}
              style={{ background: '#1e293b', borderRadius: 6, padding: '10px 14px', cursor: 'pointer', border: '1px solid #334155', display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
              <span>{call.outcome === 'success' ? '✅' : '❌'}</span>
              <span style={{ color: '#e2e8f0', minWidth: 130 }}>{call.number}</span>
              <span style={{ color: '#94a3b8', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{call.goal}</span>
              <span style={{ color: '#475569', fontSize: 11 }}>{new Date(call.started_at).toLocaleString()}</span>
            </div>
            {expandedId === call.id && transcript && (
              <div style={{ background: '#0f172a', borderRadius: '0 0 6px 6px', padding: '10px 14px', border: '1px solid #334155', borderTop: 'none' }}>
                {call.summary && <div style={{ color: '#94a3b8', fontSize: 12, marginBottom: 8 }}>📋 {call.summary}</div>}
                {transcript.map((t, i) => (
                  <div key={i} style={{ marginBottom: 5, fontSize: 12 }}>
                    <span style={{ color: t.speaker === 'nexus' ? '#22c55e' : '#60a5fa', marginRight: 6 }}>
                      {t.speaker === 'nexus' ? '🤖 NEXUS:' : '🗣 Them:'}
                    </span>
                    <span style={{ color: '#cbd5e1' }}>{t.text}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
