// nexus-ui/src/components/CameraDirector.tsx
import { useEffect, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import type { CameraControls } from '@react-three/drei'
import { useNexusStore } from '../store'

const HOME = { pos: [0, 2, 10] as const, target: [0, 0.5, 0] as const }

interface Props {
  controlsRef: React.RefObject<CameraControls | null>
  positionFor: (id: string) => [number, number, number]
}

export function CameraDirector({ controlsRef, positionFor }: Props) {
  const selectedAgent = useNexusStore(s => s.selectedAgent)
  const agents = useNexusStore(s => s.agents)
  const lastInteraction = useRef(Date.now())

  // Any user interaction pauses the idle orbit for 8s
  useEffect(() => {
    const bump = () => { lastInteraction.current = Date.now() }
    window.addEventListener('pointerdown', bump)
    window.addEventListener('wheel', bump)
    return () => {
      window.removeEventListener('pointerdown', bump)
      window.removeEventListener('wheel', bump)
    }
  }, [])

  // Fly to the selected agent; return home on deselect
  useEffect(() => {
    const controls = controlsRef.current
    if (!controls) return
    if (selectedAgent && selectedAgent !== 'ceo') {
      const [x, y, z] = positionFor(selectedAgent)
      controls.setLookAt(x * 0.35, y + 1.6, z + 4.2, x, y + 0.2, z, true)
    } else if (selectedAgent === 'ceo') {
      controls.setLookAt(0, 1.4, 7.5, 0, 0.5, 4, true)
    } else {
      controls.setLookAt(...HOME.pos, ...HOME.target, true)
    }
  }, [selectedAgent, controlsRef, positionFor])

  // Slow idle orbit when nothing selected, nobody working, no recent input
  useFrame((_, delta) => {
    const controls = controlsRef.current
    if (!controls || selectedAgent) return
    const anyBusy = Object.values(agents).some(a => a.status === 'working' || a.status === 'thinking')
    if (anyBusy) return
    if (Date.now() - lastInteraction.current < 8000) return
    controls.azimuthAngle += delta * 0.025
  })

  return null
}
