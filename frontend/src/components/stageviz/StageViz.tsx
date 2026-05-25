import type { PipelineStage, SitingPlan } from '../../api/types'
import { AnalysisSparklines } from './AnalysisSparklines'
import { ConstraintsFunnel } from './ConstraintsFunnel'
import { GenerationMap } from './GenerationMap'
import { ScoringPareto } from './ScoringPareto'
import { SynthesisRadarBar } from './SynthesisRadarBar'
import './stageviz.css'

// Maps the current `stream.stage` to its visualization. Every viz is driven
// purely by the completed `plan` — PipelineLive gates the panel on
// `hasRealData`, so no synthetic fallbacks live in here.
const TITLES: Record<string, string> = {
  grid_analysis: 'Regions analyzed',
  region_discovery: 'Constraint funnel',
  site_generation: 'Candidate map',
  scoring: 'Pareto front · cost vs. time to power',
  plan_synthesis: 'Ranked plan',
  completed: 'Final plan',
}

export interface StageVizProps {
  stage: PipelineStage
  progress: number
  plan: SitingPlan | null
}

export function StageViz({ stage, plan }: StageVizProps) {
  const body = (() => {
    switch (stage) {
      case 'grid_analysis':
        return <AnalysisSparklines plan={plan} />
      case 'region_discovery':
        return <ConstraintsFunnel plan={plan} />
      case 'site_generation':
        return <GenerationMap plan={plan} />
      case 'scoring':
        return <ScoringPareto plan={plan} />
      case 'plan_synthesis':
      case 'completed':
        return <SynthesisRadarBar plan={plan} />
      default:
        return null
    }
  })()
  const title = TITLES[stage] ?? 'Pipeline'
  return (
    <div className="stage-viz">
      <div className="stage-viz-head">
        <span className="t-eyebrow">{title}</span>
      </div>
      <div className="stage-viz-body">{body}</div>
    </div>
  )
}
