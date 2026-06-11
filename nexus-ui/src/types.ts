// nexus-ui/src/types.ts

export type AgentStatus = 'idle' | 'thinking' | 'working' | 'done'

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

export const AGENT_POSITIONS: Record<string, [number, number, number]> = {
  ceo:      [0,  0.5,  4],
  backend:  [-3, 0,   -1],
  frontend: [-2, 0,   -3],
  qa:       [0,  0,   -2],
  devops:   [2,  0,   -1],
  browser:  [3,  0,   -3],
}

export const AGENT_RADII: Record<string, number> = {
  ceo: 0.9,
  backend: 0.6,
  frontend: 0.6,
  qa: 0.6,
  devops: 0.6,
  browser: 0.6,
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
