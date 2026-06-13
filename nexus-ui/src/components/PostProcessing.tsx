// nexus-ui/src/components/PostProcessing.tsx
import { EffectComposer, Bloom, ChromaticAberration, Vignette, Noise, Scanline } from '@react-three/postprocessing'
import { BlendFunction } from 'postprocessing'
import * as THREE from 'three'

export function PostProcessing() {
  return (
    <EffectComposer>
      <Bloom
        intensity={1.35}
        luminanceThreshold={0.3}
        luminanceSmoothing={0.9}
        mipmapBlur
      />
      <ChromaticAberration
        blendFunction={BlendFunction.NORMAL}
        offset={new THREE.Vector2(0.0008, 0.0008)}
        radialModulation={false}
        modulationOffset={0}
      />
      <Vignette darkness={0.4} />
      <Scanline blendFunction={BlendFunction.OVERLAY} density={1.1} opacity={0.045} />
      <Noise premultiply opacity={0.05} />
    </EffectComposer>
  )
}
