// nexus-ui/src/components/NodeLabel.tsx
import { Billboard, Text } from '@react-three/drei'

interface Props {
  position: [number, number, number]
  name: string
  role: string
  color: string
  dimmed?: boolean
}

/**
 * In-canvas (WebGL) label. Rendered with drei <Text> rather than <Html>:
 * DOM-over-canvas compositing (Html) flickers the whole WebGL layer on some
 * GPUs. The outline keeps it legible against the dark scene.
 */
export function NodeLabel({ position, name, role, color, dimmed }: Props) {
  return (
    <Billboard position={position}>
      <Text
        fontSize={0.16}
        color={dimmed ? '#334155' : color}
        anchorX="center"
        anchorY="top"
        letterSpacing={0.06}
        outlineWidth={0.006}
        outlineColor="#020408"
      >
        {name.toUpperCase()}
      </Text>
      <Text
        position={[0, -0.22, 0]}
        fontSize={0.10}
        color={dimmed ? '#1e293b' : '#94a3b8'}
        anchorX="center"
        anchorY="top"
        outlineWidth={0.004}
        outlineColor="#020408"
      >
        {role}
      </Text>
    </Billboard>
  )
}
