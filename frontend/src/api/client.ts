import type {
  ChatMessage,
  ElectrificationPlan,
  ElectrificationRequest,
  ExpansionPlan,
  ExpansionRequest,
  ImportConflict,
  ImportResult,
  ImportStrategy,
  InvestmentPlan,
  InvestmentRequest,
  JobListItem,
  JobStatus,
  ResiliencePlan,
  SiteRequest,
  SiteResponse,
  SitingPlan,
  WinterPeakRequest,
} from './types'
import {
  isFixtureJobId,
  loadDemoJobList,
  loadDemoJobStatus,
  loadDemoResults,
} from '../demo/fixturesLoader'
import { isDemoModeActive } from '../hooks/useDemoMode'
import JSZip from 'jszip'

export const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? ''


// ── Demo intercept helpers ─────────────────────────────────────────────── //
//
// When demo mode is on AND the requested job_id matches one of the static
// fixtures bundled with the build, every read-side method returns the
// fixture instead of touching the network. This is what makes the Vercel
// deploy work — there's no backend reachable there, so any real call
// would 404.
//
// Write-side methods (submit*, chatStream) throw a clear error in demo
// mode so a typo doesn't silently hit a non-existent backend.

function demoFixtureForJob<T>(jobId: string, fixtureLoader: (id: string) => T | null): T | null {
  // Intentionally NOT gated on isDemoModeActive(). Fixture intercept fires
  // for any known fixture job_id, in any mode. This lets the Agent Pipeline
  // tab's empty-state Sample run (winter-peak fixture rendered as the
  // landing view) work outside demo mode too. Real jobs in the user's DB
  // have different UUIDs and fall through to the network as normal.
  if (!isFixtureJobId(jobId)) return null
  return fixtureLoader(jobId)
}

class DemoDisabledError extends Error {
  constructor(action: string) {
    super(`${action} is disabled in demo mode. Sign in for live runs.`)
  }
}

// ── Session token (Stage 2 auth) ───────────────────────────────────────── //
// Stored in localStorage so refreshes and same-origin tabs share it. Cleared
// on logout / 401. Read on every request to populate the Authorization header.

const TOKEN_KEY = 'skorpio.auth.token'

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return window.localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(TOKEN_KEY)
}

export interface MeResponse {
  id: string
  email: string
  name: string | null
  google_sub: string | null
  created_at: string
}

// Thrown by `request` on any non-2xx response. Preserves the raw status and
// the parsed JSON body (when possible) so callers can react to specific
// rejections — e.g. /api/route returns HTTP 400 with detail.error =
// "prompt_rejected" and a user-facing reason.
export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, statusText: string, path: string, body: unknown) {
    super(`${status} ${statusText} on ${path}${body ? `: ${typeof body === 'string' ? body : JSON.stringify(body)}` : ''}`)
    this.status = status
    this.body = body
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((init?.headers as Record<string, string>) || {}),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers })
  if (!res.ok) {
    const rawText = await res.text().catch(() => '')
    let parsed: unknown = rawText
    try { parsed = rawText ? JSON.parse(rawText) : rawText } catch { /* keep raw */ }
    throw new ApiError(res.status, res.statusText, path, parsed)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  submitSiting: (req: SiteRequest) => {
    if (isDemoModeActive()) throw new DemoDisabledError('Submitting a new siting run')
    return request<SiteResponse>('/api/site', { method: 'POST', body: JSON.stringify(req) })
  },

  submitWinterPeak: (req: WinterPeakRequest) => {
    if (isDemoModeActive()) throw new DemoDisabledError('Submitting a new winter-peak run')
    return request<SiteResponse>('/api/winter-peak', { method: 'POST', body: JSON.stringify(req) })
  },

  listWinterPeakCities: () =>
    request<{ cities: { key: string; city: string; utility: string; province: string }[] }>(
      '/api/winter-peak/cities',
    ),

  listColdEvents: () =>
    request<{ events: { event_id: string; name: string; min_temp_c: number | null; duration_hours: number | null; blurb: string }[] }>(
      '/api/winter-peak/cold-events',
    ),

  submitElectrification: (req: ElectrificationRequest) => {
    if (isDemoModeActive()) throw new DemoDisabledError('Submitting a new electrification run')
    return request<SiteResponse>('/api/electrification', { method: 'POST', body: JSON.stringify(req) })
  },

  listElectrificationFsas: () =>
    request<{ fsas: { fsa: string; label: string; city: string; province: string; households: number }[] }>(
      '/api/electrification/fsas',
    ),

  getElectrificationResults: (jobId: string) => {
    const fixture = demoFixtureForJob(jobId, loadDemoResults)
    if (fixture) return Promise.resolve(fixture as ElectrificationPlan)
    return request<ElectrificationPlan>(`/api/results/${jobId}`)
  },

  submitInvestment: (req: InvestmentRequest) => {
    if (isDemoModeActive()) throw new DemoDisabledError('Submitting a new investment run')
    return request<SiteResponse>('/api/investment', { method: 'POST', body: JSON.stringify(req) })
  },

  listInvestmentUtilities: () =>
    request<{ utilities: { key: string; name: string; province: string; asset_count: number }[] }>(
      '/api/investment/utilities',
    ),

  getInvestmentResults: (jobId: string) => {
    const fixture = demoFixtureForJob(jobId, loadDemoResults)
    if (fixture) return Promise.resolve(fixture as InvestmentPlan)
    return request<InvestmentPlan>(`/api/results/${jobId}`)
  },

  submitExpansion: (req: ExpansionRequest) => {
    if (isDemoModeActive()) throw new DemoDisabledError('Submitting a new expansion run')
    return request<SiteResponse>('/api/expansion', { method: 'POST', body: JSON.stringify(req) })
  },

  listExpansionOperators: () =>
    request<{ operators: { key: string; name: string; site_count: number; total_mw: number; provinces: string[] }[] }>(
      '/api/expansion/operators',
    ),

  getExpansionResults: (jobId: string) => {
    const fixture = demoFixtureForJob(jobId, loadDemoResults)
    if (fixture) return Promise.resolve(fixture as ExpansionPlan)
    return request<ExpansionPlan>(`/api/results/${jobId}`)
  },

  getJob: (jobId: string) => {
    const fixture = demoFixtureForJob(jobId, loadDemoJobStatus)
    if (fixture) return Promise.resolve(fixture)
    return request<JobStatus>(`/api/jobs/${jobId}`)
  },

  getResults: (jobId: string) => {
    const fixture = demoFixtureForJob(jobId, loadDemoResults)
    if (fixture) return Promise.resolve(fixture as SitingPlan)
    return request<SitingPlan>(`/api/results/${jobId}`)
  },

  getWinterResults: (jobId: string) => {
    const fixture = demoFixtureForJob(jobId, loadDemoResults)
    if (fixture) return Promise.resolve(fixture as ResiliencePlan)
    return request<ResiliencePlan>(`/api/results/${jobId}`)
  },

  listJobs: () => {
    // In demo mode, the Reports table + the demo-job-id resolver both
    // call listJobs(). Serve the 5 baked-in fixtures so neither path
    // touches the backend (and so the Reports table actually has rows
    // to display on Vercel).
    if (isDemoModeActive()) return Promise.resolve(loadDemoJobList())
    return request<JobListItem[]>('/api/jobs')
  },

  arxivSearch: (q: string, max = 5) =>
    request<unknown[]>(`/api/arxiv/search?q=${encodeURIComponent(q)}&max=${max}`),

  health: () => request<{ status: string }>('/health'),

  // JSON bundle export — returns a Blob the caller can hand to
  // URL.createObjectURL for a synthetic download link. Server returns
  // application/json when len(jobIds) === 1 and application/zip when > 1;
  // the filename comes from the Content-Disposition header in both cases
  // so the saved file has the correct extension automatically.
  exportJobsBundle: async (opts: { jobIds: string[]; fromEmail?: string }) => {
    if (!opts.jobIds.length) throw new Error('exportJobsBundle requires at least one jobId')
    const token = getToken()
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res = await fetch(`${BASE_URL}/api/jobs/export-bundle`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        job_ids: opts.jobIds,
        from_email: opts.fromEmail || null,
      }),
    })
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      throw new Error(`Export failed: ${res.status}${body ? `. ${body}` : ''}`)
    }
    const filename = (() => {
      const cd = res.headers.get('Content-Disposition') || ''
      const m = cd.match(/filename="?([^";]+)"?/i)
      // Fallback uses the count to pick the right extension if the server
      // omitted the header for some reason.
      return m?.[1] || (opts.jobIds.length === 1 ? 'skorpio-report.json' : 'skorpio-reports.zip')
    })()
    return { blob: await res.blob(), filename }
  },

  // Client-side bundle export. Builds the same envelope shape as the
  // backend `/api/jobs/export-bundle` endpoint, but assembles it
  // entirely in the browser from (a) the JobListItem rows already in
  // state and (b) per-job result blobs fetched via the existing
  // `/api/results/<id>` reads (or the demo fixture intercept). Output
  // file format is identical to the backend exporter — single .json
  // for one report, .zip of N .json files for N>1 — so anything
  // exported here round-trips cleanly into the backend's
  // `/api/jobs/import-reports` endpoint.
  exportJobsBundleLocal: async (opts: {
    jobs: JobListItem[]
    fromEmail?: string
  }): Promise<{ blob: Blob; filename: string }> => {
    if (!opts.jobs.length) throw new Error('exportJobsBundleLocal requires at least one job')
    const exportedAt = new Date().toISOString()

    const envelopes = await Promise.all(
      opts.jobs.map(async (job) => {
        // Honor the demo fixture intercept first (matches every other
        // result-fetching method in this file) so demo-mode exports
        // stay off the network. Non-demo falls through to the real
        // /api/results/<id> read. A missing result (failed run, still
        // in-flight) is packed as null — mirrors backend
        // _serialize_report which just emits whatever job.result is.
        const result = await (async () => {
          const fixture = demoFixtureForJob(job.job_id, loadDemoResults)
          if (fixture) return fixture as unknown
          try {
            return await request<unknown>(`/api/results/${job.job_id}`)
          } catch {
            return null
          }
        })()

        return {
          skorpio_export_version: 1,
          exported_at: exportedAt,
          exported_by: opts.fromEmail || null,
          job: {
            job_id: job.job_id,
            workload_spec: job.workload_spec,
            pipeline_id: job.pipeline_id || null,
            stage: job.stage,
            progress: job.progress,
            created_at: job.created_at || null,
          },
          result,
        }
      }),
    )

    if (envelopes.length === 1) {
      const blob = new Blob([JSON.stringify(envelopes[0], null, 2)], {
        type: 'application/json',
      })
      return {
        blob,
        filename: `skorpio-report-${opts.jobs[0].job_id.slice(0, 8)}.json`,
      }
    }

    const zip = new JSZip()
    for (const env of envelopes) {
      zip.file(
        `skorpio-report-${env.job.job_id.slice(0, 8)}.json`,
        JSON.stringify(env, null, 2),
      )
    }
    const blob = await zip.generateAsync({ type: 'blob' })
    // Match backend's filename shape: skorpio-reports-YYYYMMDD-HHMMSS.zip
    const compact = exportedAt.replace(/[-:]/g, '').replace('T', '-').slice(0, 15)
    return { blob, filename: `skorpio-reports-${compact}.zip` }
  },

  // Multi-file report import — accepts a FileList (one or more .json
  // files), uploads them in a single multipart request. Returns either
  // the result counts (200) or, on first try when conflicts exist, a
  // 409 carrying the conflict list. Caller surfaces conflicts in a
  // resolution dialog and retries with strategies.
  importReports: async (
    files: File[],
    strategies?: Record<string, ImportStrategy>,
  ): Promise<{ ok: true; data: ImportResult } | { ok: false; conflicts: ImportConflict[] }> => {
    if (!files.length) throw new Error('importReports requires at least one file')
    const fd = new FormData()
    // FastAPI's `list[UploadFile] = File(...)` reads multiple values from
    // the same `files` form key — repeat the append per file.
    for (const f of files) fd.append('files', f)
    if (strategies) fd.append('strategies', JSON.stringify(strategies))
    // Auth: every other write-side call goes through `request()` which
    // attaches the Bearer token from localStorage. We're using bare
    // `fetch()` here because FormData needs a multipart Content-Type
    // that `request()` would clobber — so attach the token manually.
    // Without it, an auth-gated /api/jobs/import-reports returns 401
    // and the conflict dialog never has a chance to render.
    const token = getToken()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res = await fetch(`${BASE_URL}/api/jobs/import-reports`, {
      method: 'POST',
      headers,
      body: fd,
    })
    // Log status + a short body excerpt so when "the dialog didn't show"
    // happens, the developer can open the browser console and see what
    // status the server actually returned. Cheap and always-on.
    const peekBody = await res.clone().text().catch(() => '')
    console.info('[importReports]', res.status, peekBody.slice(0, 200))
    if (res.status === 409) {
      const body = (await res.json()) as { conflicts: ImportConflict[] }
      return { ok: false, conflicts: body.conflicts }
    }
    if (!res.ok) {
      throw new Error(`Import failed: ${res.status}${peekBody ? `. ${peekBody}` : ''}`)
    }
    return { ok: true, data: (await res.json()) as ImportResult }
  },


  // SSE helpers — return an EventSource the caller manages.
  streamProgress: (jobId: string) => new EventSource(`${BASE_URL}/api/stream/${jobId}`),

  pauseJob: (jobId: string) =>
    request<{ job_id: string; paused: boolean }>(`/api/jobs/${jobId}/pause`, { method: 'POST' }),

  resumeJob: (jobId: string) =>
    request<{ job_id: string; paused: boolean }>(`/api/jobs/${jobId}/resume`, { method: 'POST' }),

  // Cancel a running job. Lands at the next stage boundary; the job ends up
  // in the "failed" stage with message "Cancelled by user".
  cancelJob: (jobId: string) =>
    request<{ job_id: string; cancelled: boolean }>(`/api/jobs/${jobId}/cancel`, { method: 'POST' }),

  // Delete a job + its persisted result. Server is idempotent so a 204
  // response (no body) is the success signal.
  deleteJob: (jobId: string) =>
    request<void>(`/api/jobs/${jobId}`, { method: 'DELETE' }),

  // Re-tag a job's pipeline. Used by the "change" pickers in the Routed-to
  // pill and Reports row badges. The persisted result blob isn't touched —
  // the caller should refresh the jobs list and let the report viewer
  // re-route based on the new pipeline_id.
  updateJobPipeline: (jobId: string, pipelineId: string) =>
    request<{ job_id: string; pipeline_id: string }>(
      `/api/jobs/${jobId}/pipeline`,
      { method: 'PATCH', body: JSON.stringify({ pipeline_id: pipelineId }) },
    ),

  // Live grid carbon for an ElectricityMaps zone (e.g. "CA-ON"). Returns
  // null when the backend has no key configured or no data — callers should
  // render a "—" placeholder rather than fail.
  gridCarbon: async (zone: string): Promise<{
    zone: string
    g_co2_per_kwh: number
    datetime: string
    source: string
  } | null> => {
    const res = await fetch(`${BASE_URL}/api/grid-carbon/${encodeURIComponent(zone)}`)
    if (!res.ok) return null
    const body = (await res.json()) as { data_missing?: boolean } & Record<string, unknown>
    if (body.data_missing) return null
    return body as { zone: string; g_co2_per_kwh: number; datetime: string; source: string }
  },

  // Live weather for a supported Canadian city. Same null-when-unavailable
  // contract as gridCarbon.
  weather: async (city: string): Promise<{
    temp_c: number
    humidity: number
    wind_speed_ms: number
    condition: string
    city: string
    source: string
  } | null> => {
    const res = await fetch(`${BASE_URL}/api/weather?city=${encodeURIComponent(city)}`)
    if (!res.ok) return null
    const body = (await res.json()) as { data_missing?: boolean } & Record<string, unknown>
    if (body.data_missing) return null
    return body as {
      temp_c: number
      humidity: number
      wind_speed_ms: number
      condition: string
      city: string
      source: string
    }
  },

  // Operator metrics for the Dashboard — counts, success rate, avg duration,
  // pipeline mix, daily runs, recent failures.
  operatorMetrics: (timeframeHours: number = 24) =>
    request<{
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
    }>(`/api/metrics?timeframe_hours=${timeframeHours}`),

  // Claude-powered pipeline router. ~1s Haiku call that classifies a free-
  // form prompt into one of the 5 pipelines. Returns `source: "regex-
  // fallback"` when the Claude call failed and a keyword guess was used.
  routePrompt: (prompt: string, model?: string) =>
    request<{
      pipeline_id: string | null
      confidence: number
      rationale: string
      source: 'claude' | 'regex-fallback'
      off_topic?: boolean
      multi_location?: boolean
      reject_reason?: string | null
    }>('/api/route', {
      method: 'POST',
      body: JSON.stringify(model ? { prompt, model } : { prompt }),
    }),

  // ── Auth (Stage 2) ──────────────────────────────────────────────────── //
  requestEmailCode: (email: string) =>
    request<{ status: string; expires_in_minutes: number }>(
      '/api/auth/email/request-code',
      { method: 'POST', body: JSON.stringify({ email }) },
    ),

  verifyEmailCode: (email: string, code: string) =>
    request<{ token: string; user: MeResponse }>(
      '/api/auth/email/verify-code',
      { method: 'POST', body: JSON.stringify({ email, code }) },
    ),

  getMe: () => request<MeResponse>('/api/auth/me'),

  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),

  // Google OAuth is a full-page redirect (the browser must follow Google's
  // redirect back), so callers use this URL with `window.location.href`.
  googleLoginUrl: (redirectTo: string = '/') =>
    `${BASE_URL}/api/auth/google/login?redirect_to=${encodeURIComponent(redirectTo)}`,

  // Chat is POST-then-stream — fetch with body, parse SSE manually. The
  // optional `model` param overrides the backend's default Claude model.
  // `onCorrection`, when provided, receives the full reconciled text the
  // backend emits if it found numeric drift in Claude's reply; callers
  // should replace the assistant message content with that string so the
  // user never sees the hallucinated value persist after the stream ends.
  chatStream: async (
    jobId: string,
    messages: ChatMessage[],
    model: string | undefined,
    onText: (t: string) => void,
    onCorrection?: (full: string) => void,
  ) => {
    // ReportChatBar already swaps to a "demo mode — chat disabled" notice
    // when demo is on, so this guard is defensive. If a caller somehow
    // reaches here in demo mode, throw a clear error rather than letting
    // the fetch 404 silently on Vercel.
    if (isDemoModeActive()) {
      throw new DemoDisabledError('Follow-up chat')
    }
    const body: Record<string, unknown> = { messages }
    if (model) body.model = model
    const res = await fetch(`${BASE_URL}/api/chat/${jobId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok || !res.body) throw new Error(`Chat stream failed: ${res.status}`)
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (payload === '[DONE]') return
        try {
          const obj = JSON.parse(payload) as { text?: string; corrected?: string }
          if (obj.text) onText(obj.text)
          if (obj.corrected && onCorrection) onCorrection(obj.corrected)
        } catch {
          // ignore malformed line
        }
      }
    }
  },
}
