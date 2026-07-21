import { useNavigate, Link } from 'react-router-dom'
import { FormEvent, useEffect, useRef, useState } from 'react'
import { GlobeCanvas } from '../components/GlobeCanvas'
import { api, setToken, clearToken, getToken } from '../api/client'
import { useDemoMode } from '../hooks/useDemoMode'
import './LoginPage.css'

const USER_EMAIL_KEY = 'skorpio.user.email'

// Login flow state machine.
//   email     — collecting the email address; "Continue" sends a 6-digit code.
//   code      — code-entry phase; user types the 6 digits emailed to them.
//   verifying — momentary: in flight to /api/auth/email/verify-code.
//   sso       — momentary: redirected back from Google with #token=...
//                we're calling /me to confirm the session and bouncing home.
type Phase = 'email' | 'code' | 'verifying' | 'sso'

export function LoginPage() {
  const nav = useNavigate()
  const [demo] = useDemoMode()
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [phase, setPhase] = useState<Phase>('email')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const codeInputRef = useRef<HTMLInputElement>(null)

  // ── Bounce already-signed-in users out of /login ──────────────────────
  // The sidebar logo and any stray `/login` link now route to `/`, but a
  // user can still type the URL by hand. Treat /login as a logged-out
  // surface: if a session token is present, send them straight home.
  // Runs before the OAuth fragment-capture effect so it doesn't trip on
  // the moments where we're mid-handshake (token isn't stored until
  // setToken() finishes inside that effect).
  //
  // Demo carve-out: if demo mode is on, the user clicked the sidebar
  // "Log in" button on purpose — they want to see the login surface
  // (and either sign in for real or just look at it). Skip the bounce
  // even if a stale real token happens to be in localStorage.
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (window.location.hash.startsWith('#token=')) return
    if (demo) return
    if (getToken()) nav('/', { replace: true })
  }, [nav, demo])

  // ── Capture the token (or error) after Google OAuth bounces back ──────
  // Success path: backend redirects to /login#token=<jwt>&dest=<path>.
  // Failure path (e.g. allowlist rejection): /login#error=<code>.
  // We parse, strip the fragment, then either store the JWT and forward
  // to `dest`, or surface the error message on the login screen.
  useEffect(() => {
    if (typeof window === 'undefined') return
    const hash = window.location.hash
    if (!hash.startsWith('#')) return
    const params = new URLSearchParams(hash.slice(1))

    const errCode = params.get('error')
    if (errCode) {
      window.history.replaceState(null, '', window.location.pathname)
      setError(
        errCode === 'not_authorized'
          ? "This Google account isn't authorized to access Skorpio."
          : `Sign-in failed: ${errCode}`,
      )
      setPhase('email')
      return
    }

    const token = params.get('token')
    if (!token) return
    const dest = params.get('dest') || '/'
    setToken(token)
    window.history.replaceState(null, '', window.location.pathname)
    setPhase('sso')
    api
      .getMe()
      .then((u) => {
        if (u.email) window.localStorage.setItem(USER_EMAIL_KEY, u.email)
        nav(dest.startsWith('/') ? dest : '/')
      })
      .catch((err) => {
        clearToken()
        setError(`Could not complete sign-in: ${err instanceof Error ? err.message : String(err)}`)
        setPhase('email')
      })
  }, [nav])

  // Auto-focus the code input the moment we transition into the code phase.
  useEffect(() => {
    if (phase === 'code') {
      const t = setTimeout(() => codeInputRef.current?.focus(), 30)
      return () => clearTimeout(t)
    }
  }, [phase])

  // ── Handlers ─────────────────────────────────────────────────────────
  //
  // Demo bypass: when the floating demo toggle is ON, every auth handler
  // short-circuits to nav('/'). No Google OAuth round-trip, no email-code
  // request, no token persisted. The sidebar on / will still render the
  // Log In button (not a fake user) because the demo flag is still set —
  // we never impersonate a signed-in identity in demo mode.
  const onGoogle = () => {
    if (demo) {
      nav('/', { replace: true })
      return
    }
    window.location.href = api.googleLoginUrl('/')
  }

  const onRequestCode = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setInfo(null)
    if (demo) {
      nav('/', { replace: true })
      return
    }
    const trimmed = email.trim()
    if (!trimmed) {
      setError('Enter your email')
      return
    }
    setSubmitting(true)
    try {
      const res = await api.requestEmailCode(trimmed)
      setEmail(trimmed)
      setPhase('code')
      setInfo(`Code sent. Check your inbox. It expires in ${res.expires_in_minutes} minutes.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const onVerifyCode = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (demo) {
      nav('/', { replace: true })
      return
    }
    if (!/^\d{6}$/.test(code)) {
      setError('Enter the 6-digit code from the email')
      return
    }
    setSubmitting(true)
    setPhase('verifying')
    try {
      const { token, user } = await api.verifyEmailCode(email, code)
      setToken(token)
      window.localStorage.setItem(USER_EMAIL_KEY, user.email)
      nav('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setPhase('code')
    } finally {
      setSubmitting(false)
    }
  }

  const onResend = async () => {
    setError(null)
    setInfo(null)
    setSubmitting(true)
    try {
      const res = await api.requestEmailCode(email)
      setInfo(`New code sent. Expires in ${res.expires_in_minutes} minutes.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const onChangeEmail = () => {
    setPhase('email')
    setCode('')
    setError(null)
    setInfo(null)
  }

  // ── Render ───────────────────────────────────────────────────────────
  // Skorpio logo target: in normal mode it stays on /login (no-op nav,
  // matches the unauthenticated state). In demo mode it goes to / so the
  // judge can click the logo at any point and land back in the demo home
  // — mirrors the in-app sidebar-logo behavior on / and /pipeline.
  const onLogoClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (demo) {
      e.preventDefault()
      nav('/', { replace: true })
    }
  }

  return (
    <div className="login-root">
      <header className="topbar">
        <a
          className="brand"
          href={demo ? '/' : '/login'}
          aria-label="Skorpio"
          onClick={onLogoClick}
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#1f1e1d"/><g transform="translate(6.25, 3) scale(0.8125)"><path d="M12 0 C 12 8, 22 14, 22 22 A 10 10 0 1 1 2 22 C 2 14, 12 8, 12 0 Z" fill="#F38764"/></g></svg>
          <span className="wordmark">SKORPIO</span>
        </a>
      </header>

      <main className="page">
        <section className="left">
          <div className="eyebrow-row">
            <span className="dot" aria-hidden="true"></span>
            <span className="label">OPERATOR CONSOLE · V0.1.0</span>
          </div>

          <h1 className="headline">
            Reason about the <em>grid</em> from one prompt.
          </h1>
          <p className="subhead">
            Sign in to run datacenter siting, winter peak stress tests, neighborhood
            electrification scoring, grid investment planning, and datacenter
            expansion planning across Canada.
          </p>

          {phase === 'sso' ? (
            <div className="auth" aria-live="polite">
              <p className="subhead">Completing sign-in…</p>
            </div>
          ) : phase === 'email' ? (
            <form className="auth" onSubmit={onRequestCode} noValidate>
              <button className="btn btn-google" type="button" onClick={onGoogle} disabled={submitting}>
                <svg viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <path fill="#EA4335" d="M9 3.48c1.69 0 2.83.73 3.48 1.34l2.54-2.48C13.46.89 11.43 0 9 0 5.48 0 2.44 2.02.96 4.96l2.91 2.26C4.6 5.05 6.62 3.48 9 3.48z" />
                  <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.26-.16-1.84H9v3.48h4.84c-.21 1.12-.84 2.07-1.79 2.71l2.88 2.24c1.68-1.55 2.71-3.83 2.71-6.59z" />
                  <path fill="#FBBC05" d="M3.88 10.74A5.4 5.4 0 0 1 3.62 9c0-.6.1-1.18.27-1.74L.96 4.96A8.99 8.99 0 0 0 0 9c0 1.45.35 2.83.96 4.04l2.92-2.3z" />
                  <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.95-2.18l-2.88-2.24c-.8.54-1.83.86-3.07.86-2.36 0-4.36-1.59-5.08-3.72L.96 13.04C2.43 15.98 5.48 18 9 18z" />
                </svg>
                Continue with Google
              </button>

              <div className="divider"><span>or</span></div>

              <div className="field">
                <input
                  type="email"
                  placeholder="Enter your email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  disabled={submitting}
                  required
                />
              </div>

              <button className="btn btn-primary" type="submit" disabled={submitting}>
                {submitting ? 'Sending code…' : 'Continue with email'}
              </button>
            </form>
          ) : (
            <form className="auth" onSubmit={onVerifyCode} noValidate>
              <p className="subhead" style={{ marginTop: 0 }}>
                We emailed a 6-digit code to <strong>{email}</strong>.
              </p>
              <div className="field">
                <input
                  ref={codeInputRef}
                  type="text"
                  inputMode="numeric"
                  pattern="\d{6}"
                  maxLength={6}
                  placeholder="123456"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  autoComplete="one-time-code"
                  disabled={submitting}
                  style={{
                    fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
                    letterSpacing: '0.4em',
                    fontSize: '20px',
                    textAlign: 'center',
                  }}
                />
              </div>
              <button className="btn btn-primary" type="submit" disabled={submitting || code.length !== 6}>
                {submitting ? 'Verifying…' : 'Sign in'}
              </button>
              <div style={{ display: 'flex', gap: 12, justifyContent: 'space-between', fontSize: 13 }}>
                <button type="button" className="link" onClick={onChangeEmail} disabled={submitting}>
                  Use a different email
                </button>
                <button type="button" className="link" onClick={onResend} disabled={submitting}>
                  Resend code
                </button>
              </div>
            </form>
          )}

          {error && <p className="error" role="alert">{error}</p>}
          {info && !error && <p className="info">{info}</p>}

          <p className="legal">
            By continuing you agree to the <Link to="/terms">Operator Terms</Link> and{' '}
            <Link to="/privacy">Privacy Policy</Link>.
          </p>
        </section>

        <section className="right" aria-label="Live capital-grid network">
          <span className="corner tl" />
          <span className="corner tr" />
          <span className="corner bl" />
          <span className="corner br" />
          <div className="hud hud-tl">
            <span className="swatch" />
            <span>GRID · <strong>LIVE</strong></span>
          </div>
          <div className="hud hud-tr">
            <span>REGION · <strong>ONTARIO · IESO</strong></span>
          </div>
          <div className="hud hud-bl">
            <span>CO₂ · <strong>30</strong> g/kWh</span>
          </div>
          <div className="hud hud-br">
            <span>DEMAND · <strong>17.4</strong> GW</span>
          </div>
          <GlobeCanvas />
        </section>
      </main>
    </div>
  )
}
