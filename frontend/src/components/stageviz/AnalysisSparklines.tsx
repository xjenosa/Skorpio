import type { SitingPlan } from '../../api/types'

// Stage 1 — Grid Analysis. Renders a tile per region the agent actually
// analyzed (from `plan.region_insights`), with the agent's market outlook
// blurb. The previous version showed synthetic random-walk sparklines with
// fabricated ISO names (PJM-WEST etc.); those were demo theatre and have
// no corresponding real data on `SitingPlan`, so the panel has been
// rebuilt around the data we actually have.

export interface AnalysisSparklinesProps {
  plan: SitingPlan | null
}

export function AnalysisSparklines({ plan }: AnalysisSparklinesProps) {
  if (!plan || plan.region_insights.length === 0) {
    return (
      <div className="stage-viz-pending">
        <span className="t-eyebrow">No data</span>
        <p>Region analysis will appear after the run finishes.</p>
      </div>
    )
  }
  return (
    <div className="viz-grid">
      {plan.region_insights.slice(0, 6).map((r) => (
        <div key={r.region_iso} className="viz-tile">
          <div className="viz-tile-head">
            <span className="viz-tile-label">{r.region_iso}</span>
            <span className="viz-tile-value">
              {r.top_sites.length}
              <small> sites</small>
            </span>
          </div>
          <div className="viz-tile-body">
            <p className="viz-tile-blurb">{r.market_outlook}</p>
          </div>
        </div>
      ))}
    </div>
  )
}
