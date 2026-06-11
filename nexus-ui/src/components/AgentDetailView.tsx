// nexus-ui/src/components/AgentDetailView.tsx
import { useEffect, useRef, useState, KeyboardEvent } from 'react'
import { useNexusStore, sendWsMessage } from '../store'
import { NodeFlowPanel } from './NodeFlowPanel'

export function AgentDetailView() {
  const selectedId = useNexusStore(s => s.selectedAgent)
  const selectAgent = useNexusStore(s => s.selectAgent)
  const agent = useNexusStore(s => selectedId ? s.agents[selectedId] : null)
  const [input, setInput] = useState('')
  const termRef = useRef<HTMLDivElement>(null)

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

  return (
    <div style={styles.overlay}>
      <div style={styles.panel}>
        <div style={styles.header}>
          <button style={styles.backBtn} onClick={() => selectAgent(null)}>← Back</button>
          <span style={styles.agentTitle}>
            {agent.name.toUpperCase()} <span style={styles.roleBadge}>• {agent.role}</span>
          </span>
          <span style={styles.statusDot(agent.status)} />
        </div>

        <div style={styles.divider} />

        <NodeFlowPanel agent={agent} />

        <div ref={termRef} style={styles.terminal}>
          {agent.recentOutput.length === 0 ? (
            <div style={styles.emptyLog}>No output yet…</div>
          ) : (
            agent.recentOutput.map((line, i) => (
              <div key={i} style={styles.logLine(line)}>{line}</div>
            ))
          )}
        </div>

        <div style={styles.divider} />

        <div style={styles.inputRow}>
          <input
            style={styles.input}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
          />
          <button style={styles.sendBtn} onClick={handleSend}>Send</button>
        </div>
      </div>
    </div>
  )
}

const styles = {
  overlay: {
    position: 'fixed' as const,
    inset: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'rgba(5, 10, 20, 0.85)',
    backdropFilter: 'blur(4px)',
    zIndex: 100,
  } satisfies React.CSSProperties,
  panel: {
    width: 540,
    maxHeight: '80vh',
    background: '#0d1117',
    border: '1px solid #1e293b',
    borderRadius: 12,
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
    padding: '16px 20px',
    gap: 0,
  } satisfies React.CSSProperties,
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginBottom: 8,
  } satisfies React.CSSProperties,
  backBtn: {
    background: 'none',
    border: '1px solid #334155',
    color: '#94a3b8',
    borderRadius: 6,
    padding: '4px 10px',
    cursor: 'pointer',
    fontSize: 12,
  } satisfies React.CSSProperties,
  agentTitle: {
    flex: 1,
    color: '#e2e8f0',
    fontWeight: 700,
    fontSize: 14,
    letterSpacing: '0.08em',
  } satisfies React.CSSProperties,
  roleBadge: {
    color: '#475569',
    fontWeight: 400,
  } satisfies React.CSSProperties,
  statusDot: (status: string): React.CSSProperties => ({
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: status === 'working' ? '#00f0ff' : status === 'thinking' ? '#7c3aed' : status === 'done' ? '#22c55e' : '#334155',
  }),
  divider: {
    height: 1,
    background: '#1e293b',
    marginBottom: 10,
    marginTop: 4,
  } satisfies React.CSSProperties,
  terminal: {
    flex: 1,
    overflowY: 'auto' as const,
    fontFamily: 'monospace',
    fontSize: 12,
    lineHeight: '1.6',
    minHeight: 120,
    maxHeight: 320,
    paddingBottom: 8,
  } satisfies React.CSSProperties,
  emptyLog: {
    color: '#334155',
    fontStyle: 'italic',
    fontSize: 11,
  } satisfies React.CSSProperties,
  logLine: (line: string): React.CSSProperties => ({
    color: (line.startsWith('Tool:') || line.startsWith('> Tool:')) ? '#00f0ff' : '#e2e8f0',
    whiteSpace: 'pre-wrap' as const,
    wordBreak: 'break-word' as const,
  }),
  inputRow: {
    display: 'flex',
    gap: 8,
    marginTop: 10,
  } satisfies React.CSSProperties,
  input: {
    flex: 1,
    background: '#0f172a',
    border: '1px solid #334155',
    borderRadius: 6,
    color: '#e2e8f0',
    padding: '8px 12px',
    fontSize: 13,
    outline: 'none',
  } satisfies React.CSSProperties,
  sendBtn: {
    background: '#00f0ff22',
    border: '1px solid #00f0ff66',
    color: '#00f0ff',
    borderRadius: 6,
    padding: '8px 16px',
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 600,
  } satisfies React.CSSProperties,
}
