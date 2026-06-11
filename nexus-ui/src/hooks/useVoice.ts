import { useState, useEffect, useCallback, useRef } from 'react'
import { onAudioEvent, offAudioEvent } from '../store'

const TTS_KEY = 'nexus-tts-enabled'

type SpeechRecognitionType = unknown

// Module-level AudioQueue — shared across all hook instances
const AudioQueue = {
  _queue: [] as Array<{ base64: string; mode: string }>,
  _playing: false,
  _onPlayingChange: null as ((v: boolean) => void) | null,

  push(base64: string, mode: string) {
    this._queue.push({ base64, mode })
    if (!this._playing) this._next()
  },

  async _next() {
    if (!this._queue.length) {
      this._playing = false
      this._onPlayingChange?.(false)
      return
    }
    this._playing = true
    this._onPlayingChange?.(true)

    const { base64, mode: _mode } = this._queue.shift()!
    void _mode // Suppress unused parameter warning
    try {
      const binary = atob(base64)
      const bytes = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
      const blob = new Blob([bytes], { type: 'audio/wav' })
      const url = URL.createObjectURL(blob)
      const el = new Audio(url)
      el.onended = () => {
        URL.revokeObjectURL(url)
        this._next()
      }
      el.onerror = () => {
        URL.revokeObjectURL(url)
        this._next()
      }
      await el.play()
    } catch {
      this._next()
    }
  },
}

export function useVoice(_agentId: string | null, onTranscript: (text: string) => void) {
  const [isListening, setIsListening] = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [ttsEnabled, setTtsEnabled] = useState(() => {
    try { return localStorage.getItem(TTS_KEY) !== 'false' } catch { return true }
  })

  const recogRef = useRef<SpeechRecognitionType | null>(null)

  // Wire AudioQueue → isSpeaking state
  useEffect(() => {
    AudioQueue._onPlayingChange = setIsSpeaking
    return () => { AudioQueue._onPlayingChange = null }
  }, [])

  // Listen for audio events from WS
  useEffect(() => {
    if (!ttsEnabled) return
    const cb = (base64: string, mode: string) => {
      AudioQueue.push(base64, mode)
    }
    onAudioEvent(cb)
    return () => offAudioEvent(cb)
  }, [ttsEnabled])

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
    setTtsEnabled(prev => {
      const next = !prev
      try { localStorage.setItem(TTS_KEY, String(next)) } catch {}
      return next
    })
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
