import { useEffect, useState } from 'react'
import './MobileGate.css'

// Soft mobile gate. Shown when the viewport is narrower than the
// breakpoint and the user hasn't dismissed it this session. Phones get
// an explanation + a copy-link button (so they can finish reading on a
// laptop) plus an escape hatch link to continue on mobile anyway.
//
// Not a hard block. The escape link is intentionally present so a
// stubborn judge or someone on a tablet can proceed without contacting
// support. Dismissal is per-tab (sessionStorage), so a fresh visit on
// the same device still surfaces the gate.

const BREAKPOINT_PX = 768
const DISMISS_KEY = 'skorpio.mobileGate.dismissed'

// Custom event dispatched by `onContinue` so the guided tour can hold
// its auto-open timer until the user has actually dismissed the gate.
// Listened to in App.tsx's TourWrapper.
export const MOBILE_GATE_DISMISSED_EVENT = 'skorpio-mobile-gate-dismissed'

function getInitialDismissed(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.sessionStorage.getItem(DISMISS_KEY) === '1'
  } catch {
    return false
  }
}

function isNarrow(): boolean {
  if (typeof window === 'undefined') return false
  return window.innerWidth < BREAKPOINT_PX
}

// Exported so TourWrapper can decide whether to suppress its auto-open
// timer on first paint. The gate hides the rest of the UI while
// active, so opening the tour underneath it costs nothing visible but
// lets the tour's click-anywhere-advances logic eat the user's
// dismissal taps. Returns true exactly when the gate would render.
export function isMobileGateActive(): boolean {
  return isNarrow() && !getInitialDismissed()
}

export function MobileGate() {
  const [narrow, setNarrow] = useState<boolean>(isNarrow)
  const [dismissed, setDismissed] = useState<boolean>(getInitialDismissed)
  const [copied, setCopied] = useState(false)

  // Track viewport changes so a device rotation or window resize
  // re-evaluates the gate. Once dismissed, the user stays through
  // resizes (we never block them mid-session after they opted in).
  useEffect(() => {
    if (typeof window === 'undefined') return
    const onResize = () => setNarrow(isNarrow())
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  if (!narrow || dismissed) return null

  const onCopy = async () => {
    const url = window.location.href
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2500)
    } catch {
      // Older mobile browsers without the async clipboard API. Fall
      // back to a hidden textarea + document.execCommand so the copy
      // still works on iOS 12 / Android Chrome 64 era devices.
      const ta = document.createElement('textarea')
      ta.value = url
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      try {
        document.execCommand('copy')
        setCopied(true)
        window.setTimeout(() => setCopied(false), 2500)
      } catch {
        // Even the fallback failed. The user will have to manually
        // type the URL from the address bar — there's no on-screen
        // copy of it to long-press anymore.
      } finally {
        document.body.removeChild(ta)
      }
    }
  }

  const onContinue = () => {
    try {
      window.sessionStorage.setItem(DISMISS_KEY, '1')
    } catch {
      // Storage disabled (private mode on some browsers). The flag
      // still flips in React state so the gate hides for the rest
      // of this navigation, just not across hard refreshes.
    }
    setDismissed(true)
    // Let the guided tour know it can start its auto-open timer now.
    // TourWrapper holds the timer while the gate is up so a tap on
    // Copy link doesn't advance the tour underneath the gate.
    try {
      window.dispatchEvent(new CustomEvent(MOBILE_GATE_DISMISSED_EVENT))
    } catch {}
  }

  return (
    <div className="mobile-gate" role="dialog" aria-modal="true" aria-labelledby="mobile-gate-title">
      <div className="mobile-gate-card">
        {/* Inline SVG so the brand mark renders even if the backend is
            offline or the CDN is unreachable — same drop+rounded-square
            artwork used in the LoginPage and HomePage topbars. */}
        <div className="mobile-gate-brand" aria-label="Skorpio">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="7" fill="#1f1e1d" />
            <g transform="translate(6.25, 3) scale(0.8125)">
              <path
                d="M12 0 C 12 8, 22 14, 22 22 A 10 10 0 1 1 2 22 C 2 14, 12 8, 12 0 Z"
                fill="#F38764"
              />
            </g>
          </svg>
          <span className="mobile-gate-wordmark">SKORPIO</span>
        </div>
        <h1 id="mobile-gate-title" className="mobile-gate-title">
          Best viewed on a laptop
        </h1>
        <p className="mobile-gate-body">
          Skorpio uses Mapbox maps and dense multi-pane reports. They
          render correctly on a laptop or desktop. Phone screens will
          show layout issues.
        </p>

        <button
          type="button"
          className="mobile-gate-copy"
          onClick={onCopy}
          aria-live="polite"
        >
          {copied ? 'Link copied' : 'Copy link to open on laptop'}
        </button>
        {/* Static domain shown as a visual receipt for the copy button —
            confirms WHAT the user is about to copy without churning per
            page like `window.location.href` would. The actual clipboard
            payload still uses the full deep-link URL (see onCopy above),
            so a judge already on /?tab=reports lands on the right page
            after pasting. */}
        <p className="mobile-gate-url" aria-hidden="true">
          skorpio.vercel.app
        </p>

        <button
          type="button"
          className="mobile-gate-continue"
          onClick={onContinue}
        >
          Continue on mobile anyway
        </button>
      </div>
    </div>
  )
}
