export type AgentStatus = 'idle' | 'thinking' | 'working' | 'done'
export type WsModel = 'claude' | 'gemini' | 'tgpt'

export interface Step {
  step: number
  tool: string
  label: string
  ts: number
}

export interface Checkpoint {
  index: number
  summary: string
  step: number
  ts: number
}

export interface AgentState {
  id: string
  name: string
  role: string
  status: AgentStatus
  recentOutput: string[]
  stepCount: number
  recentSteps: Step[]
  checkpoints: Checkpoint[]
}

export interface EdgeState {
  from: string
  to: string
  isActive: boolean
}

export interface WorkQueueItem {
  id: string
  task: string
  status: 'pending' | 'active' | 'blocked' | 'completed'
  agent?: string
}

export interface Notification {
  id: string
  text: string
  ts: number
  type: 'done' | 'delegation' | 'queue' | 'message'
      | 'routine' | 'email' | 'approval' | 'system'
}

export interface BrowserView {
  image: string          // base64 (no data: prefix)
  mime: 'image/jpeg' | 'image/png'
  url: string
  caption: string
  ts: number
}

export const AGENT_POSITIONS: Record<string, [number, number, number]> = {
  ceo:      [0,  0.5,  4],
  backend:  [-3, 0,   -1],
  frontend: [-2, 0,   -3],
  qa:       [0,  0,   -2],
  devops:   [2,  0,   -1],
  browser:  [3,  0,   -3],
}

export const AGENT_RADII: Record<string, number> = {
  ceo:      0.9,
  backend:  0.6,
  frontend: 0.6,
  qa:       0.6,
  devops:   0.6,
  browser:  0.6,
}

export const AGENT_COLORS: Record<string, string> = {
  ceo:      '#f59e0b',
  backend:  '#3b82f6',
  frontend: '#ec4899',
  qa:       '#f59e0b',
  devops:   '#10b981',
  browser:  '#8b5cf6',
}

export const TOOL_ICONS: Record<string, string> = {
  bash:    '⚙',
  read:    '📖',
  write:   '✍',
  edit:    '✏',
  web:     '🌐',
  jira:    '🎫',
  browser: '🔍',
}
