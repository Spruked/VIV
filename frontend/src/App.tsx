import { useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Sidebar } from '@/components/Sidebar'
import { Topbar } from '@/components/Topbar'
import SplashScreen from '@/components/layout/SplashScreen'
import Activities from '@/pages/Activities'
import Calendar from '@/pages/Calendar'
import Contacts from '@/pages/Contacts'
import Dashboard from '@/pages/Dashboard'
import Email from '@/pages/Email'
import Escalations from '@/pages/Escalations'
import OrbAssistant from '@/pages/OrbAssistant'
import Pipeline from '@/pages/Pipeline'
import { BusinessContextProvider } from '@/providers/BusinessContextProvider'
import { VIVProvider } from '@/providers/VIVProvider'

function splashSeen() {
  return sessionStorage.getItem('viv_splash_seen') === '1' || sessionStorage.getItem('cali_splash_seen') === '1'
}

function App() {
  const [showSplash, setShowSplash] = useState(() => !splashSeen())

  function completeSplash() {
    sessionStorage.setItem('viv_splash_seen', '1')
    sessionStorage.setItem('cali_splash_seen', '1')
    setShowSplash(false)
  }

  return (
    <ErrorBoundary>
      <BrowserRouter>
        <BusinessContextProvider>
          <VIVProvider>
            <AnimatePresence mode="wait">
              {showSplash ? <SplashScreen onComplete={completeSplash} /> : null}
            </AnimatePresence>
            <div className="flex h-screen overflow-hidden bg-[#0b0f2a] text-zinc-100">
              <Sidebar />
              <div className="flex min-w-0 flex-1 flex-col">
                <Topbar />
                <main className="min-h-0 flex-1 overflow-y-auto bg-[linear-gradient(180deg,#17306d_0%,#122757_38%,#0b0f2a_100%)] p-5">
                  <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/contacts" element={<Contacts />} />
                    <Route path="/email" element={<Email />} />
                    <Route path="/activities" element={<Activities />} />
                    <Route path="/calendar" element={<Calendar />} />
                    <Route path="/escalations" element={<Escalations />} />
                    <Route path="/orb" element={<OrbAssistant />} />
                    <Route path="/pipeline" element={<Pipeline />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Routes>
                </main>
              </div>
            </div>
          </VIVProvider>
        </BusinessContextProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}

export default App
