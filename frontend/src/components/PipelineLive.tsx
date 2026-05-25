import { useEffect, useMemo, useState } from 'react'
import { useJobStream, type JobStreamState } from '../hooks/useJobStream'
import { api } from '../api/client'
import type { ElectrificationPlan, ExpansionPlan, InvestmentPlan, JobStatus, PipelineStage, ResiliencePlan, SitingPlan } from '../api/types'
import { StageViz } from './stageviz/StageViz'
import { WinterStageViz } from './stageviz/WinterStageViz'
import { ElectrificationStageViz } from './stageviz/ElectrificationStageViz'
import { InvestmentStageViz } from './stageviz/InvestmentStageViz'
import { ExpansionStageViz } from './stageviz/ExpansionStageViz'
import { FinalReport } from './FinalReport'
import { stageDescription, stageLabel, stageOrder } from './pipelineConfigs'
import type { PipelineId } from '../pipelines'
import { useFakeJobStream } from '../demo/fakeStream'

export interface PipelineLiveProps {
  jobId: string | undefined
  // The pipeline producing this job's result. Drives the stage card labels,
  // per-stage viz dispatch, and which final-report shape to fetch. Defaults
  // to siting for backwards compatibility.
  pipelineId?: string
  // Forwarded to FinalReport's ReportChatBar so the topic picker can re-tag
  // the job's pipeline. The other 4 reports already receive this callback
  // directly from the AgentPipelineView; siting goes through PipelineLive
  // because it's the only one mounted by PipelineLive itself.
  onPipelineChange?: (pipelineId: PipelineId) => void
  // Demo theater: when true, drive stages from a local timer instead of SSE
  // and suppress real result fetching until onTheaterDone fires. Used to
  // fake an agent run on top of an already-completed historical job.
  fakeStream?: boolean
  onTheaterDone?: () => void
}

// Card-open state: 'auto' = follow the live stage; 'closed' = nothing open;
// a stage = user explicitly opened that card.
type CardState = 'auto' | 'closed' | PipelineStage

export function PipelineLive({
  jobId,
  pipelineId = 'datacenter-siting',
  onPipelineChange,
  fakeStream = false,
  onTheaterDone,
}: PipelineLiveProps) {
  // When the demo theater is active, pass `undefined` to useJobStream so it
  // doesn't open an SSE connection to the already-completed job. The fake
  // hook produces a matching-shape state from a local timer.
  const realStream = useJobStream(fakeStream ? undefined : jobId)
  const fakeStreamState: JobStreamState = useFakeJobStream({
    pipelineId: fakeStream ? (pipelineId as PipelineId) : null,
    active: fakeStream,
    onDone: onTheaterDone,
  })
  const stream: JobStreamState = fakeStream ? fakeStreamState : realStream
  const [job, setJob] = useState<JobStatus | null>(null)
  const [sitingPlan, setSitingPlan] = useState<SitingPlan | null>(null)
  const [winterPlan, setWinterPlan] = useState<ResiliencePlan | null>(null)
  const [electrificationPlan, setElectrificationPlan] = useState<ElectrificationPlan | null>(null)
  const [investmentPlan, setInvestmentPlan] = useState<InvestmentPlan | null>(null)
  const [expansionPlan, setExpansionPlan] = useState<ExpansionPlan | null>(null)
  // Initial cardState honors a tour-set localStorage hint so that
  // the 05 Plan Synthesis card opens immediately on remount during
  // the guided tour. Without this, switching tabs (e.g. Reports →
  // Agent Pipeline when backing from step 8 to step 7) unmounts
  // PipelineLive and resets the dropdown to closed, which then
  // briefly flashes closed before the tour's expand polling fires.
  // The tour sets the flag on step 7 entry and clears it when the
  // tour finishes or is skipped.
  const [cardState, setCardState] = useState<CardState>(() => {
    try {
      if (typeof window !== 'undefined' &&
          window.localStorage.getItem('skorpio.tour.card4Open') === '1') {
        return 'plan_synthesis'
      }
    } catch {}
    return 'auto'
  })

  const isSitingPipeline = pipelineId === 'datacenter-siting'
  const isWinterPipeline = pipelineId === 'winter-peak-stress'
  const isElectrificationPipeline = pipelineId === 'electrification-readiness'
  const isInvestmentPipeline = pipelineId === 'grid-investment-optimizer'
  const isExpansionPipeline = pipelineId === 'datacenter-expansion'

  // Per-pipeline stage chrome. Looked up once and memoized so the cards
  // don't rebuild on every stream tick.
  const stages = useMemo<PipelineStage[]>(() => stageOrder(pipelineId), [pipelineId])
  const labelOf = (s: PipelineStage) => stageLabel(pipelineId, s)
  const descOf = (s: PipelineStage) => stageDescription(pipelineId, s)

  useEffect(() => {
    if (!jobId || fakeStream) return
    api.getJob(jobId).then(setJob).catch(() => {})
  }, [jobId, fakeStream])

  // Refetch the job once it terminates so the persisted progress_log includes
  // the final stage entries that landed after the initial mount fetch.
  useEffect(() => {
    if (!jobId || fakeStream) return
    if (stream.stage !== 'completed' && stream.stage !== 'failed') return
    api.getJob(jobId).then(setJob).catch(() => {})
  }, [jobId, stream.stage, fakeStream])

  // Display log = persisted history from the server ∪ anything the live SSE
  // stream has appended since. Dedupe by text so we don't repeat lines that
  // are already in progress_log. Persisted comes first to anchor the order.
  const displayLog = useMemo(() => {
    const persisted = job?.progress_log ?? []
    const persistedTexts = new Set(persisted.map((e) => e.text))
    const liveOnly = stream.log.filter((e) => !persistedTexts.has(e.text))
    return [...persisted, ...liveOnly]
  }, [job?.progress_log, stream.log])

  // Fetch the appropriate result shape once the pipeline completes. Each
  // pipeline returns a different schema, so we route to the matching client.
  // Suppressed during demo theater so the final-report panels don't pop up
  // mid-animation; the parent re-mounts with fakeStream=false once theater
  // ends and the real fetch fires then.
  useEffect(() => {
    if (!jobId || stream.stage !== 'completed' || fakeStream) return
    if (isSitingPipeline) {
      api.getResults(jobId).then(setSitingPlan).catch(() => {})
    } else if (isWinterPipeline) {
      api.getWinterResults(jobId).then(setWinterPlan).catch(() => {})
    } else if (isElectrificationPipeline) {
      api.getElectrificationResults(jobId).then(setElectrificationPlan).catch(() => {})
    } else if (isInvestmentPipeline) {
      api.getInvestmentResults(jobId).then(setInvestmentPlan).catch(() => {})
    } else if (isExpansionPipeline) {
      api.getExpansionResults(jobId).then(setExpansionPlan).catch(() => {})
    }
  }, [jobId, stream.stage, fakeStream, isSitingPipeline, isWinterPipeline, isElectrificationPipeline, isInvestmentPipeline, isExpansionPipeline])

  const activeIdx = stages.indexOf(stream.stage)
  const isCompleted = stream.stage === 'completed'
  const liveCard: PipelineStage | null = activeIdx >= 0 ? stream.stage : null

  const visibleStage: PipelineStage | null =
    cardState === 'auto' ? liveCard : cardState === 'closed' ? null : cardState

  // Lock future stages (haven't started yet). They're visible in the timeline
  // but not expandable until reached. After the pipeline completes, every
  // stage is in the past and all unlock.
  const isLockedStage = (s: PipelineStage) => {
    if (isCompleted) return false
    const i = stages.indexOf(s)
    return i > activeIdx
  }

  // Real per-stage data only exists after the pipeline completes and the plan
  // has been fetched. Until then, the viz panel hides rather than show
  // placeholder/animated data unrelated to the agent's actual work.
  const planLoaded = isSitingPipeline
    ? sitingPlan !== null
    : isWinterPipeline
      ? winterPlan !== null
      : isElectrificationPipeline
        ? electrificationPlan !== null
        : isInvestmentPipeline
          ? investmentPlan !== null
          : isExpansionPipeline
            ? expansionPlan !== null
            : false
  const hasRealData = isCompleted && planLoaded

  const toggleCard = (stage: PipelineStage) => {
    if (isLockedStage(stage)) return
    setCardState(visibleStage === stage ? 'closed' : stage)
  }

  return (
    <>
      {stream.error && <div className="error-banner">Pipeline error: {stream.error}</div>}

      <div className="panel-pipeline">
        <div className="pp-head">
          <div>
            <div
              className={`live${stream.stage === 'completed' ? ' completed' : ''}${stream.stage === 'failed' ? ' failed' : ''}`}
            >
              {/* While the pipeline is running, the eyebrow leads with
                  "Live · <stage>" and the dot pulses orange (accent).
                  Once it lands on a TERMINAL state, the prefix flips
                  to "Status", the pulse stops, and the dot recolors:
                  green (`--ok`) for completed, terracotta (`--err`)
                  for failed. Traffic-light convention so a glance at
                  the dot tells the user the lifecycle state without
                  having to read the label. */}
              <i /> {stream.stage === 'completed' || stream.stage === 'failed' ? 'Status' : 'Live'} · {labelOf(stream.stage)}
            </div>
            <h2>{stream.message || job?.workload_spec || 'Awaiting first event…'}</h2>
          </div>
          <div className="meta">
            <span>Progress <strong>{stream.progress}%</strong></span>
          </div>
        </div>

        <div className="stages" data-tour-anchor="stages-row">
          {stages.map((stage, i) => {
            const isActive = i === activeIdx
            const isDone = i < activeIdx || isCompleted
            const isLocked = isLockedStage(stage)
            const isOpen = visibleStage === stage && !isLocked
            const width = isDone ? 100 : isActive ? Math.max(stream.progress, 5) : 0
            // Wrap each card so its viz panel can render inline directly under
            // it (mirrors the final report's .fr-section-wrap pattern). The
            // wrapper uses display:contents so the grid layout still sees the
            // button and panel as siblings.
            return (
              <div
                key={stage}
                className="pp-stage-wrap"
                // Wrapper anchor used by the guided tour's step 7 to
                // spotlight a card AND its expanded chart panel as a
                // single unit, after the per-card spotlight in step 6.
                data-tour-anchor={`stage-wrap-${i}`}
              >
                <button
                  type="button"
                  onClick={() => toggleCard(stage)}
                  disabled={isLocked}
                  aria-disabled={isLocked}
                  className={`stage-card${isActive ? ' live' : ''}${isOpen ? ' open' : ''}${isLocked ? ' locked' : ''}`}
                  aria-expanded={isOpen}
                  title={isLocked ? 'Not started yet' : undefined}
                  // Per-card tour anchor (stage-card-0 ... stage-card-4)
                  // for the step 6 spotlight animation that walks through
                  // each card before settling on the full stages-row.
                  data-tour-anchor={`stage-card-${i}`}
                >
                  <span className="corner tl" /><span className="corner tr" />
                  <span className="corner bl" /><span className="corner br" />
                  <span className="num">
                    {labelOf(stage)}
                    {isActive ? ' · Running' : isDone ? ' · Done' : isLocked ? ' · Pending' : ''}
                  </span>
                  <span className="label">{descOf(stage)}</span>
                  <div className="bar">
                    <i style={{ width: `${width}%` }} />
                  </div>
                  {!isLocked && (
                    <span className="stage-caret" aria-hidden>
                      {isOpen ? '▾' : '▸'}
                    </span>
                  )}
                </button>
                {isOpen && hasRealData && isSitingPipeline && (
                  <StageViz stage={stage} progress={stream.progress} plan={sitingPlan} />
                )}
                {isOpen && hasRealData && isWinterPipeline && (
                  <WinterStageViz stage={stage} progress={stream.progress} plan={winterPlan} />
                )}
                {isOpen && hasRealData && isElectrificationPipeline && (
                  <ElectrificationStageViz stage={stage} progress={stream.progress} plan={electrificationPlan} />
                )}
                {isOpen && hasRealData && isInvestmentPipeline && (
                  <InvestmentStageViz stage={stage} progress={stream.progress} plan={investmentPlan} />
                )}
                {isOpen && hasRealData && isExpansionPipeline && (
                  <ExpansionStageViz stage={stage} progress={stream.progress} plan={expansionPlan} />
                )}
                {isOpen && !hasRealData && (
                  <div className="stage-viz-pending">
                    <span className="t-eyebrow stage-viz-pending__eyebrow">
                      Processing<span className="stage-viz-pending__dot">.</span><span className="stage-viz-pending__dot">.</span><span className="stage-viz-pending__dot">.</span>
                    </span>
                    <p>Stage data will appear here once the agent finishes the run.</p>
                    <div className="stage-viz-pending__skeleton" aria-hidden="true">
                      <div className="skel skel--block" />
                      <div className="skel-row">
                        <div className="skel skel--bar" />
                        <div className="skel skel--bar" />
                      </div>
                      <div className="skel skel--line" />
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>

        <div className="pp-body">
          <div className="log">
            {displayLog.length === 0 && (
              <div className="line">
                <span className="t">--:--:--</span>
                <span className="lvl info">INFO</span>
                <span>Waiting for first event…</span>
              </div>
            )}
            {displayLog.map((line, i) => (
              <div className="line" key={i}>
                <span className="t">{line.ts}</span>
                <span className={`lvl ${line.level}`}>{line.level.toUpperCase()}</span>
                <span>{line.text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {sitingPlan && isSitingPipeline && jobId && (
        <FinalReport
          plan={sitingPlan}
          jobId={jobId}
          onPipelineChange={onPipelineChange}
        />
      )}
    </>
  )
}
