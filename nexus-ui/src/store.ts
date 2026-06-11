import { create } from 'zustand'
import type { AgentState, EdgeState, Step, Checkpoint, WorkQueueItem, Notification, WsModel } from './types'

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

  selectAgent: (id: string | null) => void
  setWsStatus: (s: 'connected' | 'offline') => void
  resetAgentStatus: (id: string) => void
  setIslandExpanded: (v: boolean) => void
  setIslandTab: (tab: 'notifications' | 'queue' | 'active') => void
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

  selectAgent: (id) => set({ selectedAgent: id }),
  setWsStatus: (s) => set({ wsStatus: s }),
  resetAgentStatus: (id) => set(state => ({
    agents: { ...state.agents, [id]: { ...state.agents[id], status: 'idle' } }
  })),
  setIslandExpanded: (v) => set({ islandExpanded: v }),
  setIslandTab: (tab) => set({ islandTab: tab, islandExpanded: true }),

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
          const content = (event.message as { content?: string })?.content ?? ''
          if (!content) break
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
