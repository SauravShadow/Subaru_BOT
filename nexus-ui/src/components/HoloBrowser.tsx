// nexus-ui/src/components/HoloBrowser.tsx
import { useEffect, useMemo, useRef, useState } from 'react'
import { Billboard, Text } from '@react-three/drei'
import * as THREE from 'three'
import { useNexusStore } from '../store'

const VIOLET = '#8b5cf6'
const FRESH_MS = 90_000   // hide hologram 90s after the last frame

interface Props {
  position: [number, number, number]   // Maya's node position
}

export function HoloBrowser({ position }: Props) {
  const view = useNexusStore(s => s.browserView)
  const [, forceTick] = useState(0)
  const texRef = useRef<THREE.Texture | null>(null)

  // Build a texture from the latest frame; dispose the previous one
  const texture = useMemo(() => {
    if (!view) return null
    const img = new Image()
    const tex = new THREE.Texture(img)
    tex.colorSpace = THREE.SRGBColorSpace
    img.onload = () => { tex.needsUpdate = true }
    img.src = `data:${view.mime};base64,${view.image}`
    return tex
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view?.ts])

  useEffect(() => {
    const prev = texRef.current
    texRef.current = texture
    return () => { prev?.dispose() }
  }, [texture])

  // Re-evaluate freshness once after the window passes
  useEffect(() => {
    if (!view) return
    const id = setTimeout(() => forceTick(n => n + 1), FRESH_MS + 1000)
    return () => clearTimeout(id)
  }, [view?.ts])

  if (!view || !texture) return null
  if (Date.now() - view.ts > FRESH_MS) return null

  const holoPos: [number, number, number] = [position[0], position[1] + 2.1, position[2]]

  return (
    <Billboard position={holoPos}>
      {/* Glow frame */}
      <mesh position={[0, 0, -0.01]}>
        <planeGeometry args={[2.56, 1.66]} />
        <meshBasicMaterial color={VIOLET} transparent opacity={0.25} />
      </mesh>
      {/* The live screen */}
      <mesh>
        <planeGeometry args={[2.4, 1.5]} />
        <meshBasicMaterial map={texture} transparent opacity={0.92} toneMapped={false} />
      </mesh>
      <Text position={[0, -0.92, 0]} fontSize={0.08} color={VIOLET} anchorX="center"
            maxWidth={2.4} outlineWidth={0.004} outlineColor="#020408">
        {(view.caption ? `${view.caption} · ` : '') + view.url.slice(0, 70)}
      </Text>
    </Billboard>
  )
}
