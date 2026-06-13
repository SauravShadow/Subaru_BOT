// nexus-ui/src/hooks/useSfx.ts
import { useEffect } from 'react'
import { useNexusStore } from '../store'

const SFX_KEY = 'nexus-sfx-enabled'
let _ctx: AudioContext | null = null

function blip(freq: number, duration = 0.09, gain = 0.04) {
  try {
    if (localStorage.getItem(SFX_KEY) !== 'true') return
    _ctx = _ctx ?? new AudioContext()
    const osc = _ctx.createOscillator()
    const g = _ctx.createGain()
    osc.type = 'sine'
    osc.frequency.value = freq
    g.gain.setValueAtTime(gain, _ctx.currentTime)
    g.gain.exponentialRampToValueAtTime(0.0001, _ctx.currentTime + duration)
    osc.connect(g).connect(_ctx.destination)
    osc.start()
    osc.stop(_ctx.currentTime + duration)
  } catch { /* audio blocked — ignore */ }
}

export function toggleSfx(): boolean {
  const next = localStorage.getItem(SFX_KEY) !== 'true'
  localStorage.setItem(SFX_KEY, String(next))
  return next
}

/** Subscribes to store transitions and plays matching blips. */
export function useSfx() {
  useEffect(() => useNexusStore.subscribe((state, prev) => {
    for (const id of Object.keys(state.agents)) {
      const cur = state.agents[id]?.status
      const old = prev.agents[id]?.status
      if (cur === old) continue
      if (cur === 'working') blip(520)
      else if (cur === 'done') blip(880, 0.14)
      else if (cur === 'thinking') blip(330)
    }
  }), [])
}
