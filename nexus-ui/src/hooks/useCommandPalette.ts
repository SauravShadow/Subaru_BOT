import { useState, useEffect, useCallback } from 'react'
import { useNexusStore, connectWebSocket, sendWsMessage } from '../store'
import { toggleWakeWord } from './useWakeWord'

export interface PaletteAction {
  id: string
  label: string
  group: string
  accent?: string
}

export function useCommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')

  const selectAgent    = useNexusStore(s => s.selectAgent)
  const setIslandTab   = useNexusStore(s => s.setIslandTab)
  const agents         = useNexusStore(s => s.agents)

  const AGENT_ACCENTS: Record<string, string> = {
    ceo:      '#f59e0b',
    backend:  '#3b82f6',
    frontend: '#ec4899',
    qa:       '#f59e0b',
    devops:   '#10b981',
    browser:  '#8b5cf6',
  }

  const actions: PaletteAction[] = [
    ...['ceo', 'backend', 'frontend', 'qa', 'devops', 'browser'].map(id => ({
      id: `agent-${id}`,
      label: `Talk to ${agents[id]?.name ?? id}`,
      group: 'AGENTS',
      accent: AGENT_ACCENTS[id],
    })),
    { id: 'queue-show',   label: 'Show work queue',    group: 'WORK QUEUE' },
    { id: 'notif-show',   label: 'Show notifications', group: 'WORK QUEUE' },
    { id: 'tts-toggle',   label: 'Toggle voice / TTS', group: 'VOICE' },
    { id: 'wake-toggle',  label: 'Toggle wake word ("Nexus …")', group: 'VOICE' },
    { id: 'ws-reconnect', label: 'Reconnect WebSocket', group: 'SYSTEM' },
  ]

  const matched = query.trim()
    ? actions.filter(a => a.label.toLowerCase().includes(query.toLowerCase()))
    : actions
  const filtered: PaletteAction[] = matched.length > 0 ? matched : [
    { id: 'ask-subaru', label: `Ask Subaru: "${query.trim()}"`, group: 'COMMAND', accent: '#f59e0b' },
  ]

  const runAction = useCallback((id: string, toggleTts?: () => void) => {
    setOpen(false)

    if (id.startsWith('agent-')) {
      selectAgent(id.replace('agent-', ''))
    } else if (id === 'queue-show') {
      setIslandTab('queue')
    } else if (id === 'notif-show') {
      setIslandTab('notifications')
    } else if (id === 'tts-toggle') {
      toggleTts?.()
    } else if (id === 'wake-toggle') {
      toggleWakeWord()
    } else if (id === 'ask-subaru') {
      const text = query.trim()
      if (text) sendWsMessage({ type: 'message', agent: 'ceo', text })
    } else if (id === 'ws-reconnect') {
      connectWebSocket()
    }

    setQuery('')
  }, [selectAgent, setIslandTab, query])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setOpen(prev => !prev)
      }
      if (e.key === 'Escape') {
        setOpen(false)
        setQuery('')
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return { open, setOpen, query, setQuery, filtered, runAction }
}
