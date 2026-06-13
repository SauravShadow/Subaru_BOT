// nexus-ui/src/components/EdgeTaskLabel.tsx
import { Html } from '@react-three/drei'
import { useNexusStore } from '../store'
import { agentColor } from '../types'

interface Props {
  workerId: string
  start: [number, number, number]
  end: [number, number, number]
}

export function EdgeTaskLabel({ workerId, start, end }: Props) {
  const item = useNexusStore(s =>
    s.workQueue.find(q => q.agent === workerId && q.status === 'active'))
  if (!item) return null

  const mid: [number, number, number] = [
    (start[0] + end[0]) / 2,
    (start[1] + end[1]) / 2 + 0.45,
    (start[2] + end[2]) / 2,
  ]
  const color = agentColor(workerId)

  return (
    <Html position={mid} center distanceFactor={9} zIndexRange={[20, 0]}
          style={{ pointerEvents: 'none', userSelect: 'none' }}>
      <div style={{
        maxWidth: 240, textAlign: 'center',
        fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color,
        background: 'rgba(2, 4, 8, 0.55)', border: `1px solid ${color}33`,
        borderRadius: 6, padding: '3px 8px',
        textShadow: '0 0 6px currentColor',
      }}>
        {item.task.length > 60 ? item.task.slice(0, 60) + '…' : item.task}
      </div>
    </Html>
  )
}
