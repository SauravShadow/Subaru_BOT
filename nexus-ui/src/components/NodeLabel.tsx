// nexus-ui/src/components/NodeLabel.tsx
import { Html } from '@react-three/drei'

interface Props {
  position: [number, number, number]
  name: string
  role: string
  color: string
  dimmed?: boolean
}

/** Crisp CSS typography anchored to a 3D position — replaces in-scene drei <Text>. */
export function NodeLabel({ position, name, role, color, dimmed }: Props) {
  return (
    <Html position={position} center distanceFactor={8} zIndexRange={[20, 0]}
          style={{ pointerEvents: 'none', userSelect: 'none' }}>
      <div style={{ textAlign: 'center', whiteSpace: 'nowrap',
                    opacity: dimmed ? 0.25 : 1, transition: 'opacity 200ms' }}>
        <div style={{
          fontFamily: 'Orbitron, sans-serif', fontSize: 13, fontWeight: 700,
          letterSpacing: '0.18em', color,
          textShadow: `0 0 10px ${color}aa, 0 0 2px #000`,
        }}>
          {name.toUpperCase()}
        </div>
        <div style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 9,
          color: '#94a3b8', letterSpacing: '0.08em', marginTop: 2,
        }}>
          {role}
        </div>
      </div>
    </Html>
  )
}
