// Ten-step guided tour for first-time visitors. PowerPoint-style: any
// click on the page advances to the next step; the click also passes
// through to whatever's underneath (so clicking the actual anchor button
// fires its normal handler AND advances the tour).
//
// Spotlight implementation uses the box-shadow trick: a small element
// positioned over the anchor with a 9999px box-shadow paints the dim
// "frame" everywhere except over the anchor itself, and pointer-events:
// none on the spotlight lets clicks fall through.
//
// Centered-modal steps (welcome / no anchor / anchor-not-found fallback)
// render a separate dim with a centered card. Auto-navigation between
// routes is per-step; steps can also declare an `onEnter` hook for
// setup work (auto-expanding a stage card, seeding a fixture row).

import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useDemoMode,
  markFixturePlayed,
  markFixtureSubmitted,
  unmarkFixturePlayed,
  unmarkFixtureSubmitted,
} from '../hooks/useDemoMode'
import './GuidedTour.css'

interface TourStep {
  // data-tour-anchor value to find the spotlight target. null = centered modal.
  anchor: string | null
  headline: string
  // Single paragraph or an array of paragraphs (rendered as separate <p>s).
  body: string | string[]
  // Optional route to push before measuring the anchor (auto-nav between tabs).
  route?: string
  // Optional setup hook fired when the step becomes active. Receives a
  // disarm() helper that suspends the global click-to-advance listener
  // for ~250ms — needed when onEnter dispatches synthetic clicks (e.g.
  // auto-expanding a stage card) that would otherwise advance the tour.
  onEnter?: (helpers: { disarm: () => void }) => void
}

// Built inside the component because step 4 + step 9 depend on demoMode
// (different copy / different setup hooks). Memoized so a re-render
// doesn't trash anchor measurement mid-step.
function buildSteps(demoMode: boolean): TourStep[] {
  return [
    {
      anchor: null,
      headline: 'Welcome to Skorpio',
      body: [
        'Skorpio runs five agent pipelines that plan grid investments, site new datacenters, and project electrification load growth.',
        'The agents pull real grid data, simulate scenarios, and produce ranked, actionable plans. This quick tour takes about 30 seconds.',
      ],
      route: '/',
    },
    {
      anchor: 'cards',
      headline: 'Pick a pipeline to run',
      body: 'Each card routes to a different agent.',
      route: '/',
    },
    {
      anchor: 'composer',
      headline: 'Cards fill the composer for you',
      body: 'The prompt drops in automatically once you pick a card.',
      route: '/',
    },
    // Both variants anchor on 'composer-input' (the textarea wrapper)
    // so the spotlight covers the same area whether or not demo
    // mode is on — only the copy changes.
    demoMode
      ? {
          anchor: 'composer-input',
          headline: 'Free typing is paused in this preview',
          body: 'The live build accepts any grid scenario you can describe in plain English.',
          route: '/',
        }
      : {
          anchor: 'composer-input',
          headline: 'Or type any scenario yourself',
          body: 'The composer accepts any grid question in plain English. The cards are just shortcuts.',
          route: '/',
        },
    {
      anchor: 'submit-button',
      headline: 'Hit Enter or the orange arrow to run',
      body: 'Both keyboard and mouse start the pipeline.',
      route: '/',
    },
    {
      // 'stages-row' is the .stages container holding all five cards;
      // during the burst (handled in effectiveAnchor below) we swap to
      // 'stage-card-0'..'stage-card-4' for the per-card sweep, then
      // settle back on the full row.
      anchor: 'stages-row',
      headline: 'Each run is five agent stages',
      body: "Numbered 01 through 05. Each one is a separate step of the agent's reasoning.",
      route: '/?tab=agent-pipeline',
    },
    {
      // Two-phase spotlight (state machine lives in the GuidedTour
      // component, keyed off stepIdx === 6 + step7Phase):
      //   phase 'card' (initial): spotlight just the card — picks up
      //     where the previous step's burst landed.
      //   phase 'wrap' (after 450ms, matching the burst cadence):
      //     synthetically click the card to expand it, then grow the
      //     spotlight to the wrapper element so the card AND its
      //     chart panel light up together.
      // anchor here is just the initial-phase value; effectiveAnchor
      // overrides it once the phase advances.
      anchor: 'stage-card-4',
      headline: 'Open a stage to see inside',
      body: 'Each card shows the data, charts, and decisions behind that step.',
      route: '/?tab=agent-pipeline',
    },
    {
      // The Reports tab auto-loads via this step's route, so we anchor
      // directly on the first row here ("past runs land in Reports")
      // instead of detouring to highlight the sidebar nav button —
      // step 8 used to do that, but it was the only step pointing at
      // a sidebar element, which broke the in-context flow.
      anchor: 'reports-row',
      headline: 'Past runs land in Reports',
      body: "Every pipeline you've run shows up here. Click a row to reopen the report.",
      route: '/?tab=reports',
      // Demo mode: seed the winter-peak fixture into Reports so the row
      // exists to anchor on. Non-demo first-visit users with an empty
      // table fall through to the centered-modal fallback (anchor not
      // found after retries — handled below).
      onEnter: demoMode
        ? () => {
            markFixtureSubmitted('winter-peak-stress')
            markFixturePlayed('winter-peak-stress')
          }
        : undefined,
    },
    // Demo mode delete is non-destructive (it hides the row so the
    // operator can re-trigger the same fixture); the live build
    // actually deletes the record from Postgres. The copy here
    // matches whichever behavior the visitor will see if they click.
    demoMode
      ? {
          anchor: 'reports-row-delete',
          headline: 'Delete hides without losing',
          body: 'Re-submit the same card to bring the row back.',
          route: '/?tab=reports',
        }
      : {
          anchor: 'reports-row-delete',
          headline: 'Delete removes the run',
          body: 'In the live app this is permanent. The row is wiped from your reports.',
          route: '/?tab=reports',
        },
    {
      // Virtual anchor 'report-io' resolves (in the measure effect) to
      // the union of the Import + Export buttons. They sit side-by-side
      // in the Reports page-head actions row.
      anchor: 'report-io',
      headline: 'Move reports in and out',
      body: 'Bring runs in as JSON or .zip, or export them to share with a teammate.',
      route: '/?tab=reports',
    },
  ]
}

const TOUR_SEEN_KEY = 'skorpio.tour.seen'
// HomePage sets this when the user submits a real pipeline (live mode).
// GuidedTour reads it on finish to decide whether to auto-hide the
// tour-seeded winter-peak fixture: a returning user who has already
// run their own pipelines shouldn't have their reports table mutated
// just because they replayed the tour.
export const TOUR_USER_HAS_RUN_KEY = 'skorpio.user-has-run-pipeline'
export function markUserHasRunPipeline(): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(TOUR_USER_HAS_RUN_KEY, '1')
    // A real run replaces the "sample run" empty state, so the
    // suppression flag below is no longer needed. Clear it so a
    // user who later deletes all their runs still sees the sample
    // fallback (parity with the first-launch behaviour).
    window.localStorage.removeItem(TOUR_SAMPLE_SUPPRESSED_KEY)
  } catch {}
}
function hasUserRunPipeline(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(TOUR_USER_HAS_RUN_KEY) === '1'
  } catch {
    return false
  }
}

// AgentPipelineView falls back to rendering the winter-peak fixture as
// a "Sample run" when no real job is selected, so judges have a finished
// pipeline to land on. The Reports tab's first-time-tour auto-hide
// removes the fixture row but the sample-run fallback would still
// surface the same fixture on Agent pipeline, defeating the hide. This
// flag is the matching half: set in finish() under the same gate that
// fires the Reports auto-hide, read by AgentPipelineView to suppress
// the sample. Cleared by markUserHasRunPipeline above so a future
// empty-reports state can re-show the sample if the user wants it.
export const TOUR_SAMPLE_SUPPRESSED_KEY = 'skorpio.tour.sample-suppressed'
export function isTourSampleSuppressed(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage.getItem(TOUR_SAMPLE_SUPPRESSED_KEY) === '1'
  } catch {
    return false
  }
}
// Also written by the demo-mode delete handler when the user hides the
// winter-peak fixture (the same fixture that the Agent Pipeline tab uses
// as its "Sample run" fallback). Without this the sample re-renders
// the same data the user just hid, making the delete look broken.
// Cleared by markUserHasRunPipeline above so a subsequent submission
// restores the sample fallback's normal behaviour.
export function markTourSampleSuppressed(): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(TOUR_SAMPLE_SUPPRESSED_KEY, '1')
  } catch {}
}
// Persistence flag: PipelineLive reads this on mount and starts with
// the 05 Plan Synthesis card pre-opened if set. The tour sets it
// when entering step 7 and clears it on finish/skip. Without this,
// tab switches during the tour remount PipelineLive and reset the
// chart dropdown to closed (a visible "blink" between steps 7 → 8 →
// back to 7).
const TOUR_CARD4_OPEN_KEY = 'skorpio.tour.card4Open'
const setCard4OpenFlag = (on: boolean) => {
  if (typeof window === 'undefined') return
  try {
    if (on) window.localStorage.setItem(TOUR_CARD4_OPEN_KEY, '1')
    else window.localStorage.removeItem(TOUR_CARD4_OPEN_KEY)
  } catch {}
}

export function hasSeenTour(): boolean {
  if (typeof window === 'undefined') return true
  return window.localStorage.getItem(TOUR_SEEN_KEY) === '1'
}

export function markTourSeen(): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(TOUR_SEEN_KEY, '1')
}

interface GuidedTourProps {
  open: boolean
  onClose: () => void
}

export function GuidedTour({ open, onClose }: GuidedTourProps) {
  const [demoMode] = useDemoMode()
  const steps = useMemo(() => buildSteps(demoMode), [demoMode])
  const [stepIdx, setStepIdx] = useState(0)
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null)
  // Step 6 quick-burst frame state: null = not animating, 0..4 = which
  // per-card anchor to spotlight, 'settled' = full row anchor. Stays
  // 'settled' once the burst has played for this tour open.
  const [step6Frame, setStep6Frame] = useState<number | 'settled'>('settled')
  const step6PlayedRef = useRef(false)
  // Step 7 two-phase state: 'card' spotlights just stage-card-4,
  // then after the burst-matching 450ms interval flips to 'wrap' and
  // synthetically clicks card 4 to expand it (so the spotlight grows
  // to cover the chart panel too). Played-flag mirrors the step 6
  // pattern so Back-then-forward doesn't replay the click. Initial
  // value is 'card' so the first render of step 7 matches the phase
  // the effect will set — avoids a one-frame flash to 'wrap' before
  // the effect runs.
  const [step7Phase, setStep7Phase] = useState<'card' | 'wrap'>('card')
  const step7PlayedRef = useRef(false)
  // Captured at tour open time: was this the user's first ever
  // viewing? finish() reads this so an accidental click on the (?)
  // replay button doesn't auto-hide a fixture the user has gotten
  // used to seeing. Stored in a ref so markTourSeen()'s side effect
  // doesn't backfill the value to true before finish() reads it.
  const wasFirstRunRef = useRef(false)
  // Brief disarm window after step transitions so the click that
  // advanced the tour isn't double-counted into a further step. Also
  // togglable by step.onEnter callbacks that dispatch synthetic clicks.
  const armedRef = useRef(false)
  const navigate = useNavigate()

  // Reset to step 0 on every (re)open, plus clear the step 6 and
  // step 7 played flags so re-opening the tour via (?) replays both
  // the per-card burst and the card→wrap expand animation. Also
  // resets step7Phase to 'card' so re-opening doesn't briefly show
  // the wrap-anchored spotlight before the phase effect kicks in.
  //
  // Broadcasts a window event so the HomePage composer can clear
  // any leftover prompt text. A populated composer hides the demo
  // notice overlay (which is gated on `demoMode && !prompt`) and
  // would break step 4's anchor measurement.
  useEffect(() => {
    if (open) {
      setStepIdx(0)
      step6PlayedRef.current = false
      step7PlayedRef.current = false
      setStep7Phase('card')
      // Snapshot whether this is the user's first viewing BEFORE
      // markTourSeen() runs at finish time. Used by finish() to
      // gate the demo fixture auto-hide on first-time-only.
      wasFirstRunRef.current = !hasSeenTour()
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('skorpio-tour-open'))
      }
    }
  }, [open])

  // Toggle a body-level flag while the tour is active so the custom
  // white-arrow cursor CSS targets the whole page (including over the
  // spotlight cutout, where pointer-events: none would otherwise let
  // the underlying element's cursor show through).
  useEffect(() => {
    if (typeof document === 'undefined') return
    if (open) {
      document.body.dataset.tourActive = 'true'
      return () => {
        delete document.body.dataset.tourActive
      }
    }
  }, [open])

  // Lock user-initiated scroll while the tour is open. User scrolls
  // (wheel, touch, arrow keys, space, page up/down) move anchor
  // elements relative to the viewport, which makes the spotlight
  // and tooltip drift out of place — confusing during a guided
  // walkthrough. Programmatic scrolls (the measure effect's
  // scrollIntoView) still go through because we only block the input
  // events, not scroll() itself. Inputs inside the tour (none today,
  // but defensive) are exempted so keyboard text entry isn't broken.
  useEffect(() => {
    if (!open) return
    // Capture phase + stopImmediatePropagation is critical here:
    // SmoothStage (the workspace's scroll container) attaches its
    // own wheel listener on the .smooth-stage element and animates
    // scrollTop imperatively via rAF, bypassing any bubble-phase
    // preventDefault. Intercepting in capture and stopping the
    // event before it reaches SmoothStage is the only reliable
    // way to kill page scroll while the tour is active.
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      e.stopImmediatePropagation()
    }
    const onTouchMove = (e: TouchEvent) => {
      e.preventDefault()
      e.stopImmediatePropagation()
    }
    const SCROLL_KEYS = new Set([
      'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
      'PageUp', 'PageDown', 'Home', 'End', ' ',
    ])
    const onKey = (e: KeyboardEvent) => {
      if (!SCROLL_KEYS.has(e.key)) return
      const t = e.target as HTMLElement | null
      if (t?.closest('input, textarea, [contenteditable="true"]')) return
      e.preventDefault()
      e.stopImmediatePropagation()
    }
    window.addEventListener('wheel', onWheel, { passive: false, capture: true })
    window.addEventListener('touchmove', onTouchMove, { passive: false, capture: true })
    window.addEventListener('keydown', onKey, { passive: false, capture: true })
    return () => {
      window.removeEventListener('wheel', onWheel, { capture: true })
      window.removeEventListener('touchmove', onTouchMove, { capture: true })
      window.removeEventListener('keydown', onKey, { capture: true })
    }
  }, [open])

  // Clear the spotlight rect immediately on step transition so a step
  // whose anchor takes a moment to locate (route change, lazy render)
  // doesn't briefly show the previous step's highlight. Without this,
  // back/forward across steps with hard-to-find anchors leaves a
  // stale spotlight pinned to the old position. The measure effect
  // below repopulates anchorRect once the new step's anchor lands.
  // Burst frames within step 5 don't change stepIdx, so this doesn't
  // flicker during the per-card sweep.
  useEffect(() => {
    setAnchorRect(null)
  }, [stepIdx])

  const step = steps[stepIdx]
  const isLast = stepIdx === steps.length - 1
  const isFirst = stepIdx === 0

  // Effective anchor for the spotlight. Equal to step.anchor except:
  //   • Step 6 (idx 5) burst: returns 'stage-span-N' virtual tokens
  //     (handled by the measure effect's unionFromNames helper as
  //     the union of stage-card-0 through stage-card-N), so the
  //     spotlight grows downward one card at a time instead of
  //     jumping. The final frame settles on the real 'stages-row'
  //     anchor.
  //   • Step 7 (idx 6) two-phase: 'card' → stage-card-4 (initial,
  //     just the card button), 'wrap' → card-and-panel-4 (virtual
  //     union of card-4 + its sibling .stage-viz panel). We use
  //     this explicit virtual anchor instead of the .pp-stage-wrap
  //     element because the wrap is display:contents (0×0 rect)
  //     AND its `children` collection isn't a tight enough
  //     definition of "card + chart" — taking the union of
  //     `.stage-viz`/`.stage-viz-pending` specifically guarantees
  //     the spotlight never accidentally grows to include the
  //     follow-up chatbar or "show conversation" pill below.
  const effectiveAnchor = useMemo(() => {
    if (stepIdx === 5) {
      // During the burst, grow downward one card at a time; once
      // settled, keep the spotlight as the cards-only union
      // (stage-span-4) instead of the real `stages-row` container.
      // Reason: once step 7 has expanded card 4's chart, the
      // chart-open state persists for the rest of the tour, which
      // makes `.stages` taller than the viewport allows for a below-
      // anchor tooltip. The tooltip would then flip above. Anchoring
      // on the cards-only union pins the bottom edge to the bottom
      // of card 5 regardless of chart state, so step 6's tooltip
      // always sits below the anchor.
      const frame = typeof step6Frame === 'number' ? step6Frame : 4
      return `stage-span-${frame}`
    }
    if (stepIdx === 6) {
      return step7Phase === 'card' ? 'stage-card-4' : 'card-and-panel-4'
    }
    return step.anchor
  }, [stepIdx, step6Frame, step7Phase, step.anchor])

  // Per-step navigation: push the step's route so the anchor is actually
  // in the DOM before we measure it.
  useEffect(() => {
    if (!open) return
    if (step.route) navigate(step.route, { replace: true })
  }, [open, stepIdx])

  // Helper passed to step.onEnter so a setup hook can dispatch a
  // synthetic click without it being interpreted as "the user clicked
  // the anchor, advance the tour".
  const disarm = () => {
    armedRef.current = false
    setTimeout(() => {
      armedRef.current = true
    }, 250)
  }

  // Fire the step's onEnter setup hook (auto-expand, seed fixture row,
  // etc.) once the step becomes active. Deferred a tick so route
  // navigation has settled.
  useEffect(() => {
    if (!open) return
    if (!step.onEnter) return
    const id = setTimeout(() => step.onEnter?.({ disarm }), 80)
    return () => clearTimeout(id)
  }, [open, stepIdx])

  // Step 6 burst: cycle 0 → 1 → 2 → 3 → 4 → 'settled' at ~450ms
  // intervals (~2.2s total — the sweep should feel deliberate enough
  // that the user can track which card is lit, not a blink-and-miss).
  // Plays once per tour open; on Back-navigation the played flag
  // short-circuits straight to 'settled' so the animation doesn't
  // replay (read as a bug otherwise). (?) re-open clears the flag.
  useEffect(() => {
    if (!open) return
    if (stepIdx !== 5) {
      setStep6Frame('settled')
      return
    }
    // We deliberately do NOT close an expanded stage card here.
    // The chart-open state should persist across the rest of the
    // tour once step 7 has expanded it — closing on Back to step 6
    // would force step 7 to re-animate on every revisit, which the
    // user flagged as a bug ("instead of replaying the animation
    // every time"). The trade-off is a slightly taller stages-row
    // on the Back path, which may flip the tooltip above the
    // anchor — acceptable for the persistence win.
    if (step6PlayedRef.current) {
      setStep6Frame('settled')
      return
    }
    step6PlayedRef.current = true
    setStep6Frame(0)
    let frame = 0
    const id = setInterval(() => {
      frame += 1
      if (frame >= 5) {
        setStep6Frame('settled')
        clearInterval(id)
      } else {
        setStep6Frame(frame)
      }
    }, 450)
    return () => clearInterval(id)
  }, [open, stepIdx])

  // Step 7 two-phase animation: spotlight just the card for 450ms
  // (same cadence as the step 6 burst frames, so it feels like a
  // continuation), then synthetically click the card to expand it
  // and flip to the wrapper anchor — the spotlight grows to cover
  // the card AND its chart panel. disarm() suspends the global
  // click-advance listener during the synthetic click so we don't
  // double-advance. step7PlayedRef stops the animation from
  // replaying when the user Backs out and returns.
  useEffect(() => {
    if (!open) return
    // Other steps: leave step7Phase alone. Touching it from here
    // would cause a render flash when stepIdx changes to 6 (the
    // wrap-anchored value would render for a frame before the
    // played-flag branch below set it to its final value). The
    // open-reset effect handles initial state.
    if (stepIdx !== 6) return
    // Set persistence flag so that PipelineLive remounts (e.g. user
    // tabs to Reports for step 8 and back via Back) start with card
    // 4 pre-opened. This avoids the visible close→reopen blink.
    setCard4OpenFlag(true)
    // The wrap anchor isn't trivially measurable: .pp-stage-wrap is
    // display:contents (so its own rect is 0×0), so a valid spotlight
    // needs the wrap to contain at least its expanded panel child.
    // Three failure modes the naive "set phase + click + measure"
    // approach hits:
    //   1. Route is still transitioning (Back-from-step-8 switches
    //      from /?tab=reports to /?tab=agent-pipeline), so the card
    //      isn't in the DOM yet — querySelector returns null.
    //   2. Card found but visibleStage state was reset on tab unmount;
    //      we need to click to re-expand. Click is async via React's
    //      render → the panel mounts on the next paint.
    //   3. Panel mounted but its rect briefly resolves to 0 height
    //      (Chrome layout pass not done yet), giving the spotlight a
    //      stale or wrong-sized frame.
    // Fix: stay on the 'card' phase (which always has a usable rect
    // since the button itself has a layout box) until the wrap's
    // child layout has actually settled — meaning the panel sibling
    // exists AND has a non-zero height. Only then flip to 'wrap'.
    let cancelled = false
    let rafId = 0
    const flipToWrapWhenReady = () => {
      let tries = 0
      // Critical: click AT MOST ONCE per round. The previous version
      // called card.click() every frame the card wasn't expanded —
      // but React's commit is async, so frame-2's aria-expanded is
      // still 'false' even after frame-1's click registered, which
      // triggered a second click that toggled the card back to
      // closed. The Back→forward retry path landed on an even
      // number of toggles (= still closed) and the spotlight stayed
      // broken. The flag pins us to a single expand intent and we
      // just wait for React + layout to catch up.
      let attemptedClick = false
      const tick = () => {
        if (cancelled) return
        const card = document.querySelector<HTMLButtonElement>(
          '[data-tour-anchor="stage-card-4"]',
        )
        if (!card) {
          tries += 1
          if (tries < 90) rafId = requestAnimationFrame(tick)
          return
        }
        if (card.getAttribute('aria-expanded') !== 'true') {
          if (!attemptedClick) {
            disarm()
            card.click()
            attemptedClick = true
          }
          tries += 1
          if (tries < 90) rafId = requestAnimationFrame(tick)
          return
        }
        // Card expanded — check the chart panel sibling has been
        // rendered AND has a measurable height before flipping
        // phase. Without this gate the union measures as just the
        // button and the spotlight pops into the wrong size for a
        // frame before settling.
        const wrap = card.parentElement
        const panel = wrap
          ? (wrap.querySelector(
              '.stage-viz, .stage-viz-pending',
            ) as HTMLElement | null)
          : null
        if (panel && panel.getBoundingClientRect().height > 0) {
          setStep7Phase('wrap')
          return
        }
        tries += 1
        if (tries < 90) rafId = requestAnimationFrame(tick)
      }
      tick()
    }
    // Two cases:
    //   • First visit in this tour: card was never expanded, so
    //     play the bar-only spotlight for 450ms (matching step 6's
    //     burst cadence), then expand the chart and flip to 'wrap'.
    //   • Subsequent visit (Back from step 8, etc.): the chart is
    //     already open (we no longer close it in step 6, and the
    //     localStorage flag survives tab remounts). Skip the bar
    //     phase entirely and go straight to ensuring the chart is
    //     measurable as 'wrap'. The user's stated expectation: the
    //     animation plays once per tour run, not once per revisit.
    if (step7PlayedRef.current) {
      flipToWrapWhenReady()
      return () => {
        cancelled = true
        cancelAnimationFrame(rafId)
      }
    }
    setStep7Phase('card')
    step7PlayedRef.current = true
    const id = window.setTimeout(flipToWrapWhenReady, 450)
    return () => {
      cancelled = true
      cancelAnimationFrame(rafId)
      window.clearTimeout(id)
    }
  }, [open, stepIdx])

  // Measure the effective anchor. ResizeObserver tracks size changes so
  // step 7's auto-expanded stage panel grows the spotlight, and step 6's
  // burst re-measures cleanly on each frame.
  //
  // Wrapper elements that use `display: contents` (e.g. .pp-stage-wrap,
  // which lets its button + viz-panel children participate in the
  // .stages grid as direct siblings) have no layout box of their own —
  // getBoundingClientRect would return all zeros, sending the spotlight
  // to the top-left of the screen. rectOf() falls back to the union of
  // child rects in that case, which is what step 7's stage-wrap-N
  // anchor relies on to cover the card + panel together.
  useEffect(() => {
    if (!open) {
      setAnchorRect(null)
      return
    }
    if (!effectiveAnchor) {
      setAnchorRect(null)
      return
    }
    let cancelled = false
    let tries = 0
    let observer: ResizeObserver | null = null
    // Returns null (NOT a zero-rect) when the element has no
    // measurable layout yet. The measure loop interprets null as a
    // retry signal so we don't stamp anchorRect with a bogus 0,0
    // rect that would render the spotlight at the top-left corner
    // of the screen. The previous version returned `r` (which is
    // 0,0) as a fallback, which is exactly the "first highlight is
    // top left at 0,0 coord bug" the user kept reporting.
    const rectOf = (el: HTMLElement): DOMRect | null => {
      const r = el.getBoundingClientRect()
      if (r.width > 0 || r.height > 0) return r
      const kids = Array.from(el.children) as HTMLElement[]
      const rs = kids
        .map((k) => k.getBoundingClientRect())
        .filter((cr) => cr.width > 0 || cr.height > 0)
      if (rs.length === 0) return null
      const top = Math.min(...rs.map((cr) => cr.top))
      const left = Math.min(...rs.map((cr) => cr.left))
      const right = Math.max(...rs.map((cr) => cr.right))
      const bottom = Math.max(...rs.map((cr) => cr.bottom))
      return new DOMRect(left, top, right - left, bottom - top)
    }
    const remeasure = (el: HTMLElement) => {
      if (cancelled) return
      const r = rectOf(el)
      if (r) setAnchorRect(r)
    }
    // Generic union-of-named-anchors helper for any virtual anchor
    // that resolves to multiple real anchors. Used by both the
    // step 6 burst (stage-span-N) and the import/export pair on
    // the final tour step.
    const unionFromNames = (names: string[]): DOMRect | null => {
      const rects: DOMRect[] = []
      for (const name of names) {
        const el = document.querySelector<HTMLElement>(`[data-tour-anchor="${name}"]`)
        if (el) rects.push(el.getBoundingClientRect())
      }
      if (rects.length === 0) return null
      const top = Math.min(...rects.map((r) => r.top))
      const left = Math.min(...rects.map((r) => r.left))
      const right = Math.max(...rects.map((r) => r.right))
      const bottom = Math.max(...rects.map((r) => r.bottom))
      return new DOMRect(left, top, right - left, bottom - top)
    }
    // Special-case virtual anchors that don't map to a single DOM
    // element:
    //   • `stage-span-N` (step 6 burst, grows down through cards 0..N)
    //   • `report-io` (final step, unions Import + Export buttons)
    //   • `card-and-panel-N` (step 7 wrap phase, unions card-N with
    //     its sibling .stage-viz / .stage-viz-pending panel — and
    //     ONLY those two, so the spotlight never grows to swallow
    //     the follow-up chat bar or other content below the panel)
    const spanMatch = effectiveAnchor.match(/^stage-span-(\d+)$/)
    const cardAndPanelMatch = effectiveAnchor.match(/^card-and-panel-(\d+)$/)
    let computeVirtual: (() => DOMRect | null) | null = null
    if (spanMatch) {
      const n = Number(spanMatch[1])
      const names = Array.from({ length: n + 1 }, (_, i) => `stage-card-${i}`)
      computeVirtual = () => unionFromNames(names)
    } else if (effectiveAnchor === 'report-io') {
      computeVirtual = () => unionFromNames(['report-import', 'report-export'])
    } else if (cardAndPanelMatch) {
      const n = Number(cardAndPanelMatch[1])
      computeVirtual = () => {
        const card = document.querySelector<HTMLElement>(
          `[data-tour-anchor="stage-card-${n}"]`,
        )
        if (!card) return null
        const wrap = card.parentElement
        const panel = wrap
          ? (wrap.querySelector(
              '.stage-viz, .stage-viz-pending',
            ) as HTMLElement | null)
          : null
        const rects: DOMRect[] = [card.getBoundingClientRect()]
        if (panel) rects.push(panel.getBoundingClientRect())
        const filtered = rects.filter((r) => r.width > 0 || r.height > 0)
        if (filtered.length === 0) return null
        const top = Math.min(...filtered.map((r) => r.top))
        const left = Math.min(...filtered.map((r) => r.left))
        const right = Math.max(...filtered.map((r) => r.right))
        const bottom = Math.max(...filtered.map((r) => r.bottom))
        return new DOMRect(left, top, right - left, bottom - top)
      }
    }
    if (computeVirtual) {
      const compute = computeVirtual
      const tickVirtual = () => {
        if (cancelled) return
        const r = compute()
        if (r) {
          setAnchorRect(r)
          return
        }
        tries += 1
        if (tries < 30) requestAnimationFrame(tickVirtual)
      }
      tickVirtual()
      const onResize = () => {
        const r = compute()
        if (r) setAnchorRect(r)
      }
      window.addEventListener('resize', onResize)
      window.addEventListener('scroll', onResize, true)
      return () => {
        cancelled = true
        window.removeEventListener('resize', onResize)
        window.removeEventListener('scroll', onResize, true)
      }
    }
    const measure = () => {
      if (cancelled) return
      const el = document.querySelector<HTMLElement>(`[data-tour-anchor="${effectiveAnchor}"]`)
      if (el) {
        // Try to measure now. If rectOf returns null (element not
        // yet laid out, common during a freshly-mounted tab or a
        // panel that's animating in), retry on rAF before giving
        // up. Without this, the spotlight either renders at 0,0 or
        // sits invisible for the first frame.
        const initial = rectOf(el)
        if (initial) {
          el.scrollIntoView({ block: 'center', behavior: 'auto' })
          setAnchorRect(initial)
          // display:contents elements can't be observed directly
          // (the observer fires with zero-size rects). Observe
          // each laid-out child instead so the spotlight re-fits
          // when panels mount/unmount.
          observer = new ResizeObserver(() => remeasure(el))
          const targets =
            el.getBoundingClientRect().width === 0 && el.children.length > 0
              ? (Array.from(el.children) as HTMLElement[])
              : [el]
          targets.forEach((t) => observer!.observe(t))
          return
        }
      }
      tries += 1
      if (tries < 30) requestAnimationFrame(measure)
    }
    measure()
    const onResize = () => {
      const el = document.querySelector<HTMLElement>(`[data-tour-anchor="${effectiveAnchor}"]`)
      if (!el) return
      const r = rectOf(el)
      if (r) setAnchorRect(r)
    }
    window.addEventListener('resize', onResize)
    window.addEventListener('scroll', onResize, true)
    return () => {
      cancelled = true
      observer?.disconnect()
      window.removeEventListener('resize', onResize)
      window.removeEventListener('scroll', onResize, true)
    }
  }, [open, stepIdx, effectiveAnchor])

  const advance = () => {
    if (isLast) {
      finish()
    } else {
      setStepIdx((i) => i + 1)
    }
  }

  const back = () => {
    if (!isFirst) setStepIdx((i) => i - 1)
  }

  const finish = () => {
    // Demo-mode-only auto-hide: only on the user's first ever tour
    // viewing AND when they've never manually run a real pipeline.
    // Both gates matter:
    //   • wasFirstRunRef stops an accidental click on the (?) replay
    //     button from wiping a fixture the user has gotten used to
    //     seeing in Reports.
    //   • hasUserRunPipeline keeps the fixture around for users who
    //     already have their own runs (clearing it would surprise
    //     them by mutating a list they didn't ask to change).
    if (demoMode && wasFirstRunRef.current && !hasUserRunPipeline()) {
      unmarkFixtureSubmitted('winter-peak-stress')
      unmarkFixturePlayed('winter-peak-stress')
      // Suppress the Agent pipeline "sample run" fallback so the
      // winter-peak fixture doesn't reappear on that tab right after
      // it was wiped from Reports. Cleared in markUserHasRunPipeline
      // once the user submits their own first pipeline.
      try {
        window.localStorage.setItem(TOUR_SAMPLE_SUPPRESSED_KEY, '1')
      } catch {}
    }
    markTourSeen()
    setCard4OpenFlag(false)
    // Land the user on New Session after the tour wraps. The last step's
    // anchor is on the Reports tab, so without this the user is dropped
    // there and has to navigate back to start a run. "/" is the New
    // Session default route (see ALL_ROUTES in HomePage.tsx).
    navigate('/')
    onClose()
  }

  // Click-anywhere-advances (PowerPoint model). Any click on the page
  // moves to the next step; clicks that land on the actual anchor also
  // fire the anchor's normal handler (the click bubbles unhindered),
  // so the "click the thing AND advance" feel is preserved without
  // needing a special anchor check. Tour control elements (Back / Skip)
  // tag themselves with data-tour-control so the handler ignores them.
  // Text-selection clicks (drag-then-release) are also ignored so the
  // user can copy text from a tour box without auto-advancing.
  //
  // EXCEPTION — destructive actions: in non-demo mode, the submit
  // button on the composer would actually fire a real pipeline run
  // (charging the agent loop, polluting Reports). A capture-phase
  // listener swallows those clicks before the form submit handler
  // sees them, then advances the tour manually. Same treatment for
  // Enter in the composer textarea (the keyboard equivalent). In
  // demo mode the composer overlay already blocks both, so this is
  // belt-and-suspenders there.
  useEffect(() => {
    if (!open) return
    armedRef.current = false
    const armTimer = setTimeout(() => {
      armedRef.current = true
    }, 250)
    const handler = (e: MouseEvent) => {
      if (!armedRef.current) return
      const target = e.target as HTMLElement | null
      if (target?.closest('[data-tour-control]')) return
      const selection = window.getSelection()?.toString() ?? ''
      if (selection.length > 0) return
      advance()
    }
    const captureHandler = (e: MouseEvent) => {
      if (!armedRef.current) return
      const target = e.target as HTMLElement | null
      // Tour-control buttons (Skip / Back / Next) are always exempt
      // from any blocking — they live inside the tour overlay, not
      // in #view-new-session, but be defensive in case the markup
      // ever changes.
      if (target?.closest('[data-tour-control]')) return
      // Block ALL button clicks inside the New session view while
      // the tour is open. The tour demos these controls (suggestion
      // cards, submit, pipeline/model pickers) without actually
      // firing them — clicking would either pollute the composer or
      // submit a real pipeline run. Each blocked click still
      // advances the tour so the click-anywhere model is preserved.
      // Applies in both demo and live modes.
      if (
        target?.closest(
          '#view-new-session button, #view-new-session [role="button"], ' +
          '#view-agent-pipeline button, #view-agent-pipeline [role="button"]',
        )
      ) {
        e.preventDefault()
        e.stopPropagation()
        advance()
        return
      }
    }
    const keyHandler = (e: KeyboardEvent) => {
      if (!armedRef.current) return
      if (e.key !== 'Enter' || e.shiftKey) return
      const target = e.target as HTMLElement | null
      if (target?.closest('[data-tour-anchor="composer"]')) {
        e.preventDefault()
        e.stopPropagation()
        advance()
      }
    }
    document.addEventListener('click', captureHandler, true)
    document.addEventListener('keydown', keyHandler, true)
    document.addEventListener('click', handler, false)
    return () => {
      clearTimeout(armTimer)
      document.removeEventListener('click', captureHandler, true)
      document.removeEventListener('keydown', keyHandler, true)
      document.removeEventListener('click', handler, false)
    }
  }, [open, stepIdx])

  if (!open) return null

  return (
    <>
      {/* Centered-modal step (no anchor): full-screen dim + centered card */}
      {!step.anchor && (
        <div className="tour-fullscreen-dim">
          <CenteredCard
            step={step}
            stepIdx={stepIdx}
            totalSteps={steps.length}
            onBack={back}
            onSkip={finish}
            onNext={advance}
            isFirst={isFirst}
            isLast={isLast}
          />
        </div>
      )}

      {/* Anchored step: spotlight cutout + pulse ring + nearby tooltip */}
      {step.anchor && anchorRect && (
        <>
          <div
            className="tour-spotlight"
            style={spotlightStyle(anchorRect)}
          />
          <div
            className="tour-pulse"
            style={spotlightStyle(anchorRect)}
          />
          <Tooltip
            rect={anchorRect}
            step={step}
            stepIdx={stepIdx}
            totalSteps={steps.length}
            onBack={back}
            onSkip={finish}
            onNext={advance}
            isFirst={isFirst}
            isLast={isLast}
          />
        </>
      )}

      {/* While the anchor is still being located on an anchored step,
          show a transient dim so the screen doesn't flash undimmed. */}
      {step.anchor && !anchorRect && <div className="tour-fullscreen-dim" />}
    </>
  )
}

// Renders body copy as one or multiple paragraphs. Array entries become
// separate <p> elements so the welcome step can break the long pitch into
// two cleanly-spaced paragraphs without baking <br/> tags into the data.
function TourBody({ body, modifier }: { body: string | string[]; modifier: string }) {
  const paragraphs = Array.isArray(body) ? body : [body]
  return (
    <>
      {paragraphs.map((p, i) => (
        <p key={i} className={`tour-body ${modifier}`.trim()}>
          {p}
        </p>
      ))}
    </>
  )
}

function spotlightStyle(rect: DOMRect): React.CSSProperties {
  // 8px breathing room around the anchor.
  const pad = 8
  return {
    top: rect.top - pad,
    left: rect.left - pad,
    width: rect.width + pad * 2,
    height: rect.height + pad * 2,
  }
}

// ── Tooltip near the anchor ─────────────────────────────────────────────── //

interface TooltipProps {
  rect: DOMRect
  step: TourStep
  stepIdx: number
  totalSteps: number
  onBack: () => void
  onSkip: () => void
  onNext: () => void
  isFirst: boolean
  isLast: boolean
}

function Tooltip({ rect, step, stepIdx, totalSteps, onBack, onSkip, onNext, isFirst, isLast }: TooltipProps) {
  const width = 360
  const gap = 16
  const margin = 16
  // Default: below the anchor.
  let top = rect.bottom + gap
  // Estimated tooltip height — generous so we flip in time. Real height
  // can be a bit smaller; centered horizontally so vertical guess is fine.
  const estHeight = 220
  // Flip above if below would overflow the viewport.
  if (top + estHeight > window.innerHeight - margin) {
    top = Math.max(margin, rect.top - gap - estHeight)
  }
  let left = rect.left + rect.width / 2 - width / 2
  left = Math.max(margin, Math.min(window.innerWidth - width - margin, left))

  return (
    <div className="tour-tooltip" style={{ top, left, width }}>
      <div className="tour-step-indicator">
        Step {stepIdx + 1} of {totalSteps}
      </div>
      <h3 className="tour-headline">{step.headline}</h3>
      <TourBody body={step.body} modifier="" />
      <TourBottom
        isFirst={isFirst}
        isLast={isLast}
        onBack={onBack}
        onSkip={onSkip}
        onNext={onNext}
      />
    </div>
  )
}

// ── Centered modal (welcome step) ───────────────────────────────────────── //

interface CenteredCardProps {
  step: TourStep
  stepIdx: number
  totalSteps: number
  onBack: () => void
  onSkip: () => void
  onNext: () => void
  isFirst: boolean
  isLast: boolean
}

function CenteredCard({ step, stepIdx, totalSteps, onBack, onSkip, onNext, isFirst, isLast }: CenteredCardProps) {
  return (
    <div className="tour-modal">
      <div className="tour-step-indicator">
        Step {stepIdx + 1} of {totalSteps}
      </div>
      <h2 className="tour-headline tour-headline--modal">{step.headline}</h2>
      <TourBody body={step.body} modifier="tour-body--modal" />
      <TourBottom
        isFirst={isFirst}
        isLast={isLast}
        onBack={onBack}
        onSkip={onSkip}
        onNext={onNext}
      />
    </div>
  )
}

// Shared bottom row, modal-family layout: [Skip tour] flush left as
// the escape hatch, [Back] [Next/Done] flush right as the secondary
// + primary action pair. Mirrors the site's .modal-actions chrome
// (radius-md, accent primary, transparent secondary) but with Skip
// pulled to the opposite end so the cancel-ish action stays visually
// separate from the forward pair.
//
// The "Click anywhere to continue" hint only appears on the welcome
// step — by step 2 the model is established and the repeat is noise.
interface TourBottomProps {
  isFirst: boolean
  isLast: boolean
  onBack: () => void
  onSkip: () => void
  onNext: () => void
}

function TourBottom({ isFirst, isLast, onBack, onSkip, onNext }: TourBottomProps) {
  return (
    <div className="tour-bottom">
      <div className="tour-bottom-left">
        <button
          type="button"
          className="tour-btn"
          data-tour-control="skip"
          onClick={(e) => {
            e.stopPropagation()
            onSkip()
          }}
        >
          Skip tour
        </button>
      </div>
      <div className="tour-bottom-right">
        {/* On step 1, the hint sits immediately to the left of Next
            so it reads as an alternative to that button ("...or click
            anywhere") rather than as a label on Skip. Pairing the
            hint with the action it substitutes for matches scan order
            and clarifies that the click-anywhere model is equivalent
            to pressing Next. */}
        {isFirst && (
          <span className="tour-hint-inline">Click anywhere to continue</span>
        )}
        {!isFirst && (
          <button
            type="button"
            className="tour-btn"
            data-tour-control="back"
            onClick={(e) => {
              e.stopPropagation()
              onBack()
            }}
          >
            Back
          </button>
        )}
        <button
          type="button"
          className="tour-btn tour-btn--primary"
          data-tour-control="next"
          onClick={(e) => {
            e.stopPropagation()
            onNext()
          }}
        >
          {isLast ? 'Done' : 'Next'}
        </button>
      </div>
    </div>
  )
}
