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

export const CEO_POSITION: [number, number, number] = [0, 0.5, 4]

/** Place worker `index` of `total` on a 200° arc behind the CEO, radius 5.5. */
export function workerPosition(index: number, total: number): [number, number, number] {
  const arc = (200 * Math.PI) / 180
  const start = Math.PI / 2 + arc / 2
  const angle = total <= 1 ? Math.PI / 2 : start - (arc * index) / (total - 1)
  const r = 5.5
  return [Math.cos(angle) * r, 0, CEO_POSITION[2] - Math.sin(angle) * r]
}

const FALLBACK_PALETTE = ['#22d3ee', '#a3e635', '#fb7185', '#fbbf24', '#34d399', '#818cf8']

/** Identity color for any agent id — known agents keep their color, custom ids hash into a palette. */
export function agentColor(id: string): string {
  if (AGENT_COLORS[id]) return AGENT_COLORS[id]
  let h = 0
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return FALLBACK_PALETTE[h % FALLBACK_PALETTE.length]
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
