// nexus-ui/src/components/NodeFlowPanel.tsx
import { useEffect, useRef } from 'react'
import type { AgentState, Step, Checkpoint } from '../types'
import { TOOL_ICONS } from '../types'

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

export function NodeFlowPanel({ agent }: NodeFlowPanelProps) {
  const { recentSteps, checkpoints } = agent
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [recentSteps.length, checkpoints.length])

  if (recentSteps.length === 0 && checkpoints.length === 0) return null

  const timeline = buildTimeline(recentSteps, checkpoints)

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        NODE FLOW
        <span style={styles.headerStats}>
          {recentSteps.length > 0 && `${agent.stepCount} steps`}
          {checkpoints.length > 0 && ` · ${checkpoints.length} ✓`}
        </span>
      </div>
      <div style={styles.list}>
        {timeline.map((item, i) =>
          item.kind === 'checkpoint' ? (
            <div key={`cp-${item.data.index}`} style={styles.checkpointRow}>
              <span style={styles.cpDiamond}>◆</span>
              <span style={styles.cpText}>
                <strong>Checkpoint {item.data.index}</strong> · step {item.data.step}
                <br />
                <span style={{ color: '#86efac' }}>{item.data.summary}</span>
              </span>
            </div>
          ) : (
            <div key={`step-${item.data.step}-${i}`} style={styles.stepRow}>
              <span style={styles.stepCircle}>○</span>
              <span style={styles.stepTool}>
                {TOOL_ICONS[item.data.tool] ?? '⚙'} {item.data.tool}
              </span>
              <span style={styles.stepLabel}>{item.data.label}</span>
            </div>
          )
        )}
        <div ref={bottomRef} />
      </div>
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
  headerStats: {
    color: '#94a3b8',
    fontWeight: 400,
  },
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
  stepCircle: {
    color: '#334155',
    minWidth: 10,
  },
  stepTool: {
    color: '#00f0ff',
    minWidth: 64,
    fontFamily: 'monospace',
  },
  stepLabel: {
    color: '#94a3b8',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: 220,
  },
  checkpointRow: {
    display: 'flex',
    gap: 8,
    alignItems: 'flex-start',
    padding: '4px 0',
    borderTop: '1px solid #1e293b',
  },
  cpDiamond: {
    color: '#22c55e',
    minWidth: 16,
    marginLeft: 2,
  },
  cpText: {
    color: '#94a3b8',
    fontSize: 11,
  },
}
