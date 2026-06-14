import { useState, useEffect, useCallback, useRef } from 'react'
import { onAudioEvent, onSpeechFallback } from '../store'

const TTS_KEY = 'nexus-tts-enabled'

type SpeechRecognitionType = unknown

// ── Module-level singletons (shared across ALL useVoice instances) ───────────
// Multiple components mount useVoice (NexusScene, CommandBar, and
// AgentDetailView when open). Audio playback and speech synthesis MUST be
// registered EXACTLY ONCE — otherwise every reply is voiced once per mounted
// instance (the "bot says everything twice" bug: NexusScene + CommandBar are
// both always mounted → 2×). Only the per-instance microphone (SpeechRecognition)
// stays local, since just the focused input should capture voice.

let _ttsEnabled: boolean = (() => {
  try { return localStorage.getItem(TTS_KEY) !== 'false' } catch { return true }
})()

// isSpeaking pub/sub — every mounted hook subscribes so its UI reflects playback.
const _speakingSubs = new Set<(v: boolean) => void>()
let _isSpeaking = false
function _setSpeaking(v: boolean) {
  _isSpeaking = v
  _speakingSubs.forEach(fn => fn(v))
}

// ttsEnabled pub/sub — toggling in one place updates every consumer.
const _ttsSubs = new Set<(v: boolean) => void>()
function _setTtsEnabled(v: boolean) {
  _ttsEnabled = v
  try { localStorage.setItem(TTS_KEY, String(v)) } catch {}
  _ttsSubs.forEach(fn => fn(v))
}

// Single shared audio queue — plays Bark clips sequentially.
const AudioQueue = {
  _queue: [] as Array<{ base64: string; mode: string }>,
  _playing: false,

  push(base64: string, mode: string) {
    this._queue.push({ base64, mode })
    if (!this._playing) this._next()
  },

  async _next() {
    if (!this._queue.length) {
      this._playing = false
      _setSpeaking(false)
      return
    }
    this._playing = true
    _setSpeaking(true)

    const { base64 } = this._queue.shift()!
    try {
      const binary = atob(base64)
      const bytes = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
      const blob = new Blob([bytes], { type: 'audio/wav' })
      const url = URL.createObjectURL(blob)
      const el = new Audio(url)
      el.onended = () => { URL.revokeObjectURL(url); this._next() }
      el.onerror = () => { URL.revokeObjectURL(url); this._next() }
      await el.play()
    } catch {
      this._next()
    }
  },
}

// Register the global playback + speech-fallback listeners EXACTLY ONCE.
let _playbackInit = false
function _initPlaybackOnce() {
  if (_playbackInit) return
  _playbackInit = true

  // Bark audio from the backend
  onAudioEvent((base64, mode) => {
    if (!_ttsEnabled) return
    AudioQueue.push(base64, mode)
  })

  // Web Speech fallback when Bark produced no audio
  onSpeechFallback((text) => {
    if (!_ttsEnabled) return
    if (AudioQueue._playing) return                 // Bark audio wins
    if (!('speechSynthesis' in window)) return
    const clean = text
      .replace(/```[\s\S]*?```/g, ' code block omitted ')
      .replace(/[*_#>`]/g, '')
      .slice(0, 300)
    if (!clean.trim()) return
    window.speechSynthesis.cancel()
    const utter = new SpeechSynthesisUtterance(clean)
    utter.rate = 1.05
    utter.onstart = () => _setSpeaking(true)
    utter.onend = () => _setSpeaking(false)
    window.speechSynthesis.speak(utter)
  })
}

export function useVoice(_agentId: string | null, onTranscript: (text: string) => void) {
  const [isListening, setIsListening] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(_isSpeaking)
  const [ttsEnabled, setTtsEnabledState] = useState(_ttsEnabled)

  const recogRef = useRef<SpeechRecognitionType | null>(null)

  // Initialize global playback once; subscribe to shared speaking/tts state.
  useEffect(() => {
    _initPlaybackOnce()
    _speakingSubs.add(setIsSpeaking)
    _ttsSubs.add(setTtsEnabledState)
    setIsSpeaking(_isSpeaking)
    setTtsEnabledState(_ttsEnabled)
    return () => {
      _speakingSubs.delete(setIsSpeaking)
      _ttsSubs.delete(setTtsEnabledState)
    }
  }, [])

  const startListening = useCallback(() => {
    const SpeechRecognition =
      (window as unknown as { SpeechRecognition?: unknown }).SpeechRecognition ??
      (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition

    if (!SpeechRecognition) return

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const recog = new (SpeechRecognition as any)()
    recog.continuous = false
    recog.interimResults = false
    recog.lang = 'en-US'

    recog.onresult = (e: Event) => {
      const event = e as unknown as { results: Array<Array<{ transcript: string }>> }
      const transcript = (event.results[0]?.[0]?.transcript ?? '').toString()
      if (transcript.trim()) onTranscript(transcript.trim())
    }

    recog.onend = () => setIsListening(false)
    recog.onerror = () => setIsListening(false)

    recog.start()
    recogRef.current = recog as SpeechRecognitionType
    setIsListening(true)
  }, [onTranscript])

  const stopListening = useCallback(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (recogRef.current as any)?.stop()
    recogRef.current = null
    setIsListening(false)
  }, [])

  const toggleTts = useCallback(() => {
    _setTtsEnabled(!_ttsEnabled)
  }, [])

  const hasSpeechRecognition = !!(
    (window as unknown as { SpeechRecognition?: unknown }).SpeechRecognition ??
    (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition
  )

  return {
    isListening,
    isSpeaking,
    ttsEnabled,
    hasSpeechRecognition,
    startListening,
    stopListening,
    toggleTts,
  }
}
