// nexus-ui/src/components/AgentDetailView.tsx
import { useEffect, useRef, useState, KeyboardEvent } from 'react'
import { useNexusStore, sendWsMessage } from '../store'
import { agentColor } from '../types'
import { NodeFlowPanel } from './NodeFlowPanel'
import { useVoice } from '../hooks/useVoice'

export function AgentDetailView() {
  const selectedId  = useNexusStore(s => s.selectedAgent)
  const selectAgent = useNexusStore(s => s.selectAgent)
  const agent       = useNexusStore(s => selectedId ? s.agents[selectedId] : null)
  const [input, setInput] = useState('')
  const [mounted, setMounted] = useState(false)
  const termRef = useRef<HTMLDivElement>(null)

  const color = agentColor(selectedId ?? '')

  const handleTranscript = (text: string) => {
    if (!agent) return
    sendWsMessage({ type: 'message', agent: agent.id, text })
  }

  const voice = useVoice(selectedId, handleTranscript)

  // Entrance animation
  useEffect(() => {
    const t = setTimeout(() => setMounted(true), 50)
    return () => clearTimeout(t)
  }, [])

  // Hydrate conversation history once, only if the terminal is empty
  useEffect(() => {
    if (!selectedId || !agent || agent.recentOutput.length > 0) return
    fetch(`/api/chat/${selectedId}/history`)
      .then(r => r.json())
      .then((history: Array<{ role: string; content: string }>) => {
        if (!Array.isArray(history) || history.length === 0) return
        const lines = history.slice(-30).map(m =>
          m.role === 'user' ? `> you: ${m.content}` : m.content)
        useNexusStore.setState(s => ({
          agents: {
            ...s.agents,
            [selectedId]: {
              ...s.agents[selectedId],
              recentOutput: s.agents[selectedId].recentOutput.length === 0
                ? lines
                : s.agents[selectedId].recentOutput,
            },
          },
        }))
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  useEffect(() => {
    termRef.current?.scrollTo({ top: termRef.current.scrollHeight, behavior: 'smooth' })
  }, [agent?.recentOutput.length])

  if (!agent) return null

  const placeholder = agent.id === 'ceo'
    ? 'Talk to Subaru...'
    : `Send message to ${agent.name}...`

  const handleSend = () => {
    const text = input.trim()
    if (!text) return
    sendWsMessage({ type: 'message', agent: agent.id, text })
    setInput('')
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleSend()
  }

  const handleMicClick = () => {
    if (voice.isListening) {
      voice.stopListening()
    } else {
      voice.startListening()
    }
  }

  const statusDotColor = agent.status === 'working' ? color
    : agent.status === 'thinking' ? '#7c3aed'
    : agent.status === 'done' ? '#22c55e'
    : '#334155'

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 100,
      opacity: mounted ? 1 : 0,
      transform: mounted ? 'scale(1)' : 'scale(0.92)',
      transition: 'opacity 200ms cubic-bezier(0.16,1,0.3,1), transform 200ms cubic-bezier(0.16,1,0.3,1)',
    }}>
      <div style={{
        width: 560,
        maxHeight: '80vh',
        background: 'rgba(8, 14, 28, 0.82)',
        backdropFilter: 'blur(24px) saturate(1.4)',
        border: `1px solid ${color}59`,
        boxShadow: `0 0 0 1px ${color}1a, 0 0 40px ${color}26, inset 0 1px 0 rgba(255,255,255,0.06)`,
        clipPath: 'polygon(8px 0%, calc(100% - 8px) 0%, 100% 8px, 100% calc(100% - 8px), calc(100% - 8px) 100%, 8px 100%, 0% calc(100% - 8px), 0% 8px)',
        borderRadius: 4,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        padding: '20px 24px',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <button
            onClick={() => { setMounted(false); setTimeout(() => selectAgent(null), 200) }}
            style={{
              background: 'none',
              border: '1px solid #334155',
              color: '#94a3b8',
              borderRadius: 6,
              padding: '4px 10px',
              cursor: 'pointer',
              fontSize: 12,
            }}
          >
            ← Back
          </button>
          <span style={{
            flex: 1,
            fontFamily: 'Orbitron, sans-serif',
            color,
            fontWeight: 700,
            fontSize: 13,
            letterSpacing: '0.1em',
          }}>
            {agent.name.toUpperCase()}
            <span style={{ color: '#475569', fontWeight: 400, fontFamily: 'Inter, sans-serif', letterSpacing: 0, marginLeft: 8 }}>
              • {agent.role}
            </span>
          </span>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: statusDotColor,
            boxShadow: `0 0 6px ${statusDotColor}`,
          }} />
        </div>

        <div style={{ height: 1, background: '#1e293b', marginBottom: 8 }} />

        <NodeFlowPanel agent={agent} />

        {/* Terminal */}
        <div
          ref={termRef}
          style={{
            flex: 1,
            overflowY: 'auto',
            fontFamily: 'JetBrains Mono, monospace',
            fontSize: 12,
            lineHeight: '1.6',
            minHeight: 120,
            maxHeight: 320,
            paddingBottom: 8,
          }}
        >
          {agent.recentOutput.length === 0 ? (
            <div style={{ color: '#334155', fontStyle: 'italic', fontSize: 11 }}>No output yet…</div>
          ) : (
            agent.recentOutput.map((line, i) => {
              if (line.startsWith(' img:')) {
                const rest = line.slice(5)
                const sep = rest.indexOf(':')
                const mime = rest.slice(0, sep)
                const data = rest.slice(sep + 1)
                return (
                  <img
                    key={i}
                    src={`data:${mime};base64,${data}`}
                    alt="generated"
                    style={{ maxWidth: '100%', borderRadius: 6, margin: '6px 0', border: `1px solid ${color}44` }}
                  />
                )
              }
              const isUser = line.startsWith('> you:')
              return (
                <div key={i} style={{
                  color: (line.startsWith('Tool:') || line.startsWith('> Tool:')) ? color
                    : isUser ? '#64748b' : '#e2e8f0',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}>
                  {line}
                </div>
              )
            })
          )}
        </div>

        <div style={{ height: 1, background: '#1e293b', marginTop: 8, marginBottom: 10 }} />

        {/* Input row */}
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            style={{
              flex: 1,
              background: '#0f172a',
              border: '1px solid #334155',
              borderRadius: 6,
              color: '#e2e8f0',
              padding: '8px 12px',
              fontSize: 13,
              outline: 'none',
              fontFamily: 'Inter, sans-serif',
            }}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
          />

          {voice.hasSpeechRecognition && (
            <button
              onClick={handleMicClick}
              title={voice.isListening ? 'Stop recording' : 'Start voice input'}
              style={{
                background: voice.isListening ? `${color}22` : 'none',
                border: `1px solid ${voice.isListening ? color : voice.isSpeaking ? '#f59e0b' : '#334155'}`,
                color: voice.isListening ? color : voice.isSpeaking ? '#f59e0b' : '#94a3b8',
                borderRadius: 6,
                padding: '8px 12px',
                cursor: 'pointer',
                fontSize: 14,
                transition: 'all 150ms',
                boxShadow: voice.isListening ? `0 0 8px ${color}66` : 'none',
              }}
            >
              {voice.isSpeaking ? '🔊' : '🎤'}
            </button>
          )}

          <button
            onClick={handleSend}
            style={{
              background: `${color}22`,
              border: `1px solid ${color}66`,
              color,
              borderRadius: 6,
              padding: '8px 16px',
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}
