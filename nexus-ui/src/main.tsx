// nexus-ui/src/main.tsx
import { StrictMode, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { NexusScene } from './components/NexusScene'
import { connectWebSocket } from './store'

function App() {
  useEffect(() => {
    connectWebSocket()
  }, [])

  return <NexusScene />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
)
