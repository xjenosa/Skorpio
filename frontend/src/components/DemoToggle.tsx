import { useEffect } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { DEMO_LOCKED, useDemoMode } from '../hooks/useDemoMode'
import { resolveDemoJobIds } from '../demo/jobs'
import { stopAllTheaters } from '../demo/theaterManager'
import './DemoToggle.css'

// The toggle is intentionally available on every route — including /login —
// so a judge or first-time visitor can flip into demo mode without ever
// signing in. The previous implementation hid the toggle on /login, which
// meant the only way to enter demo mode was to sign in first, defeating
// the purpose. Now /login is the primary entry point for demo mode.
const HIDDEN_ROUTES = new Set<string>()

export function DemoToggle() {
  const location = useLocation()
  const navigate = useNavigate()
  const [demo, setDemo] = useDemoMode()
  const [, setSearchParams] = useSearchParams()

  // Whenever demo mode flips on, resolve the 5 prefix→UUID mappings. The
  // resolver is idempotent and reads from cache after the first run, so
  // re-firing this on every flip is cheap.
  useEffect(() => {
    if (!demo) return
    resolveDemoJobIds().catch((err) => {
      console.warn('[demo] failed to resolve demo job ids:', err)
    })
  }, [demo])

  // Clear `?job=` in the SAME click handler that flips the toggle so React
  // batches the two state changes into one render. Doing this from a
  // useEffect was unreliable: `setSearchParams` from react-router has an
  // unstable identity, so any deps-array including it re-fired on every
  // URL change — which then deleted the `?job=` a submit had just set,
  // killing the theater before it could start.
  const onClick = () => {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev)
        params.delete('job')
        return params
      },
      { replace: true },
    )
    // Cancel any in-flight background theater timers from the current
    // session. The useDemoMode setter handles wiping the localStorage flags
    // (submitted/played/demo lastOpened); this kills the live timers that
    // those flags don't own.
    stopAllTheaters()
    const wasOff = !demo
    setDemo((d) => !d)

    // ON-from-/login: send the user straight to the home page. That's the
    // whole point of the bypass-without-signing-in flow. AuthGate will see
    // the demo flag and render HomePage instead of bouncing back.
    if (wasOff && location.pathname === '/login') {
      navigate('/', { replace: true })
      return
    }
    // OFF-from-a-protected-route: the user's access was demo-based, so
    // turning demo off revokes it. Send them to /login. The unprotected
    // routes (/login, /privacy, /terms) stay where they are — flipping
    // demo off from one of those is fine.
    if (!wasOff) {
      const UNPROTECTED = new Set(['/login', '/privacy', '/terms'])
      if (!UNPROTECTED.has(location.pathname)) {
        navigate('/login', { replace: true })
      }
    }
  }

  if (HIDDEN_ROUTES.has(location.pathname)) return null
  // Vercel deploy → demo is locked ON. Hide the toggle entirely so a judge
  // doesn't click it expecting something to happen. Without this they'd
  // see a "demo · ON" pill that refuses to flip and looks broken.
  if (DEMO_LOCKED) return null

  return (
    <button
      type="button"
      className={`skorpio-demo-toggle${demo ? ' skorpio-demo-toggle--on' : ''}`}
      onClick={onClick}
      aria-pressed={demo}
      aria-label={demo ? 'Demo mode on. Click to turn off.' : 'Demo mode off. Click to turn on.'}
      title={demo ? 'Demo · ON' : 'Demo · OFF'}
    >
      <span className="skorpio-demo-toggle__label">demo</span>
      <span className="skorpio-demo-toggle__track" aria-hidden="true">
        <span className="skorpio-demo-toggle__thumb" />
      </span>
    </button>
  )
}
