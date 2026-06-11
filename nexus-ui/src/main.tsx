// nexus-ui/src/main.tsx
import { StrictMode, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { connectWebSocket } from './store'

function App() {
  useEffect(() => {
    connectWebSocket()
  }, [])

  return <div style={{ width: '100vw', height: '100vh', background: '#050a14' }} />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
)
