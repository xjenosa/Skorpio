import { useEffect, useState, type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { api, clearToken, getToken } from '../api/client'
import { isDemoModeActive, useDemoMode } from '../hooks/useDemoMode'

type AuthState = 'checking' | 'ok' | 'denied'

/**
 * Auth gate for protected routes. Three layers:
 *
 *  1. Demo-mode bypass: if the user has flipped the floating demo toggle,
 *     skip the auth check entirely and render children. This is what lets
 *     a hackathon judge enter the product from /login → click "demo" →
 *     land on / without ever touching Google sign-in. The auth check is
 *     not just bypassed — it's never made, so a Vercel deploy with no
 *     backend can still serve the demo experience.
 *
 *  2. Synchronous fast-path: no localStorage token → immediate redirect to
 *     /login (zero flash, zero network round-trip).
 *
 *  3. Async validation: token present → call /api/auth/me and gate render
 *     on the result. While the request is in flight we render nothing
 *     (blank screen for ~50–300ms) instead of the full UI; on 401 we clear
 *     the stale token and redirect to /login.
 *
 *  Layer 3 is what makes "docker restarted, backend session DB is
 *  fresh, browser still has yesterday's token" land directly on /login
 *  instead of flashing the console for a beat and then bouncing.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [demo] = useDemoMode()
  const [state, setState] = useState<AuthState>(() => {
    // Demo mode short-circuits before we even look at the token. The
    // initial-state computation reads localStorage directly (via
    // isDemoModeActive) so the first render is correct without waiting
    // for a useEffect tick.
    if (isDemoModeActive()) return 'ok'
    return getToken() ? 'checking' : 'denied'
  })

  // React to demo toggling at runtime — flipping ON anywhere in the app
  // should immediately unblock the gated route without needing a refresh.
  useEffect(() => {
    if (demo) setState('ok')
  }, [demo])

  useEffect(() => {
    if (state !== 'checking') return
    if (demo) return                       // demo wins; skip the network round-trip
    let cancelled = false
    api
      .getMe()
      .then(() => {
        if (!cancelled) setState('ok')
      })
      .catch(() => {
        if (cancelled) return
        clearToken()
        setState('denied')
      })
    return () => {
      cancelled = true
    }
  }, [state, demo])

  if (state === 'denied') return <Navigate to="/login" replace />
  if (state === 'checking') return null
  return <>{children}</>
}
