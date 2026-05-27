// Demo-mode job-id config.
//
// Each entry maps a pipeline to the 8-char prefix of a real historical
// job_id kept in the live DB. On first use, `resolveDemoJobIds()` calls
// `api.listJobs()`, finds the full UUIDs by prefix, and caches them under
// `localStorage["skorpio.demo.jobIds"]`. Subsequent reads hit the cache.
//
// Why prefixes instead of full UUIDs: the operator can re-run a job and
// rotate prefixes faster than they can copy a full UUID. Prefixes also
// match the format the user keeps in their notes.

import { api } from '../api/client'
import type { PipelineId } from '../pipelines'

export interface DemoJobConfig {
  pipelineId: PipelineId
  prefix: string
}

export const DEMO_JOB_PREFIXES: DemoJobConfig[] = [
  { pipelineId: 'datacenter-siting', prefix: '49d354bd' },
  { pipelineId: 'datacenter-expansion', prefix: 'ce0585bf' },
  { pipelineId: 'winter-peak-stress', prefix: 'e5d77262' },
  { pipelineId: 'electrification-readiness', prefix: 'f4b26d6a' },
  { pipelineId: 'grid-investment-optimizer', prefix: '2621702d' },
]

const CACHE_KEY = 'skorpio.demo.jobIds'

export type DemoJobMap = Partial<Record<PipelineId, string>>

// Self-healing cache validation. A historical commit (c3eb47f) swapped the
// siting/investment prefixes; any browser that loaded the swapped version
// wrote a permanently-wrong mapping into localStorage that `resolveDemoJobIds`
// then refused to rewrite (it's cache-first). This guard validates each
// cached entry against the current `DEMO_JOB_PREFIXES` source of truth on
// every read — entries whose UUID doesn't start with the prefix the
// source-of-truth claims get dropped, then the cleaned map is re-persisted.
// Side effect: next call to `resolveDemoJobIds` re-fetches the dropped
// entries from the live API, so the user heals automatically without
// having to clear localStorage by hand.
function validateAgainstPrefixes(map: DemoJobMap): {
  clean: DemoJobMap
  dropped: PipelineId[]
} {
  const validPrefixByPipeline = new Map<PipelineId, string>(
    DEMO_JOB_PREFIXES.map((d) => [d.pipelineId, d.prefix]),
  )
  const clean: DemoJobMap = {}
  const dropped: PipelineId[] = []
  for (const [pid, uuid] of Object.entries(map) as Array<[PipelineId, string]>) {
    const expectedPrefix = validPrefixByPipeline.get(pid)
    if (expectedPrefix && uuid.startsWith(expectedPrefix)) {
      clean[pid] = uuid
    } else {
      dropped.push(pid)
    }
  }
  return { clean, dropped }
}

function readCache(): DemoJobMap | null {
  if (typeof window === 'undefined') return null
  const raw = window.localStorage.getItem(CACHE_KEY)
  if (!raw) return null
  let parsed: DemoJobMap
  try {
    parsed = JSON.parse(raw) as DemoJobMap
  } catch {
    return null
  }
  const { clean, dropped } = validateAgainstPrefixes(parsed)
  // Only re-persist when validation actually removed something — keeps
  // the happy path a pure read with no extra writes.
  if (dropped.length > 0) {
    try {
      window.localStorage.setItem(CACHE_KEY, JSON.stringify(clean))
      // eslint-disable-next-line no-console
      console.info(
        '[demo/jobs] dropped stale cache entries (UUID/prefix mismatch):',
        dropped,
      )
    } catch {
      // Storage write failed (quota / private mode). The in-memory
      // `clean` map is still returned, so this load behaves correctly;
      // the next load will re-validate from the still-stale raw blob.
    }
  }
  return clean
}

function writeCache(map: DemoJobMap) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(CACHE_KEY, JSON.stringify(map))
}

export function clearDemoJobCache() {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(CACHE_KEY)
}

// Returns the cached full UUID for a pipeline's demo job, or null if it
// hasn't been resolved yet. Synchronous — for use in render paths.
export function getDemoJobId(pipelineId: PipelineId): string | null {
  const cache = readCache()
  return cache?.[pipelineId] ?? null
}

// Reverse lookup: is this job_id one of the 5 demo jobs? Used by Reports
// filtering and the PipelinePage to decide whether to play fake progress.
export function isDemoJobId(jobId: string | null | undefined): boolean {
  if (!jobId) return false
  const cache = readCache()
  if (!cache) return false
  return Object.values(cache).includes(jobId)
}

// Reverse lookup: pipeline_id for a demo job. Null if not a demo job.
export function pipelineForDemoJobId(jobId: string | null | undefined): PipelineId | null {
  if (!jobId) return null
  const cache = readCache()
  if (!cache) return null
  for (const [pid, jid] of Object.entries(cache)) {
    if (jid === jobId) return pid as PipelineId
  }
  return null
}

// One-shot resolver: fetches /api/jobs, matches each prefix to a full UUID,
// caches the result. Idempotent — safe to call multiple times. Returns the
// full map (cached + freshly resolved).
//
// Errors bubble up. Callers should surface a clear "demo job not found"
// message rather than silently degrade — a missing demo job mid-pitch is a
// bug worth seeing.
export async function resolveDemoJobIds(): Promise<DemoJobMap> {
  const cache = readCache() ?? {}
  const missing = DEMO_JOB_PREFIXES.filter((d) => !cache[d.pipelineId])
  if (missing.length === 0) return cache

  const jobs = await api.listJobs()
  for (const { pipelineId, prefix } of missing) {
    const match = jobs.find((j) => j.job_id.startsWith(prefix))
    if (match) cache[pipelineId] = match.job_id
  }
  writeCache(cache)
  return cache
}

// Diagnostic: which pipelines couldn't be resolved? Used by an in-app
// warning banner so the operator notices before the demo, not during.
export function unresolvedDemoPipelines(): PipelineId[] {
  const cache = readCache() ?? {}
  return DEMO_JOB_PREFIXES.filter((d) => !cache[d.pipelineId]).map((d) => d.pipelineId)
}
