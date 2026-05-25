import type { SitingPlan } from '../../api/types'

// Stage 2 — Constraints. Real funnel built from the completed plan's counts:
// regions analyzed → regions with insights → sites generated → sites scored.
// This panel only renders post-completion (PipelineLive gates on `hasRealData`),
// so the plan is always present in practice.

export interface ConstraintsFunnelProps {
  plan: SitingPlan | null
}

export function ConstraintsFunnel({ plan }: ConstraintsFunnelProps) {
  if (!plan) {
    return (
      <div className="stage-viz-pending">
        <span className="t-eyebrow">No data</span>
        <p>Constraint counts will appear after the run finishes.</p>
      </div>
    )
  }
  const tiers: Array<{ label: string; count: number }> = [
    { label: 'Regions analyzed', count: plan.regions_analyzed },
    { label: 'Regions with insights', count: plan.region_insights.length },
    { label: 'Sites generated', count: plan.sites_generated },
    { label: 'Sites scored', count: plan.sites_scored },
  ]
  const max = Math.max(...tiers.map((t) => t.count), 1)
  return (
    <div className="viz-funnel">
      {tiers.map((s, i) => {
        const widthPct = Math.max(20, Math.round((s.count / max) * 100))
        const isFirst = i === 0
        return (
          <div className="funnel-row" key={s.label}>
            <div
              className="funnel-bar"
              style={{
                width: `${widthPct}%`,
                background: isFirst ? 'var(--bg-3)' : 'var(--accent-soft)',
                borderColor: isFirst ? 'var(--rule-2)' : 'var(--accent-line)',
              }}
            >
              <span className="funnel-label">{s.label}</span>
              <span
                className="funnel-count"
                style={{ color: isFirst ? 'var(--fg-2)' : 'var(--accent)' }}
              >
                {s.count}
              </span>
            </div>
            {i < tiers.length - 1 && <div className="funnel-arrow">▼</div>}
          </div>
        )
      })}
    </div>
  )
}
