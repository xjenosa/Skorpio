import { useEffect, useState } from 'react'

const STORAGE_KEY = 'skorpio.demoMode'
const PLAYED_PREFIX = 'skorpio.demo.played.'
const SUBMITTED_PREFIX = 'skorpio.demo.submitted.'
const EVENT_NAME = 'skorpio:demoMode'

// Build-time flag: set in Vercel's project settings as VITE_DEMO_ONLY=true.
// When true, demo mode is permanently ON and the toggle is hidden — the
// Vercel deploy has no backend reachable, so turning demo off would just
// produce a broken /login page that can't actually authenticate anyone.
// On local dev (where the var is undefined), the toggle behaves normally.
export const DEMO_LOCKED: boolean =
  (typeof import.meta !== 'undefined' &&
    (import.meta as { env?: Record<string, string | undefined> }).env?.VITE_DEMO_ONLY === 'true') ||
  false

function readStored(): boolean {
  if (typeof window === 'undefined') return false
  // Lock wins: when VITE_DEMO_ONLY=true the demo flag is always read as on,
  // regardless of what's in localStorage. Guarantees a refresh on a Vercel
  // tab keeps the demo experience even if the user somehow flipped it off.
  if (DEMO_LOCKED) return true
  return window.localStorage.getItem(STORAGE_KEY) === '1'
}

// Wipe all per-fixture demo state (played + submitted flags + the
// demo-scoped lastOpenedJob). Called whenever the toggle flips so the next
// "on" starts with an empty Reports table, unplayed theater, and no
// auto-restored Agent pipeline job. Live's lastOpenedJob is on a separate
// key and is never touched here.
function clearDemoFixtureState() {
  if (typeof window === 'undefined') return
  const keys: string[] = []
  for (let i = 0; i < window.localStorage.length; i++) {
    const k = window.localStorage.key(i)
    if (k && (k.startsWith(PLAYED_PREFIX) || k.startsWith(SUBMITTED_PREFIX))) {
      keys.push(k)
    }
  }
  keys.forEach((k) => window.localStorage.removeItem(k))
  window.localStorage.removeItem('skorpio.demo.lastOpenedJob')
}

// Subscribed across mounts so the bottom-right toggle and any in-page reader
// (HomePage composer, intercept layer, etc.) all see the same value without
// having to thread props or set up a context provider.
export function useDemoMode(): [boolean, (next: boolean | ((prev: boolean) => boolean)) => void] {
  const [demo, setDemo] = useState<boolean>(readStored)

  useEffect(() => {
    if (typeof window === 'undefined') return
    const onChange = (e: Event) => {
      const detail = (e as CustomEvent<{ value: boolean }>).detail
      if (detail && typeof detail.value === 'boolean') setDemo(detail.value)
    }
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setDemo(e.newValue === '1')
    }
    window.addEventListener(EVENT_NAME, onChange as EventListener)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(EVENT_NAME, onChange as EventListener)
      window.removeEventListener('storage', onStorage)
    }
  }, [])

  const update = (next: boolean | ((prev: boolean) => boolean)) => {
    // Hard-lock on Vercel: silently ignore any attempt to flip demo off
    // when VITE_DEMO_ONLY=true. The toggle is hidden in that environment,
    // but a programmatic setDemo() call from elsewhere in the app would
    // still hit this code path — reject it so the demo can't break itself.
    if (DEMO_LOCKED) return
    const resolved = typeof next === 'function' ? (next as (p: boolean) => boolean)(demo) : next
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, resolved ? '1' : '0')
      // Wipe only on a real transition. Calling setDemo(true) while already
      // on (e.g. a stray dispatch) must NOT nuke an in-progress demo's
      // submitted/played flags or its Agent pipeline last-opened.
      if (resolved !== demo) clearDemoFixtureState()
      window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: { value: resolved } }))
    }
    setDemo(resolved)
  }

  return [demo, update]
}

// Non-hook read for code paths that can't use hooks (e.g. inside the
// imperative API client's request guard).
export function isDemoModeActive(): boolean {
  return readStored()
}

const PLAYED_EVENT = 'skorpio:demoPlayed'
const SUBMITTED_EVENT = 'skorpio:demoSubmitted'

export function markFixturePlayed(pipelineId: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(PLAYED_PREFIX + pipelineId, '1')
  window.dispatchEvent(new CustomEvent(PLAYED_EVENT, { detail: { pipelineId } }))
}

export function isFixturePlayed(pipelineId: string): boolean {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(PLAYED_PREFIX + pipelineId) === '1'
}

// "Submitted" flag — set when the operator picks a card or types a prompt
// and clicks Run in demo mode. Controls whether the matching demo entry is
// visible in the Reports table. (Distinct from "played", which controls
// whether theater plays vs. skipping to the finished report.)
export function markFixtureSubmitted(pipelineId: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(SUBMITTED_PREFIX + pipelineId, '1')
  window.dispatchEvent(new CustomEvent(SUBMITTED_EVENT, { detail: { pipelineId } }))
}

export function isFixtureSubmitted(pipelineId: string): boolean {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(SUBMITTED_PREFIX + pipelineId) === '1'
}

// Inverse of mark*. Used by the demo-mode delete-report handler so the
// row vanishes from Reports but the underlying fixture can be re-submitted
// from the New session tab to re-appear (and re-play theater). Dispatches
// the same events as the mark* helpers so listeners (Reports table memo,
// useFixturePlayed) re-read localStorage and re-render.
export function unmarkFixtureSubmitted(pipelineId: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(SUBMITTED_PREFIX + pipelineId)
  window.dispatchEvent(new CustomEvent(SUBMITTED_EVENT, { detail: { pipelineId } }))
}

export function unmarkFixturePlayed(pipelineId: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(PLAYED_PREFIX + pipelineId)
  window.dispatchEvent(new CustomEvent(PLAYED_EVENT, { detail: { pipelineId } }))
}

// Subscribe to a single pipeline's played state so the Reports table can
// re-render a row from "processing" to "completed" the moment theater ends.
export function useFixturePlayed(pipelineId: string | null | undefined): boolean {
  const [played, setPlayed] = useState<boolean>(() =>
    pipelineId ? isFixturePlayed(pipelineId) : false,
  )
  useEffect(() => {
    if (!pipelineId || typeof window === 'undefined') return
    setPlayed(isFixturePlayed(pipelineId))
    const onChange = (e: Event) => {
      // Re-read localStorage on every PLAYED_EVENT (not just set true) so
      // unmarkFixturePlayed correctly drives the hook back to false. The
      // event no longer carries the new value — listeners infer it from
      // storage, which is the source of truth.
      const detail = (e as CustomEvent<{ pipelineId: string }>).detail
      if (detail?.pipelineId === pipelineId) setPlayed(isFixturePlayed(pipelineId))
    }
    const onDemo = () => setPlayed(isFixturePlayed(pipelineId))
    window.addEventListener(PLAYED_EVENT, onChange as EventListener)
    window.addEventListener(EVENT_NAME, onDemo as EventListener)
    return () => {
      window.removeEventListener(PLAYED_EVENT, onChange as EventListener)
      window.removeEventListener(EVENT_NAME, onDemo as EventListener)
    }
  }, [pipelineId])
  return played
}

// Ticking counter that bumps on any demo-fixture event (submit / played /
// demo-mode change). Used by views that aggregate across all 5 pipelines
// — e.g. the Reports table — so a single useMemo can recompute when any
// of the flags change without iterating per-pipeline hooks.
export function useDemoFixtureTick(): number {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (typeof window === 'undefined') return
    const bump = () => setTick((t) => t + 1)
    window.addEventListener(SUBMITTED_EVENT, bump)
    window.addEventListener(PLAYED_EVENT, bump)
    window.addEventListener(EVENT_NAME, bump)
    return () => {
      window.removeEventListener(SUBMITTED_EVENT, bump)
      window.removeEventListener(PLAYED_EVENT, bump)
      window.removeEventListener(EVENT_NAME, bump)
    }
  }, [])
  return tick
}
