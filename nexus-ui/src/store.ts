// nexus-ui/src/store.ts
import { create } from 'zustand'
import type { AgentState, EdgeState, Step, Checkpoint } from './types'

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

interface NexusStore {
  agents: Record<string, AgentState>
  edges: EdgeState[]
  selectedAgent: string | null
  wsStatus: 'connected' | 'offline'

  selectAgent: (id: string | null) => void
  setWsStatus: (s: 'connected' | 'offline') => void
  handleEvent: (event: Record<string, unknown>) => void
}

export const useNexusStore = create<NexusStore>((set) => ({
  agents: Object.fromEntries(
    ['ceo', ...WORKER_IDS].map(id => [id, defaultAgent(id)])
  ),
  edges: defaultEdges(),
  selectedAgent: null,
  wsStatus: 'offline',

  selectAgent: (id) => set({ selectedAgent: id }),
  setWsStatus: (s) => set({ wsStatus: s }),

  handleEvent: (event) => {
    const type = event.type as string
    const agentId = event.agent as string | undefined

    set(state => {
      const agents = { ...state.agents }
      const edges = [...state.edges]

      const updateAgent = (id: string, patch: Partial<AgentState>) => {
        agents[id] = { ...(agents[id] ?? defaultAgent(id)), ...patch }
      }

      switch (type) {
        case 'init': {
          const list = (event.agents as Array<{ id: string; name: string; role: string }>) ?? []
          list.forEach(a => {
            agents[a.id] = { ...defaultAgent(a.id, a.name, a.role), ...agents[a.id] }
          })
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
          }
          break

        case 'worker_done':
          if (agentId) {
            updateAgent(agentId, {
              status: 'done',
              stepCount: 0,
              recentSteps: [],
              checkpoints: [],
            })
            const edge = edges.find(e => e.to === agentId)
            if (edge) edge.isActive = false
          }
          break

        case 'worker_step': {
          if (!agentId) break
          const step: Step = {
            step: event.step as number,
            tool: event.tool as string,
            label: event.label as string,
            ts: Date.now(),
          }
          const prev = agents[agentId] ?? defaultAgent(agentId)
          const recentSteps = [...prev.recentSteps, step].slice(-20)
          updateAgent(agentId, {
            stepCount: event.step as number,
            recentSteps,
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
          const recentOutput = [...prev3.recentOutput, content].slice(-500)
          updateAgent(agentId, { recentOutput })
          break
        }

        case 'done':
          if (agentId) updateAgent(agentId, { status: 'idle' })
          break

        case 'error':
          if (agentId) updateAgent(agentId, { status: 'idle' })
          break
      }

      return { agents, edges }
    })
  },
}))

// ── WebSocket hook ─────────────────────────────────────────────────────────────

let _ws: WebSocket | null = null
let _retryDelay = 1000

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
      useNexusStore.getState().handleEvent(data)
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
