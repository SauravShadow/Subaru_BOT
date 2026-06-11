// nexus-ui/src/components/NodeFlowPanel.tsx
import { useEffect, useRef } from 'react'
import type { AgentState, Step, Checkpoint } from '../types'
import { TOOL_ICONS, AGENT_COLORS } from '../types'

interface NodeFlowPanelProps {
  agent: AgentState
}

type TimelineItem =
  | { kind: 'step'; data: Step }
  | { kind: 'checkpoint'; data: Checkpoint }

function buildTimeline(steps: Step[], checkpoints: Checkpoint[]): TimelineItem[] {
  const items: TimelineItem[] = []
  let cpIdx = 0
  for (const step of steps) {
    while (cpIdx < checkpoints.length && checkpoints[cpIdx].step <= step.step) {
      items.push({ kind: 'checkpoint', data: checkpoints[cpIdx] })
      cpIdx++
    }
    items.push({ kind: 'step', data: step })
  }
  while (cpIdx < checkpoints.length) {
    items.push({ kind: 'checkpoint', data: checkpoints[cpIdx] })
    cpIdx++
  }
  return items
}

function formatElapsed(ts: number): string {
  const s = (Date.now() - ts) / 1000
  return s < 60 ? `${s.toFixed(1)}s` : `${(s / 60).toFixed(1)}m`
}

export function NodeFlowPanel({ agent }: NodeFlowPanelProps) {
  const { recentSteps, checkpoints, id } = agent
  const bottomRef = useRef<HTMLDivElement>(null)
  const agentColor = AGENT_COLORS[id] ?? '#00f0ff'

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [recentSteps.length, checkpoints.length])

  if (recentSteps.length === 0 && checkpoints.length === 0) return null

  const timeline = buildTimeline(recentSteps, checkpoints)

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.headerLabel}>NODE FLOW</span>
        <span style={styles.headerStats}>
          {recentSteps.length > 0 && `${agent.stepCount} steps`}
          {checkpoints.length > 0 && ` · ${checkpoints.length} ✓`}
        </span>
      </div>
      <div style={styles.list}>
        {timeline.map((item, i) =>
          item.kind === 'checkpoint' ? (
            <div key={`cp-${item.data.index}`} style={styles.checkpointRow}>
              <span style={{ ...styles.cpDiamond, textShadow: `0 0 8px ${agentColor}` }}>◆</span>
              <span style={styles.cpText}>
                <strong>Checkpoint {item.data.index}</strong> · step {item.data.step}
                <br />
                <span style={{ color: '#86efac' }}>{item.data.summary}</span>
              </span>
            </div>
          ) : (
            <div
              key={`step-${item.data.step}-${i}`}
              style={{
                ...styles.stepRow,
                animation: 'slideInStep 0.2s ease-out',
                animationFillMode: 'both',
                animationDelay: `${Math.min(i * 20, 200)}ms`,
              }}
            >
              <span style={styles.stepCircle}>○</span>
              <span style={{ ...styles.stepTool, color: agentColor }}>
                {TOOL_ICONS[item.data.tool] ?? '⚙'} {item.data.tool}
              </span>
              <span style={styles.stepLabel}>{item.data.label}</span>
              <span style={styles.stepElapsed}>{formatElapsed(item.data.ts)}</span>
            </div>
          )
        )}
        <div ref={bottomRef} />
      </div>
      <style>{`
        @keyframes slideInStep {
          from { opacity: 0; transform: translateX(-8px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    borderBottom: '1px solid #1e293b',
    marginBottom: 8,
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.1em',
    color: '#475569',
    textTransform: 'uppercase',
    padding: '6px 0 4px',
  },
  headerLabel: { color: '#475569' },
  headerStats: { color: '#94a3b8', fontWeight: 400 },
  list: {
    maxHeight: 180,
    overflowY: 'auto',
    fontSize: 11,
    lineHeight: '1.6',
  },
  stepRow: {
    display: 'flex',
    gap: 6,
    alignItems: 'baseline',
    borderLeft: '1px solid #1e293b',
    marginLeft: 6,
    paddingLeft: 8,
    paddingBottom: 2,
  },
  stepCircle: { color: '#334155', minWidth: 10 },
  stepTool: {
    minWidth: 64,
    fontFamily: 'JetBrains Mono, monospace',
  },
  stepLabel: {
    color: '#94a3b8',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: 180,
  },
  stepElapsed: {
    color: '#334155',
    fontSize: 10,
    marginLeft: 'auto',
    whiteSpace: 'nowrap',
  },
  checkpointRow: {
    display: 'flex',
    gap: 8,
    alignItems: 'flex-start',
    padding: '4px 0',
    borderTop: '1px solid #1e293b',
  },
  cpDiamond: { color: '#22c55e', minWidth: 16, marginLeft: 2 },
  cpText: { color: '#94a3b8', fontSize: 11 },
}
