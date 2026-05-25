import {
  CSSProperties,
  ReactNode,
  RefObject,
  useEffect,
  useRef,
  useState,
} from 'react'
import './SmoothStage.css'

// Skorpio's smooth-scroll primitives. Native scrollbar is hidden; wheel events
// are intercepted and animated with a lerp toward a moving target so the page
// keeps gliding after the wheel stops — the "physics" feel of nicely engineered
// editorial sites. Custom accent-orange thumb sits on the right edge.
//
// Three exports:
//   useSmoothScroll(ref)   — attach the wheel-lerp behavior to any scrollable element
//   ScrollIndicator        — render the custom thumb tracking that element
//   SmoothStage            — the workspace's <section class="stage"> wrapper, both pre-wired

const LERP = 0.12             // 0..1 — higher = snappier follow
const WHEEL_MULTIPLIER = 1.0
const STOP_THRESHOLD = 0.4    // px — snap to target once we're close enough

// ── Hook: lerp the scroll position toward a moving target ────────────────── //

export function useSmoothScroll(ref: RefObject<HTMLElement>) {
  useEffect(() => {
    const el = ref.current
    if (!el) return

    let target = el.scrollTop
    let current = target
    let rafId = 0
    let running = false

    function step() {
      if (!el) return
      const delta = target - current
      if (Math.abs(delta) < STOP_THRESHOLD) {
        current = target
        el.scrollTop = current
        running = false
        return
      }
      current += delta * LERP
      el.scrollTop = current
      rafId = requestAnimationFrame(step)
    }

    function start() {
      if (running) return
      running = true
      current = el!.scrollTop
      rafId = requestAnimationFrame(step)
    }

    function onWheel(e: WheelEvent) {
      // Hands-off zones — wheel events here belong to the inner widget,
      // not to SmoothStage's lerp. Mapbox embeds (`.skorpio-map`) use wheel
      // for zoom; anything else opting in adds the class
      // `skorpio-no-smooth-scroll`. Without this guard SmoothStage's
      // preventDefault swallows wheel before the embed can react.
      const tgt = e.target as Element | null
      if (
        tgt?.closest?.('.skorpio-map') ||
        tgt?.closest?.('.skorpio-no-smooth-scroll')
      ) {
        return
      }

      // Let nested scrollable elements (chat threads, dropdowns, modals,
      // code blocks) handle their own scroll natively — only claim the wheel
      // when no ancestor below us can absorb it in this direction.
      if (nestedCanAbsorb(tgt, el!, e.deltaY)) return

      const max = el!.scrollHeight - el!.clientHeight
      if (max <= 0) return
      e.preventDefault()
      target = clamp(target + e.deltaY * WHEEL_MULTIPLIER, 0, max)
      start()
    }

    function onScroll() {
      // External scroll sources — keyboard arrows, anchor jumps, programmatic
      // scrollTo — re-sync the animation target so we don't fight the user.
      if (!running) {
        target = el!.scrollTop
        current = target
      }
    }

    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('scroll', onScroll, { passive: true })

    return () => {
      el.removeEventListener('wheel', onWheel)
      el.removeEventListener('scroll', onScroll)
      cancelAnimationFrame(rafId)
    }
  }, [ref])
}

// ── Helpers ─────────────────────────────────────────────────────────────── //

function clamp(v: number, min: number, max: number): number {
  return v < min ? min : v > max ? max : v
}

// Walk up from the event target to the stage. If we find a scrollable element
// that still has room in the wheel direction, let native scroll handle it.
function nestedCanAbsorb(node: Element | null, container: HTMLElement, deltaY: number): boolean {
  while (node && node !== container) {
    if (node instanceof HTMLElement) {
      const cs = getComputedStyle(node)
      const overflowY = cs.overflowY
      if (overflowY === 'auto' || overflowY === 'scroll') {
        if (node.scrollHeight > node.clientHeight) {
          const atTop = node.scrollTop <= 0
          const atBottom = node.scrollTop + node.clientHeight >= node.scrollHeight - 1
          if (deltaY < 0 && !atTop) return true
          if (deltaY > 0 && !atBottom) return true
        }
      }
    }
    node = node.parentElement
  }
  return false
}

// ── Scroll indicator ────────────────────────────────────────────────────── //

const MIN_THUMB = 36       // px — never shrink below this
const TRACK_PAD = 8        // px — top/bottom padding inside the rail
const HIDE_AFTER_MS = 1100 // ms idle before the thumb fades

export function ScrollIndicator({ targetRef }: { targetRef: RefObject<HTMLElement> }) {
  const thumbRef = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const el = targetRef.current
    const thumb = thumbRef.current
    if (!el || !thumb) return

    let hideTimer: ReturnType<typeof setTimeout> | undefined

    function compute() {
      if (!el || !thumb) return
      const max = el.scrollHeight - el.clientHeight
      if (max <= 4) {
        setVisible(false)
        return
      }
      const trackHeight = el.clientHeight - TRACK_PAD * 2
      const ratio = el.clientHeight / el.scrollHeight
      const height = Math.max(MIN_THUMB, trackHeight * ratio)
      const progress = el.scrollTop / max
      // The thumb is `position: absolute` inside the scroll container, so it
      // scrolls with the content. Adding `scrollTop` to the translateY pins it
      // visually to the viewport — at scrollTop=200 the +200 cancels the
      // -200 visual shift from scrolling, leaving the thumb where we want it.
      const top = TRACK_PAD + progress * (trackHeight - height) + el.scrollTop

      // Write geometry imperatively so scroll-frame updates don't wait on
      // React's render cycle (which would visibly lag behind).
      thumb.style.transform = `translateY(${top}px)`
      thumb.style.height = `${height}px`
      setVisible(true)

      clearTimeout(hideTimer)
      hideTimer = setTimeout(() => setVisible(false), HIDE_AFTER_MS)
    }

    compute()
    el.addEventListener('scroll', compute, { passive: true })
    const ro = new ResizeObserver(compute)
    ro.observe(el)
    // Re-measure when content grows (charts hydrating, async data filling in).
    const mo = new MutationObserver(compute)
    mo.observe(el, { childList: true, subtree: true })

    return () => {
      el.removeEventListener('scroll', compute)
      ro.disconnect()
      mo.disconnect()
      clearTimeout(hideTimer)
    }
  }, [targetRef])

  return (
    <div
      ref={thumbRef}
      className="scroll-indicator"
      style={{ opacity: visible ? 1 : 0 }}
      aria-hidden
    />
  )
}

// ── SmoothStage: pre-wired wrapper for the workspace's <section class="stage"> ── //

export interface SmoothStageProps {
  children: ReactNode
  className?: string
  style?: CSSProperties
  /**
   * Whenever this value changes, the stage scrolls instantly back to the
   * top. Used by HomePage to reset scroll when switching tabs (or switching
   * jobs within Agent Pipeline). Without it, scrolling deep into the Agent
   * Pipeline tab and then clicking Reports / Dashboard / New Session would
   * land at the previous scroll position, looking at nothing.
   */
  resetKey?: string | number
}

export function SmoothStage({ children, className, style, resetKey }: SmoothStageProps) {
  const ref = useRef<HTMLElement>(null)
  useSmoothScroll(ref)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    // Set scrollTop directly. useSmoothScroll's onScroll listener picks
    // this up and resyncs its lerp target+current to 0, so any in-flight
    // animation snaps to rest at the top instead of continuing toward the
    // pre-switch target.
    el.scrollTop = 0
  }, [resetKey])
  return (
    <section
      ref={ref}
      className={`stage smooth-stage${className ? ` ${className}` : ''}`}
      style={style}
    >
      {children}
      <ScrollIndicator targetRef={ref} />
    </section>
  )
}
