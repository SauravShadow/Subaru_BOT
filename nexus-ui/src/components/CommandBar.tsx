// nexus-ui/src/components/CommandBar.tsx
import { useEffect, useRef, useState } from 'react'
import { useNexusStore, sendWsMessage } from '../store'
import { agentColor } from '../types'
import { useVoice } from '../hooks/useVoice'

export function CommandBar() {
  const agents = useNexusStore(s => s.agents)
  const ceoStatus = useNexusStore(s => s.agents['ceo']?.status ?? 'idle')
  const wsStatus = useNexusStore(s => s.wsStatus)
  const [text, setText] = useState('')
  const [target, setTarget] = useState('ceo')
  const [pickerOpen, setPickerOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const voice = useVoice(target, (t) => {
    sendWsMessage({ type: 'message', agent: target, text: t })
  })

  const send = () => {
    const t = text.trim()
    if (!t || wsStatus !== 'connected') return
    sendWsMessage({ type: 'message', agent: target, text: t })
    setText('')
  }

  // '/' focuses the bar (unless already typing somewhere); Escape blurs.
  // 'nexus-focus-cmdbar' is dispatched by the wake-word hook (Task 14).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/') return
      const el = document.activeElement
      if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) return
      e.preventDefault()
      inputRef.current?.focus()
    }
    const onFocusReq = () => inputRef.current?.focus()
    window.addEventListener('keydown', onKey)
    window.addEventListener('nexus-focus-cmdbar', onFocusReq)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('nexus-focus-cmdbar', onFocusReq)
    }
  }, [])

  const tColor = agentColor(target)
  const busy = ceoStatus === 'thinking' || ceoStatus === 'working'
  const firstName = agents[target]?.name?.split(' ')[0] ?? target

  return (
    <div style={{
      position: 'fixed', bottom: 18, left: '50%', transform: 'translateX(-50%)',
      zIndex: 130, width: 'min(680px, calc(100vw - 360px))',
    }}>
      {/* Agent target picker */}
      {pickerOpen && (
        <div style={{
          position: 'absolute', bottom: 54, left: 0, minWidth: 240,
          background: 'rgba(8, 14, 28, 0.96)', backdropFilter: 'blur(24px)',
          border: '1px solid rgba(0, 240, 255, 0.18)', borderRadius: 10,
          overflow: 'hidden', boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
        }}>
          {Object.entries(agents).map(([id, a]) => (
            <button key={id}
              onClick={() => { setTarget(id); setPickerOpen(false); inputRef.current?.focus() }}
              style={{
                display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                background: id === target ? `${agentColor(id)}14` : 'none',
                border: 'none', padding: '8px 14px', cursor: 'pointer', textAlign: 'left',
              }}>
              <span style={{
                width: 8, height: 8, borderRadius: '50%',
                background: agentColor(id), boxShadow: `0 0 6px ${agentColor(id)}`,
              }} />
              <span style={{ color: '#e2e8f0', fontSize: 12, fontFamily: 'Inter, sans-serif' }}>
                {a.name}
              </span>
              <span style={{ color: '#475569', fontSize: 10, marginLeft: 'auto' }}>{a.role}</span>
            </button>
          ))}
        </div>
      )}

      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px',
        background: 'rgba(8, 14, 28, 0.88)', backdropFilter: 'blur(24px) saturate(1.4)',
        border: `1px solid ${busy ? tColor : 'rgba(0, 240, 255, 0.18)'}`,
        borderRadius: 12, transition: 'border-color 300ms, box-shadow 300ms',
        boxShadow: busy ? `0 0 24px ${tColor}44` : '0 0 18px rgba(0, 240, 255, 0.08)',
        animation: busy ? 'cmdbar-pulse 1.6s ease-in-out infinite' : 'none',
      }}>
        <style>{`@keyframes cmdbar-pulse { 50% { box-shadow: 0 0 36px ${tColor}66 } }`}</style>

        {/* Target chip */}
        <button onClick={() => setPickerOpen(o => !o)} style={{
          background: `${tColor}16`, border: `1px solid ${tColor}55`, color: tColor,
          borderRadius: 8, padding: '5px 12px', fontSize: 10, cursor: 'pointer',
          fontFamily: 'Orbitron, sans-serif', letterSpacing: '0.12em', whiteSpace: 'nowrap',
          textShadow: `0 0 8px ${tColor}88`,
        }}>
          {target === 'ceo' ? 'CEO' : firstName.toUpperCase()} ▾
        </button>

        <input
          ref={inputRef}
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') send()
            if (e.key === 'Escape') inputRef.current?.blur()
          }}
          placeholder={target === 'ceo' ? 'Ask Subaru anything…' : `Message ${firstName}…`}
          style={{
            flex: 1, background: 'transparent', border: 'none', outline: 'none',
            color: '#e2e8f0', fontSize: 14, fontFamily: 'Inter, sans-serif',
          }}
        />

        {voice.hasSpeechRecognition && (
          <button
            onClick={() => voice.isListening ? voice.stopListening() : voice.startListening()}
            title={voice.isListening ? 'Stop recording' : 'Voice input'}
            style={{
              background: voice.isListening ? `${tColor}22` : 'none',
              border: `1px solid ${voice.isListening ? tColor : '#334155'}`,
              color: voice.isListening ? tColor : '#94a3b8',
              borderRadius: 8, padding: '5px 10px', cursor: 'pointer', fontSize: 13,
            }}>
            {voice.isListening ? '◉' : '🎤'}
          </button>
        )}

        <button onClick={send} disabled={wsStatus !== 'connected'} style={{
          background: wsStatus === 'connected' ? `${tColor}1e` : '#1e293b',
          border: `1px solid ${wsStatus === 'connected' ? `${tColor}66` : '#334155'}`,
          color: wsStatus === 'connected' ? tColor : '#475569',
          borderRadius: 8, padding: '5px 14px', fontSize: 11, fontWeight: 700,
          cursor: wsStatus === 'connected' ? 'pointer' : 'default',
          fontFamily: 'Orbitron, sans-serif', letterSpacing: '0.08em',
        }}>
          SEND
        </button>
      </div>
    </div>
  )
}
