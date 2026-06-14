// nexus-ui/src/components/PostProcessing.tsx
import { memo } from 'react'
import { EffectComposer, Bloom, ChromaticAberration, Vignette, Noise, Scanline } from '@react-three/postprocessing'
import { BlendFunction } from 'postprocessing'
import * as THREE from 'three'

// Hoisted so the ChromaticAberration offset keeps a stable identity across any
// future render (no per-frame Vector2 allocation).
const CA_OFFSET = new THREE.Vector2(0.0008, 0.0008)

// memo: PostProcessing takes no props, so it renders exactly once. NexusScene
// re-renders on nearly every WebSocket event (it subscribes to the agents map);
// without this, each re-render gave EffectComposer a new children array,
// defeating its own React.memo and rebuilding the whole pass chain repeatedly.
// (This is a correctness/perf win — NOT the flicker fix; see multisampling below.)
export const PostProcessing = memo(function PostProcessing() {
  return (
    // multisampling={0}: the Canvas already requests antialias:true (MSAA on the
    // context). The composer defaulting to multisampling:8 stacks a SECOND MSAA
    // layer on a HalfFloat render target, which flickers the whole scene on
    // Chrome/ANGLE. Disable the composer's MSAA and let the context handle AA.
    <EffectComposer multisampling={0}>
      <Bloom
        intensity={1.35}
        luminanceThreshold={0.3}
        luminanceSmoothing={0.9}
        mipmapBlur
      />
      <ChromaticAberration
        blendFunction={BlendFunction.NORMAL}
        offset={CA_OFFSET}
        radialModulation={false}
        modulationOffset={0}
      />
      <Vignette darkness={0.4} />
      <Scanline blendFunction={BlendFunction.OVERLAY} density={1.1} opacity={0.045} />
      <Noise premultiply opacity={0.05} />
    </EffectComposer>
  )
})
