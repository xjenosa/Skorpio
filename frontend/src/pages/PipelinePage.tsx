import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { PipelineLive } from '../components/PipelineLive'
import { WinterPeakReport } from '../components/WinterPeakReport'
import { ElectrificationReport } from '../components/ElectrificationReport'
import { InvestmentReport } from '../components/InvestmentReport'
import { ExpansionReport } from '../components/ExpansionReport'
import { SmoothStage } from '../components/SmoothStage'
import { api } from '../api/client'
import type { JobStatus } from '../api/types'
import { useDemoMode, useFixturePlayed, markFixturePlayed } from '../hooks/useDemoMode'
import { isDemoJobId, pipelineForDemoJobId } from '../demo/jobs'

const TERMINAL: ReadonlySet<string> = new Set(['completed', 'failed'])

export function PipelinePage() {
  const { jobId } = useParams<{ jobId: string }>()
  const [job, setJob] = useState<JobStatus | null>(null)
  const [demoMode] = useDemoMode()
  // Determine demo theater state up-front so child fetches stay suppressed
  // until the fake progression finishes.
  const demoPipelineId = pipelineForDemoJobId(jobId)
  const played = useFixturePlayed(demoPipelineId)
  const isDemoTheater = demoMode && isDemoJobId(jobId) && !played

  // Poll job status until terminal so the result panels appear when ready.
  // Skipped during demo theater so the real "completed" state doesn't leak
  // into the page header mid-animation.
  useEffect(() => {
    if (!jobId || isDemoTheater) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const tick = async () => {
      try {
        const j = await api.getJob(jobId)
        if (cancelled) return
        setJob(j)
        if (TERMINAL.has(j.stage)) return
        timer = setTimeout(tick, 2_000)
      } catch {
        // swallow — keep last known state visible
      }
    }
    void tick()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [jobId, isDemoTheater])

  // Pipeline_id is the source of truth; fall back to inference from prompt
  // text for legacy rows that predate the pipeline_id column. In demo
  // theater the real job hasn't been fetched yet, so trust the demo map.
  const pipelineId =
    (isDemoTheater ? demoPipelineId : null) ??
    job?.pipeline_id ??
    inferPipelineFromPrompt(job?.workload_spec ?? '')

  const onTheaterDone = () => {
    if (demoPipelineId) markFixturePlayed(demoPipelineId)
  }

  return (
    <div className="app">
      <aside className="sidebar" aria-label="Primary">
        <div className="sidebar-head">
          <Link className="brand" to="/" aria-label="Skorpio">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#1f1e1d"/><g transform="translate(6.25, 3) scale(0.8125)"><path d="M12 0 C 12 8, 22 14, 22 22 A 10 10 0 1 1 2 22 C 2 14, 12 8, 12 0 Z" fill="#F38764"/></g></svg>
            <span className="wordmark">SKORPIO</span>
          </Link>
        </div>
        <Link to="/" className="nav-item">← Back to console</Link>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div className="crumbs">
            <span className="live">
              <span className="dot" /> Grid · Live
            </span>
            <span className="sep">/</span>
            <span className="here">Run {jobId?.slice(0, 8)}</span>
          </div>
        </header>

        <SmoothStage style={{ justifyContent: 'flex-start' }}>
          <div className="view active">
            <div className="page-head">
              <div>
                <h1 className="title">
                  <em>Agent</em> pipeline
                </h1>
                <div className="sub">{isDemoTheater ? 'Running…' : job?.workload_spec ?? 'Loading…'}</div>
              </div>
              <div className="actions">
                <Link to="/" style={{ display: 'inline-block', padding: '10px 14px' }}>
                  Console ›
                </Link>
              </div>
            </div>

            <PipelineLive
              jobId={jobId}
              pipelineId={pipelineId}
              fakeStream={isDemoTheater}
              onTheaterDone={onTheaterDone}
            />

            {!isDemoTheater && jobId && pipelineId === 'winter-peak-stress' && (
              <WinterPeakReport jobId={jobId} hasResults={!!job?.has_results} />
            )}
            {!isDemoTheater && jobId && pipelineId === 'electrification-readiness' && (
              <ElectrificationReport jobId={jobId} hasResults={!!job?.has_results} />
            )}
            {!isDemoTheater && jobId && pipelineId === 'grid-investment-optimizer' && (
              <InvestmentReport jobId={jobId} hasResults={!!job?.has_results} />
            )}
            {!isDemoTheater && jobId && pipelineId === 'datacenter-expansion' && (
              <ExpansionReport jobId={jobId} hasResults={!!job?.has_results} />
            )}
          </div>
        </SmoothStage>
      </main>
    </div>
  )
}

// Local copy of HomePage's inference so we don't have to refactor that out
// just for one usage. Keep in sync with HomePage.tsx.
function inferPipelineFromPrompt(prompt: string): string {
  const p = prompt.toLowerCase()
  if (/(polar vortex|cold snap|winter peak|stress[- ]?test|cold weather|-\s?\d{2}\s?°?c)/.test(p)) {
    return 'winter-peak-stress'
  }
  if (/(neighborhood|electrification|fsa|postal|heat pump|ev (adoption|growth)|score (the|a) [a-z])/.test(p)) {
    return 'electrification-readiness'
  }
  if (/(invest|budget|allocate|spend|\$\d|grid upgrade)/.test(p)) {
    return 'grid-investment-optimizer'
  }
  if (/(expansion|expand|grow capacity|add capacity|next phase)/.test(p)) {
    return 'datacenter-expansion'
  }
  return 'datacenter-siting'
}
