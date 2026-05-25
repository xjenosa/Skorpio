// Central registry of in-flight demo theaters.
//
// Why this exists: previously `useFakeJobStream` kept its progression in
// React state inside PipelineLive. The moment the operator navigated away
// (e.g. back to New session to submit another demo), the component
// unmounted, the interval was cleared, and progress was lost. Coming back
// to that report restarted the timer from 0%, and a parallel "5 runs in
// flight" demo was impossible — at most one timer was ever alive.
//
// This module hoists the timers above React's lifecycle. Submitting a demo
// prompt starts a theater here (idempotent); the theater keeps advancing
// regardless of which view the operator is on. Components subscribe to
// updates by pipeline_id; unsubscribing on unmount doesn't stop the timer.

import type { PipelineStage } from '../api/types'
import type { PipelineId } from '../pipelines'
import { stageLabel, stageOrder } from '../components/pipelineConfigs'
import { markFixturePlayed } from '../hooks/useDemoMode'
import type { JobStreamState, LogLine } from '../hooks/useJobStream'

const PIPELINE_DURATION_MS: Record<PipelineId, number> = {
  'datacenter-siting': 18_000,
  'datacenter-expansion': 16_000,
  'winter-peak-stress': 22_000,
  'electrification-readiness': 20_000,
  'grid-investment-optimizer': 24_000,
}
const DEFAULT_DURATION_MS = 18_000
const TICK_MS = 250

const STAGE_LOG_LINE: Partial<Record<PipelineStage, string>> = {
  grid_analysis: 'Parsed workload spec and queued grid telemetry pull.',
  region_discovery: 'Filtered candidate regions on transmission and policy posture.',
  site_generation: 'Generated candidate site layouts.',
  scoring: 'Scored sites on cost, carbon, latency, headroom, speed, resilience.',
  plan_synthesis: 'Synthesizing the final ranked plan.',
  winter_workload: 'Parsed cold-event scenario from the prompt.',
  winter_grid: "Loaded the city's distribution network.",
  cold_event_sim: 'Simulated load under the cold event.',
  feeder_risk: 'Scored every feeder and substation for risk.',
  winter_synthesis: 'Synthesizing the resilience report.',
  electrification_workload: 'Parsed FSAs and target year.',
  neighborhood_profile: 'Pulled neighborhood demographics and heating mix.',
  adoption_modeling: 'Projected new electric load per FSA × scenario.',
  readiness_scoring: 'Scored grid headroom, building suitability, affordability.',
  electrification_synthesis: 'Synthesizing the readiness report.',
  investment_workload: 'Parsed utility, budget, and priority hazards.',
  asset_catalog: "Loaded the utility's at-risk grid assets.",
  climate_risk_modeling: 'Projected hazard exposure per asset.',
  portfolio_optimization: 'Ran the ROI knapsack against the budget.',
  investment_synthesis: 'Synthesizing the investment plan.',
  expansion_workload: 'Parsed operator footprint and target capacity.',
  operator_footprint: 'Loaded existing sites and live carbon intensity.',
  demand_forecast: 'Forecast annual MW demand under the workload mix.',
  expansion_scoring: 'Scored brownfield and greenfield expansion candidates.',
  expansion_synthesis: 'Synthesizing the expansion plan.',
}

export const INITIAL_THEATER_STATE: JobStreamState = {
  stage: 'queued',
  progress: 0,
  message: '',
  log: [],
  error: null,
  closed: false,
  paused: false,
}

interface TheaterRun {
  pipelineId: PipelineId
  stages: PipelineStage[]
  startMs: number
  durationMs: number
  intervalId: number
  state: JobStreamState
  done: boolean
}

const runs = new Map<PipelineId, TheaterRun>()
const pipelineListeners = new Map<PipelineId, Set<() => void>>()
const anyListeners = new Set<() => void>()

function nowHMS() {
  return new Date().toTimeString().slice(0, 8)
}

function notifyPipeline(pid: PipelineId) {
  pipelineListeners.get(pid)?.forEach((fn) => fn())
  anyListeners.forEach((fn) => fn())
}

// Start a theater for the given pipeline. Idempotent: calling it while a
// theater is already running (or already finished) is a no-op. The timer
// outlives the React component tree — it lives until completion, until
// `stopAllTheaters` is called, or until the tab is closed.
export function startTheater(pipelineId: PipelineId): void {
  const existing = runs.get(pipelineId)
  if (existing) return // already in-flight or already completed for this session

  const stages = stageOrder(pipelineId)
  const durationMs = PIPELINE_DURATION_MS[pipelineId] ?? DEFAULT_DURATION_MS
  const startMs = Date.now()
  const firstStage = stages[0] ?? 'queued'
  const firstLog: LogLine | null = STAGE_LOG_LINE[firstStage]
    ? { ts: nowHMS(), level: 'info', text: STAGE_LOG_LINE[firstStage]! }
    : null

  const run: TheaterRun = {
    pipelineId,
    stages,
    startMs,
    durationMs,
    intervalId: 0,
    state: {
      ...INITIAL_THEATER_STATE,
      stage: firstStage,
      message: stageLabel(pipelineId, firstStage),
      log: firstLog ? [firstLog] : [],
    },
    done: false,
  }
  runs.set(pipelineId, run)
  notifyPipeline(pipelineId)

  run.intervalId = window.setInterval(() => {
    const elapsed = Date.now() - run.startMs
    const ratio = Math.min(1, elapsed / run.durationMs)
    const stageIdx = Math.min(stages.length - 1, Math.floor(ratio * stages.length))
    const stage = stages[stageIdx] ?? 'queued'
    const progress = Math.round(ratio * 100)
    const justAdvanced = run.state.stage !== stage
    const nextLog: LogLine[] =
      justAdvanced && STAGE_LOG_LINE[stage]
        ? [...run.state.log, { ts: nowHMS(), level: 'info', text: STAGE_LOG_LINE[stage]! }]
        : run.state.log

    run.state = {
      ...run.state,
      stage,
      progress,
      message: stageLabel(pipelineId, stage),
      log: nextLog,
    }

    if (ratio >= 1) {
      window.clearInterval(run.intervalId)
      run.done = true
      run.state = {
        ...run.state,
        stage: 'completed',
        progress: 100,
        message: 'Completed',
        closed: true,
        log: [
          ...run.state.log,
          { ts: nowHMS(), level: 'ok', text: 'Pipeline complete.' },
        ],
      }
      notifyPipeline(pipelineId)
      // Mark fixture played so the parent view (which gates fakeStream on
      // !played) tears down the theater UI and reveals the real DB report.
      markFixturePlayed(pipelineId)
      return
    }

    notifyPipeline(pipelineId)
  }, TICK_MS)
}

export function getTheaterState(
  pipelineId: PipelineId | null | undefined,
): JobStreamState {
  if (!pipelineId) return INITIAL_THEATER_STATE
  return runs.get(pipelineId)?.state ?? INITIAL_THEATER_STATE
}

export function isTheaterRunning(
  pipelineId: PipelineId | null | undefined,
): boolean {
  if (!pipelineId) return false
  const run = runs.get(pipelineId)
  return !!run && !run.done
}

// Subscribe to updates for a single pipeline. Returns an unsubscribe fn.
// Unsubscribing does NOT stop the timer — the theater keeps progressing in
// the background until completion. Used by useFakeJobStream so PipelineLive
// re-renders on each tick.
export function subscribeTheater(pipelineId: PipelineId, cb: () => void): () => void {
  let set = pipelineListeners.get(pipelineId)
  if (!set) {
    set = new Set()
    pipelineListeners.set(pipelineId, set)
  }
  set.add(cb)
  return () => {
    set?.delete(cb)
  }
}

// Subscribe to ANY theater progress event. Used by aggregate views (Reports
// table, Dashboard) that need to re-render whenever any in-flight theater
// advances.
export function subscribeAnyTheater(cb: () => void): () => void {
  anyListeners.add(cb)
  return () => {
    anyListeners.delete(cb)
  }
}

// Cancel and drop a single pipeline's theater. Used by the demo-mode
// delete-report handler so re-submitting the prompt starts a fresh
// theater (startTheater is idempotent — without this, a leftover
// completed run would make re-submit a no-op).
export function stopTheater(pipelineId: PipelineId): void {
  const run = runs.get(pipelineId)
  if (!run) return
  window.clearInterval(run.intervalId)
  runs.delete(pipelineId)
  notifyPipeline(pipelineId)
}

// Cancel all in-flight theaters and drop their state. Called on demo
// toggle so flipping off → on starts every pipeline fresh.
export function stopAllTheaters(): void {
  for (const run of runs.values()) {
    window.clearInterval(run.intervalId)
  }
  runs.clear()
  // Fire one notification per pipeline + the any-listener so subscribers
  // re-render and see the cleared state.
  for (const set of pipelineListeners.values()) {
    set.forEach((fn) => fn())
  }
  anyListeners.forEach((fn) => fn())
}
