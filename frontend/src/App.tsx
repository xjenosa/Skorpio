import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useParams, useLocation } from 'react-router-dom'
import { LoginPage } from './pages/LoginPage'
import { HomePage } from './pages/HomePage'
import { PipelinePage } from './pages/PipelinePage'
import { PrivacyPolicyPage } from './pages/PrivacyPolicyPage'
import { TermsPage } from './pages/TermsPage'
import { DemoToggle } from './components/DemoToggle'
import { AuthGate } from './components/AuthGate'
import { MobileGate, MOBILE_GATE_DISMISSED_EVENT, isMobileGateActive } from './components/MobileGate'
import { GuidedTour, hasSeenTour } from './components/GuidedTour'
import { HelpButton } from './components/HelpButton'

function PipelineRedirect() {
  const { jobId } = useParams<{ jobId: string }>()
  return <Navigate to={`/pipeline/${jobId ?? ''}`} replace />
}

// Tour + (?) help button wrapper. Lives inside BrowserRouter because
// GuidedTour uses useNavigate to step between routes. Auto-opens once
// per browser (localStorage flag) on the first home-page visit; the
// (?) button replays it on demand thereafter. Suppressed on /login and
// the legal pages so a judge isn't tour-bombed before they're inside
// the product.
function TourWrapper() {
  const [open, setOpen] = useState(false)
  // Mobile gate suppresses the auto-open timer. While the gate is up
  // the tour sits behind it and the gate's tap-anywhere dismissal
  // (Copy link, Continue) would otherwise advance the tour underneath.
  // Initialized from sessionStorage so the first paint matches the
  // gate's own visibility check; flipped to false when MobileGate
  // dispatches MOBILE_GATE_DISMISSED_EVENT from its Continue handler.
  const [gateActive, setGateActive] = useState<boolean>(isMobileGateActive)
  const location = useLocation()
  const isProductRoute =
    location.pathname === '/' || location.pathname.startsWith('/pipeline/')

  useEffect(() => {
    const onDismissed = () => setGateActive(false)
    window.addEventListener(MOBILE_GATE_DISMISSED_EVENT, onDismissed)
    return () => window.removeEventListener(MOBILE_GATE_DISMISSED_EVENT, onDismissed)
  }, [])

  useEffect(() => {
    if (!isProductRoute) return
    if (hasSeenTour()) return
    if (gateActive) return
    // Defer slightly so the page has time to render and the anchors are
    // present in the DOM before the tour tries to measure them.
    const id = setTimeout(() => setOpen(true), 600)
    return () => clearTimeout(id)
  }, [isProductRoute, gateActive])

  if (!isProductRoute) return null

  return (
    <>
      <GuidedTour open={open} onClose={() => setOpen(false)} />
      <HelpButton onClick={() => setOpen(true)} />
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<AuthGate><HomePage /></AuthGate>} />
        <Route path="/pipeline/:jobId" element={<AuthGate><PipelinePage /></AuthGate>} />
        {/* Legacy /winter-peak/:jobId redirects to the unified pipeline page */}
        <Route path="/winter-peak/:jobId" element={<PipelineRedirect />} />
        <Route path="/privacy" element={<PrivacyPolicyPage />} />
        <Route path="/terms" element={<TermsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <DemoToggle />
      <MobileGate />
      <TourWrapper />
    </BrowserRouter>
  )
}
