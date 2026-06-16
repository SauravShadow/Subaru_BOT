// nexus-ui/src/components/CallWindow.tsx
// Floating call panel — opens from the CommandBar 📞 button or auto-detects
// any active call (started by an agent or from another tab).
// Styled like BrowserViewport: fixed top-right glassmorphism panel.

import { useState, useEffect, useRef } from 'react'
import { useNexusStore } from '../store'
import type { ActiveCall } from '../types'

const GREEN  = '#22c55e'
const BLUE   = '#3b82f6'
const AMBER  = '#f59e0b'
const MUTED  = '#475569'
const BG     = 'rgba(8, 14, 28, 0.95)'

const LANG_OPTIONS = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'Hindi' },
  { value: 'es', label: 'Spanish' },
  { value: 'fr', label: 'French' },
  { value: 'de', label: 'German' },
]

function StatusDot({ status }: { status: string }) {
  const color = status === 'connected' ? GREEN : status === 'dialing' ? BLUE : status === 'prep' ? AMBER : MUTED
  return (
    <span style={{
      display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
      background: color, marginRight: 6, flexShrink: 0,
      boxShadow: status === 'connected' ? `0 0 8px ${GREEN}` : 'none',
    }} />
  )
}

export function CallWindow() {
  const visible          = useNexusStore(s => s.callWindowVisible)
  const setVisible       = useNexusStore(s => s.setCallWindowVisible)
  const activeCall       = useNexusStore(s => s.activeCall)
  const setActiveCall    = useNexusStore(s => s.setActiveCall)
  const browserVisible   = useNexusStore(s => s.browserVisible)

  const [minimised, setMinimised]   = useState(false)
  const [number, setNumber]         = useState('')
  const [goal, setGoal]             = useState('')
  const [language, setLanguage]     = useState('en')
  const [calling, setCalling]       = useState(false)
  
  // Validation state
  const [numberTouched, setNumberTouched] = useState(false)
  
  const bottomRef = useRef<HTMLDivElement>(null)

  // Validation regex for standard/international phone numbers
  const phoneRegex = /^\+?[0-9\s\-()]{7,20}$/
  const isNumberValid = !number.trim() || phoneRegex.test(number)

  // Auto-scroll transcript
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [activeCall?.transcript])

  // Auto-detect any active call from the backend (agent-initiated, CLI, etc.)
  useEffect(() => {
    const poll = setInterval(async () => {
      try {
        const r = await fetch('/api/calls/active')
        const list: ActiveCall[] = await r.json()
        if (!list.length) return
        const first = list[0]
        const current = useNexusStore.getState().activeCall
        if (current && current.call_id === first.call_id) return
        if (!current || current.status === 'ended') {
          setVisible(true)  // auto-show window when a call appears
          setMinimised(false)
          setActiveCall({ ...first, transcript: [] })
        }
      } catch { /* ignore */ }
    }, 3000)
    return () => clearInterval(poll)
  }, [setVisible, setActiveCall])

  // Live-poll the active call for status + transcript
  useEffect(() => {
    const id = activeCall?.call_id
    if (!id || activeCall?.status === 'ended') return
    const poll = setInterval(async () => {
      try {
        const r = await fetch(`/api/calls/${id}/live`)
        const d = await r.json()
        const current = useNexusStore.getState().activeCall
        if (!current || current.call_id !== id) return
        setActiveCall({
          ...current,
          status: d.status,
          transcript: d.transcript?.length ? d.transcript : current.transcript,
          summary: d.summary ?? current.summary,
        })
      } catch { /* ignore */ }
    }, 1500)
    return () => clearInterval(poll)
  }, [activeCall?.call_id, activeCall?.status, setActiveCall])

  const handleCall = async () => {
    if (!number.trim() || !goal.trim() || !phoneRegex.test(number) || calling) return
    setCalling(true)
    setActiveCall({ call_id: '', number, goal, status: 'prep', transcript: [] })
    setMinimised(false)
    try {
      const r = await fetch('/api/calls/outbound', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ number, goal, language }),
      })
      const d = await r.json()
      if (d.error) {
        setActiveCall(prev => prev ? { ...prev, status: 'ended', summary: `Error: ${d.error}` } : null)
      } else {
        setActiveCall(prev => prev ? { ...prev, call_id: d.call_id, status: 'dialing' } : null)
      }
    } catch {
      setActiveCall(prev => prev ? { ...prev, status: 'ended', summary: 'Network error' } : null)
    } finally {
      setCalling(false)
    }
  }

  const dismiss = () => {
    setVisible(false)
    setActiveCall(null)
  }

  if (!visible) return null

  const accentColor = activeCall?.status === 'connected' ? GREEN
    : activeCall?.status === 'dialing'   ? BLUE
    : activeCall?.status === 'prep'      ? AMBER
    : GREEN

  const statusLabel: Record<string, string> = {
    prep: 'Preparing script…', dialing: 'Dialing…', connected: 'Connected', ended: 'Call ended',
  }

  const showForm = !activeCall || activeCall.status === 'ended'
  
  // Disable button if form incomplete or phone number invalid
  const dialDisabled = calling || !number.trim() || !goal.trim() || !phoneRegex.test(number)

  return (
    <div style={{
      position: 'fixed',
      top: 16,
      right: browserVisible ? 412 : 16,
      width: 420,
      zIndex: 120,
      background: BG,
      backdropFilter: 'blur(28px) saturate(1.6)',
      border: `1px solid ${accentColor}55`,
      boxShadow: activeCall?.status === 'connected'
        ? `0 0 40px ${GREEN}22, 0 8px 32px rgba(0,0,0,0.7)`
        : '0 8px 32px rgba(0,0,0,0.7)',
      borderRadius: 12,
      overflow: 'hidden',
      transition: 'border-color 400ms, box-shadow 400ms, right 300ms cubic-bezier(0.16, 1, 0.3, 1)',
    }}>

      {/* ── Header bar ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '9px 14px',
        borderBottom: minimised ? 'none' : `1px solid ${accentColor}33`,
        background: `${accentColor}0a`,
      }}>
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          background: accentColor,
          boxShadow: `0 0 8px ${accentColor}`,
          flexShrink: 0,
        }} />
        <span style={{
          flex: 1, fontFamily: 'Orbitron, sans-serif', fontSize: 10,
          color: accentColor, letterSpacing: '0.1em',
        }}>
          {activeCall && activeCall.status !== 'ended'
            ? `NEXUS — ${statusLabel[activeCall.status] ?? activeCall.status}`
            : 'NEXUS — CALL PANEL'}
        </span>
        {/* Minimise */}
        <button
          onClick={() => setMinimised(m => !m)}
          title={minimised ? 'Expand' : 'Minimise'}
          style={{ background: 'none', border: 'none', color: MUTED, cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: '0 4px' }}
        >
          {minimised ? '□' : '−'}
        </button>
        {/* Close */}
        <button
          onClick={dismiss}
          title="Close"
          style={{ background: 'none', border: 'none', color: MUTED, cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: '0 4px' }}
        >
          ✕
        </button>
      </div>

      {/* ── Body (hidden when minimised) ── */}
      {!minimised && (
        <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>

          {/* Active call status + transcript */}
          {activeCall && (
            <div>
              {/* Status row */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, fontSize: 12 }}>
                <StatusDot status={activeCall.status} />
                <strong style={{ color: '#e2e8f0' }}>{activeCall.number}</strong>
                <span style={{ color: '#64748b', marginLeft: 4 }}>{statusLabel[activeCall.status] ?? activeCall.status}</span>
                {activeCall.status !== 'ended' && (
                  <span style={{
                    marginLeft: 'auto', fontSize: 10, background: '#0f172a',
                    color: '#475569', padding: '1px 6px', borderRadius: 4,
                    border: '1px solid #334155',
                  }}>LIVE</span>
                )}
              </div>

              {/* Goal */}
              {activeCall.goal && (
                <div style={{
                  fontSize: 11, color: '#64748b', fontStyle: 'italic',
                  marginBottom: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  🎯 {activeCall.goal}
                </div>
              )}

              {/* Transcript */}
              <div style={{
                maxHeight: 260, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6,
                paddingRight: 4,
              }}>
                {activeCall.transcript.length === 0 && activeCall.status !== 'ended' && (
                  <div style={{ color: '#334155', fontSize: 12, fontStyle: 'italic', padding: '8px 0' }}>
                    ⏳ Waiting for conversation to start…
                  </div>
                )}
                {activeCall.transcript.map((t, i) => (
                  <div key={i} style={{
                    display: 'flex', gap: 8, fontSize: 12,
                    alignItems: 'flex-start',
                  }}>
                    <span style={{
                      color: t.speaker === 'nexus' ? GREEN : '#60a5fa',
                      fontFamily: 'Orbitron, sans-serif', fontSize: 9,
                      letterSpacing: '0.06em', flexShrink: 0, paddingTop: 2,
                    }}>
                      {t.speaker === 'nexus' ? 'NEXUS' : 'THEM'}
                    </span>
                    <span style={{ color: '#cbd5e1', lineHeight: 1.5 }}>{t.text}</span>
                  </div>
                ))}

                {/* Summary on end */}
                {activeCall.status === 'ended' && activeCall.summary && (
                  <div style={{
                    marginTop: 8, padding: '8px 12px', background: '#0f172a',
                    borderRadius: 8, fontSize: 12, color: '#94a3b8',
                    border: '1px solid #1e293b',
                  }}>
                    ✅ {activeCall.summary}
                  </div>
                )}
                <div ref={bottomRef} />
              </div>

              {/* End / New call buttons */}
              {activeCall.status === 'ended' && (
                <button
                  onClick={() => setActiveCall(null)}
                  style={{
                    marginTop: 12, width: '100%', padding: '8px 0',
                    background: '#1e293b', border: '1px solid #334155',
                    color: '#94a3b8', borderRadius: 8, cursor: 'pointer', fontSize: 12,
                    fontFamily: 'Orbitron, sans-serif', letterSpacing: '0.06em',
                  }}
                >
                  + NEW CALL
                </button>
              )}
            </div>
          )}

          {/* Dial form — shown when no active call */}
          {showForm && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div>
                <input
                  placeholder="+91 98XXXXXXXX"
                  value={number}
                  onChange={e => setNumber(e.target.value)}
                  style={{
                    width: '100%', padding: '9px 12px', background: '#0f172a',
                    border: `1px solid ${!isNumberValid && numberTouched ? '#ef4444' : '#334155'}`, 
                    borderRadius: 8, color: '#e2e8f0',
                    fontSize: 13, outline: 'none', boxSizing: 'border-box',
                    fontFamily: 'JetBrains Mono, monospace',
                    transition: 'border-color 150ms',
                  }}
                  onFocus={e => { e.target.style.borderColor = !isNumberValid && numberTouched ? '#ef4444' : GREEN + '88' }}
                  onBlur={e => { setNumberTouched(true); e.target.style.borderColor = !isNumberValid && numberTouched ? '#ef4444' : '#334155' }}
                />
                {!isNumberValid && numberTouched && (
                  <div style={{ color: '#ef4444', fontSize: 10, marginTop: 4, marginLeft: 2 }}>
                    ⚠ Enter valid format (e.g. +1234567890)
                  </div>
                )}
              </div>
              <textarea
                placeholder="Goal: e.g. Book a table for 2 at 7pm at Spice Garden"
                value={goal}
                onChange={e => setGoal(e.target.value)}
                rows={2}
                style={{
                  width: '100%', padding: '9px 12px', background: '#0f172a',
                  border: '1px solid #334155', borderRadius: 8, color: '#e2e8f0',
                  fontSize: 13, outline: 'none', resize: 'none', boxSizing: 'border-box',
                  fontFamily: 'Inter, sans-serif',
                  transition: 'border-color 150ms',
                }}
                onFocus={e => { e.target.style.borderColor = GREEN + '88' }}
                onBlur={e => { e.target.style.borderColor = '#334155' }}
              />
              <div style={{ display: 'flex', gap: 8 }}>
                <select
                  value={language}
                  onChange={e => setLanguage(e.target.value)}
                  style={{
                    flex: 1, padding: '7px 10px', background: '#0f172a',
                    border: '1px solid #334155', borderRadius: 8, color: '#e2e8f0',
                    fontSize: 12, cursor: 'pointer',
                  }}
                >
                  {LANG_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                <button
                  onClick={handleCall}
                  disabled={dialDisabled}
                  style={{
                    flex: 2, padding: '8px 0',
                    background: dialDisabled ? '#1e293b' : GREEN,
                    color: dialDisabled ? '#475569' : '#000',
                    fontWeight: 700, border: 'none', borderRadius: 8,
                    cursor: dialDisabled ? 'not-allowed' : 'pointer',
                    fontSize: 13, fontFamily: 'Orbitron, sans-serif', letterSpacing: '0.06em',
                    transition: 'background 200ms',
                  }}
                >
                  {calling ? 'INITIATING…' : '📞 CALL'}
                </button>
              </div>
            </div>
          )}

        </div>
      )}
    </div>
  )
}
