// nexus-ui/src/components/EdgeTaskLabel.tsx
import { Billboard, Text } from '@react-three/drei'
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
    <Billboard position={mid}>
      <Text fontSize={0.085} color={color} anchorX="center" maxWidth={2.4}
            textAlign="center" outlineWidth={0.004} outlineColor="#020408">
        {item.task.length > 60 ? item.task.slice(0, 60) + '…' : item.task}
      </Text>
    </Billboard>
  )
}
