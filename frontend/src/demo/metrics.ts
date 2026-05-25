// Synthesizes the same shape `api.operatorMetrics()` returns, but derived
// entirely from the in-browser demo state (submitted + played flags). Used
// by the Dashboard tab in demo mode so the stats reflect a fresh-run feel:
// 0 runs until the operator submits anything, climbing one-by-one as each
// pipeline's theater finishes.

import { PIPELINES, type PipelineId } from '../pipelines'
import { DEMO_JOB_PREFIXES } from './jobs'
import { isFixtureSubmitted, isFixturePlayed } from '../hooks/useDemoMode'

// Mirror of fakeStream's per-pipeline theater duration. Inlined rather than
// imported so the Dashboard doesn't pull React-coupled timer code.
const PIPELINE_DURATION_MS: Record<PipelineId, number> = {
  'datacenter-siting': 18_000,
  'datacenter-expansion': 16_000,
  'winter-peak-stress': 22_000,
  'electrification-readiness': 20_000,
  'grid-investment-optimizer': 24_000,
}

export interface DemoDashboardMetrics {
  as_of: string
  timeframe_hours: number
  total_runs: number
  active_runs: number
  runs_in_window: number
  completed_in_window: number
  failed_in_window: number
  success_rate: number | null
  avg_duration_seconds: number | null
  pipeline_mix: Array<{ pipeline_id: string; label: string; count: number }>
  daily_run_counts: Array<{ date: string; count: number }>
  recent_failures: Array<{
    job_id: string
    workload_spec: string
    pipeline_id: string | null
    error: string
    updated_at: string | null
  }>
}

export function buildDemoMetrics(timeframeHours: number): DemoDashboardMetrics {
  const allPids = DEMO_JOB_PREFIXES.map((d) => d.pipelineId)
  const submittedPids = allPids.filter((pid) => isFixtureSubmitted(pid))
  const playedPids = submittedPids.filter((pid) => isFixturePlayed(pid))

  const total = submittedPids.length
  const completed = playedPids.length
  const active = total - completed
  const success_rate = total > 0 ? completed / total : null
  const avg_duration_seconds =
    completed > 0
      ? playedPids.reduce(
          (sum, pid) => sum + (PIPELINE_DURATION_MS[pid] ?? 20_000),
          0,
        ) /
        completed /
        1000
      : null

  // Pipeline mix counts each played pipeline once (one demo job per pipeline).
  // Submitted-but-not-yet-played pipelines are excluded so the mix matches
  // "completed runs", matching the backend's semantics.
  const pipeline_mix = playedPids.map((pid) => {
    const meta = PIPELINES.find((p) => p.id === pid)
    return { pipeline_id: pid, label: meta?.label ?? pid, count: 1 }
  })

  // Strip ms + 'Z' so toLocaleTimeString below doesn't double-apply UTC
  // — the dashboard does `new Date(metrics.as_of + 'Z')` so we feed it the
  // naive-ISO format the backend uses.
  const as_of = new Date().toISOString().slice(0, 19)
  const todayDate = new Date().toISOString().slice(0, 10)

  return {
    as_of,
    timeframe_hours: timeframeHours,
    total_runs: total,
    active_runs: active,
    runs_in_window: total,
    completed_in_window: completed,
    failed_in_window: 0,
    success_rate,
    avg_duration_seconds,
    pipeline_mix,
    daily_run_counts: total > 0 ? [{ date: todayDate, count: total }] : [],
    recent_failures: [],
  }
}
