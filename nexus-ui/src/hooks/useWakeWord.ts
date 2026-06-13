// nexus-ui/src/hooks/useWakeWord.ts
import { useEffect } from 'react'
import { sendWsMessage } from '../store'

const WAKE_KEY = 'nexus-wake-enabled'
const WAKE_RE = /\b(nexus|subaru)\b[,.]?\s*/i

export function isWakeEnabled(): boolean {
  try { return localStorage.getItem(WAKE_KEY) === 'true' } catch { return false }
}

export function toggleWakeWord(): boolean {
  const next = !isWakeEnabled()
  try { localStorage.setItem(WAKE_KEY, String(next)) } catch { /* ignore */ }
  // Reload-free toggle: the hook below polls this flag on each recognition cycle.
  return next
}

/**
 * Continuous wake-word listener. When a final transcript contains "nexus"/"subaru":
 * - if there's a command after the wake word → send it straight to the CEO
 * - if the wake word is alone → focus the command bar
 * Chrome-only (webkitSpeechRecognition); silently inert elsewhere.
 */
export function useWakeWord() {
  useEffect(() => {
    const SR = (window as unknown as { webkitSpeechRecognition?: new () => unknown }).webkitSpeechRecognition
      ?? (window as unknown as { SpeechRecognition?: new () => unknown }).SpeechRecognition
    if (!SR) return

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let recog: any = null
    let stopped = false

    const start = () => {
      if (stopped || !isWakeEnabled()) {
        // Re-check the toggle every 3s while disabled
        if (!stopped) setTimeout(start, 3000)
        return
      }
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        recog = new (SR as any)()
        recog.continuous = true
        recog.interimResults = false
        recog.lang = 'en-US'
        recog.onresult = (e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal?: boolean }> }) => {
          const last = e.results[e.results.length - 1]
          const transcript = (last?.[0]?.transcript ?? '').trim()
          const m = WAKE_RE.exec(transcript)
          if (!m) return
          const command = transcript.slice(m.index + m[0].length).trim()
          if (command) {
            sendWsMessage({ type: 'message', agent: 'ceo', text: command })
          } else {
            window.dispatchEvent(new Event('nexus-focus-cmdbar'))
          }
        }
        recog.onend = () => { if (!stopped) setTimeout(start, 500) }   // auto-restart
        recog.onerror = () => { /* onend fires next and restarts */ }
        recog.start()
      } catch { /* mic blocked — stay inert */ }
    }

    start()
    return () => {
      stopped = true
      try { recog?.stop() } catch { /* ignore */ }
    }
  }, [])
}
