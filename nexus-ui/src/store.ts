import { create } from 'zustand'
import type { AgentState, EdgeState, Step, Checkpoint, WorkQueueItem, Notification, WsModel, BrowserView } from './types'

const WORKER_IDS = ['backend', 'frontend', 'qa', 'devops', 'browser']

function defaultAgent(id: string, name = id, role = ''): AgentState {
  return {
    id, name, role,
    status: 'idle',
    recentOutput: [],
    stepCount: 0,
    recentSteps: [],
    checkpoints: [],
  }
}

function defaultEdges(): EdgeState[] {
  return WORKER_IDS.map(id => ({ from: 'ceo', to: id, isActive: false }))
}

function makeNotification(text: string, type: Notification['type']): Notification {
  return { id: `${Date.now()}-${Math.random()}`, text, ts: Date.now(), type }
}

interface NexusStore {
  agents: Record<string, AgentState>
  edges: EdgeState[]
  selectedAgent: string | null
  wsStatus: 'connected' | 'offline'
  wsModel: WsModel
  workQueue: WorkQueueItem[]
  notifications: Notification[]
  islandExpanded: boolean
  islandTab: 'notifications' | 'queue' | 'active'
  browserView: BrowserView | null
  browserVisible: boolean
  designPreviewTs: number | null
  designPreviewVisible: boolean
  pendingApprovals: number

  selectAgent: (id: string | null) => void
  setWsStatus: (s: 'connected' | 'offline') => void
  resetAgentStatus: (id: string) => void
  setIslandExpanded: (v: boolean) => void
  setIslandTab: (tab: 'notifications' | 'queue' | 'active') => void
  setBrowserVisible: (v: boolean) => void
  setDesignPreviewVisible: (v: boolean) => void
  setPendingApprovals: (n: number) => void
  handleEvent: (event: Record<string, unknown>) => void
}

export const useNexusStore = create<NexusStore>((set) => ({
  agents: Object.fromEntries(
    ['ceo', ...WORKER_IDS].map(id => [id, defaultAgent(id)])
  ),
  edges: defaultEdges(),
  selectedAgent: null,
  wsStatus: 'offline',
  wsModel: 'claude',
  workQueue: [],
  notifications: [],
  islandExpanded: false,
  islandTab: 'notifications',
  browserView: null,
  browserVisible: false,
  designPreviewTs: null,
  designPreviewVisible: false,
  pendingApprovals: 0,

  selectAgent: (id) => set({ selectedAgent: id }),
  setWsStatus: (s) => set({ wsStatus: s }),
  resetAgentStatus: (id) => set(state => ({
    agents: { ...state.agents, [id]: { ...state.agents[id], status: 'idle' } }
  })),
  setIslandExpanded: (v) => set({ islandExpanded: v }),
  setIslandTab: (tab) => set({ islandTab: tab, islandExpanded: true }),
  setBrowserVisible: (v) => set({ browserVisible: v }),
  setDesignPreviewVisible: (v) => set({ designPreviewVisible: v }),
  setPendingApprovals: (n) => set({ pendingApprovals: n }),

  handleEvent: (event) => {
    const type = event.type as string
    const agentId = event.agent as string | undefined

    set(state => {
      const agents = { ...state.agents }
      const edges = state.edges.map(e => ({ ...e }))
      const notifications = [...state.notifications]

      const updateAgent = (id: string, patch: Partial<AgentState>) => {
        agents[id] = { ...(agents[id] ?? defaultAgent(id)), ...patch }
      }

      const addNotif = (text: string, type: Notification['type']) => {
        notifications.unshift(makeNotification(text, type))
        if (notifications.length > 10) notifications.pop()
      }

      switch (type) {
        case 'init': {
          const list = (event.agents as Array<{ id: string; name: string; role: string }>) ?? []
          list.forEach(a => {
            agents[a.id] = { ...defaultAgent(a.id, a.name, a.role), ...agents[a.id] }
          })
          // Reset stale active edges on reconnect
          edges.forEach(e => { e.isActive = false })
          break
        }

        case 'thinking':
          if (agentId) updateAgent(agentId, { status: 'thinking' })
          break

        case 'delegation':
          if (agentId) {
            updateAgent(agentId, { status: 'working' })
            const edge = edges.find(e => e.to === agentId)
            if (edge) edge.isActive = true
            addNotif(`${agents[agentId]?.name ?? agentId} assigned task`, 'delegation')
          }
          break

        case 'worker_done':
          if (agentId) {
            const name = agents[agentId]?.name ?? agentId
            updateAgent(agentId, {
              status: 'done',
              stepCount: 0,
              recentSteps: [],
              checkpoints: [],
            })
            const edge = edges.find(e => e.to === agentId)
            if (edge) edge.isActive = false
            addNotif(`${name} completed task`, 'done')
          }
          break

        case 'tool_call': {
          if (!agentId) break
          const label = event.label as string
          const prev = agents[agentId] ?? defaultAgent(agentId)
          updateAgent(agentId, {
            recentOutput: [...prev.recentOutput, `Tool: ${label}`].slice(-500)
          })
          break
        }

        case 'worker_step': {
          if (!agentId) break
          const step: Step = {
            step: event.step as number,
            tool: event.tool as string,
            label: event.label as string,
            ts: Date.now(),
          }
          const prev = agents[agentId] ?? defaultAgent(agentId)
          updateAgent(agentId, {
            stepCount: event.step as number,
            recentSteps: [...prev.recentSteps, step].slice(-20),
          })
          break
        }

        case 'worker_checkpoint': {
          if (!agentId) break
          const cp: Checkpoint = {
            index: event.index as number,
            summary: event.summary as string,
            step: event.step as number,
            ts: Date.now(),
          }
          const prev2 = agents[agentId] ?? defaultAgent(agentId)
          updateAgent(agentId, { checkpoints: [...prev2.checkpoints, cp] })
          break
        }

        case 'assistant': {
          if (!agentId) break
          const raw = (event.message as { content?: unknown })?.content
          let content = ''
          if (typeof raw === 'string') {
            content = raw
          } else if (Array.isArray(raw)) {
            content = (raw as Array<{ type?: string; text?: string; media_type?: string; data?: string }>)
              .map(b => {
                if (b.type === 'text') return b.text ?? ''
                if (b.type === 'image' && b.data) return ` img:${b.media_type ?? 'image/png'}:${b.data}`
                return ''
              })
              .join('')
          }
          if (!content.trim()) break
          const prev3 = agents[agentId] ?? defaultAgent(agentId)
          updateAgent(agentId, {
            recentOutput: [...prev3.recentOutput, content].slice(-500)
          })
          break
        }

        case 'queue_update': {
          const items = (event.queue as WorkQueueItem[]) ?? []
          return { agents, edges, notifications, workQueue: items }
        }

        case 'backend_switch':
          return { agents, edges, notifications, wsModel: event.model as WsModel }

        case 'backend_status': {
          const backend = event.backend as WsModel | undefined
          if (backend) return { agents, edges, notifications, wsModel: backend }
          break
        }

        case 'browser_navigated':
          if (event.screenshot) {
            return {
              agents, edges, notifications,
              browserVisible: true,
              browserView: {
                image: event.screenshot as string, mime: 'image/png' as const,
                url: (event.url as string) ?? '', caption: (event.title as string) ?? '',
                ts: Date.now(),
              },
            }
          }
          break

        case 'browser_frame':
          if (event.frame) {
            return {
              agents, edges, notifications,
              browserVisible: true,
              browserView: {
                image: event.frame as string, mime: 'image/jpeg' as const,
                url: (event.url as string) ?? '', caption: (event.action as string) ?? '',
                ts: Date.now(),
              },
            }
          }
          break

        case 'browser_result':
          addNotif(`Maya: ${String(event.summary ?? event.message ?? 'browser job finished').slice(0, 80)}`, 'done')
          break

        case 'design_preview_updated':
          addNotif('Design preview updated', 'system')
          return { agents, edges, notifications, designPreviewTs: Date.now(), designPreviewVisible: true }

        case 'routine_completed':
          addNotif(`Routine ${event.routine_id}: ${event.status}`, 'routine')
          break

        case 'standup':
          addNotif('Standup briefing generated', 'routine')
          break

        case 'email_sent':
          addNotif(`Email sent: ${String(event.subject ?? '').slice(0, 60)}`, 'email')
          break

        case 'source_file_modified':
          addNotif(`${event.agent} modified ${event.path} (${event.zone})`, 'system')
          break

        case 'approval_requested':
          addNotif(`Approval needed: ${event.file_path}`, 'approval')
          return { agents, edges, notifications, pendingApprovals: state.pendingApprovals + 1 }

        case 'approval_applied':
        case 'approval_denied':
          addNotif(`Approval ${event.approval_id}: ${type === 'approval_applied' ? 'applied' : 'denied'}`, 'approval')
          return { agents, edges, notifications, pendingApprovals: Math.max(0, state.pendingApprovals - 1) }

        case 'done':
          if (agentId) updateAgent(agentId, { status: 'idle' })
          break

        case 'error':
          if (agentId) updateAgent(agentId, { status: 'idle' })
          break
      }

      return { agents, edges, notifications }
    })
  },
}))

// ── WebSocket ────────────────────────────────────────────────────────────────

let _ws: WebSocket | null = null
let _retryDelay = 1000
const _workingTimers: Record<string, ReturnType<typeof setTimeout>> = {}

// Module-level audio event emitter (avoids Zustand churn for audio events)
type AudioListener = (base64: string, mode: string) => void
const _audioListeners: AudioListener[] = []
export function onAudioEvent(cb: AudioListener) { _audioListeners.push(cb) }
export function offAudioEvent(cb: AudioListener) {
  const i = _audioListeners.indexOf(cb)
  if (i >= 0) _audioListeners.splice(i, 1)
}

// Speech-synthesis fallback channel — fired when an assistant reply arrives
// without Bark audio (bark_ok !== true). useVoice decides whether to speak it.
type SpeechListener = (text: string) => void
const _speechListeners: SpeechListener[] = []
export function onSpeechFallback(cb: SpeechListener) { _speechListeners.push(cb) }
export function offSpeechFallback(cb: SpeechListener) {
  const i = _speechListeners.indexOf(cb)
  if (i >= 0) _speechListeners.splice(i, 1)
}

export function connectWebSocket(model = 'claude'): void {
  if (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)) return

  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${protocol}//${location.host}/ws?model=${model}`
  _ws = new WebSocket(url)

  _ws.onopen = () => {
    _retryDelay = 1000
    useNexusStore.getState().setWsStatus('connected')
  }

  _ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data) as Record<string, unknown>

      // Route audio events to listeners only (not into Zustand)
      if (data.type === 'audio') {
        _audioListeners.forEach(cb => cb(data.data as string, (data.mode as string) ?? 'speak'))
        return
      }

      useNexusStore.getState().handleEvent(data)

      if (data.type === 'assistant' && data.bark_ok !== true) {
        const raw = (data.message as { content?: Array<{ type?: string; text?: string }> })?.content
        const text = Array.isArray(raw)
          ? raw.filter(b => b.type === 'text').map(b => b.text ?? '').join(' ')
          : typeof raw === 'string' ? raw : ''
        if (text.trim()) _speechListeners.forEach(cb => cb(text))
      }

      // Stuck task guard
      const type = data.type as string
      const agentId = data.agent as string | undefined
      if (type === 'delegation' && agentId) {
        clearTimeout(_workingTimers[agentId])
        _workingTimers[agentId] = setTimeout(() => {
          useNexusStore.getState().resetAgentStatus(agentId)
          delete _workingTimers[agentId]
        }, 5 * 60 * 1000)
      }
      if ((type === 'worker_done' || type === 'done') && agentId) {
        clearTimeout(_workingTimers[agentId])
        delete _workingTimers[agentId]
      }
    } catch { /* ignore malformed */ }
  }

  _ws.onclose = () => {
    useNexusStore.getState().setWsStatus('offline')
    setTimeout(() => connectWebSocket(model), Math.min(_retryDelay, 30000))
    _retryDelay = Math.min(_retryDelay * 2, 30000)
  }
}

export function sendWsMessage(data: Record<string, unknown>): void {
  if (_ws?.readyState === WebSocket.OPEN) {
    _ws.send(JSON.stringify(data))
  }
}
