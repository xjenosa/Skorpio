import type {
  InvestmentPlan,
  PipelineStage,
} from '../../api/types'
import { CATEGORICAL_COLORS, VERDICT_COLOR as STYLE_VERDICT } from '../reportStyle'
import './stageviz.css'

// Per-stage viz dispatcher for the Climate-Adapted Grid Investment Optimizer.
// Same chrome as WinterStageViz / ElectrificationStageViz; data tailored.

const TITLES: Record<string, string> = {
  investment_workload: 'Investment scope',
  asset_catalog: 'Utility asset catalog',
  climate_risk_modeling: 'Per-asset climate risk',
  portfolio_optimization: 'Optimizer selections',
  investment_synthesis: 'Funded portfolio',
  completed: 'Funded portfolio',
}

// Risk tiers mirror the shared reportStyle palette + final-report colors
// so a "critical" tier reads identically here and in the report panel.
const TIER_COLOR: Record<string, string> = {
  critical: STYLE_VERDICT.critical,
  high:     STYLE_VERDICT.warning,
  medium:   CATEGORICAL_COLORS[3],   // lavender (informational)
  low:      STYLE_VERDICT.good,
}

export interface InvestmentStageVizProps {
  stage: PipelineStage
  progress: number
  plan: InvestmentPlan | null
}

export function InvestmentStageViz({ stage, plan }: InvestmentStageVizProps) {
  const body = (() => {
    if (!plan) return null
    switch (stage) {
      case 'investment_workload':
        return <WorkloadSpecViz plan={plan} />
      case 'asset_catalog':
        return <AssetCatalogViz plan={plan} />
      case 'climate_risk_modeling':
        return <RiskMiniViz plan={plan} />
      case 'portfolio_optimization':
        return <OptimizerMiniViz plan={plan} />
      case 'investment_synthesis':
      case 'completed':
        return <FundedPortfolioViz plan={plan} />
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

// ── Stage 1 ───────────────────────────────────────────────────────────── //

function WorkloadSpecViz({ plan }: { plan: InvestmentPlan }) {
  const { spec } = plan
  const tiles = [
    { label: 'UTILITY', value: spec.utility, sub: spec.province },
    { label: 'BUDGET', value: `$${(spec.budget_cad / 1e6).toFixed(0)}M`, sub: `${spec.horizon_years}y horizon` },
    { label: 'TARGET YEAR', value: String(spec.target_year), sub: 'climate scenario' },
    { label: 'PRIORITIES', value: String(spec.priority_hazards.length || 'all'), sub: spec.priority_hazards.join(' · ') || 'no filter' },
  ]
  return (
    <div className="viz-grid">
      {tiles.map((t) => (
        <div key={t.label} className="viz-tile">
          <div className="viz-tile-head">
            <span className="viz-tile-label">{t.label}</span>
          </div>
          <div style={{ padding: '8px 12px 12px' }}>
            <div style={{ fontFamily: 'var(--font-serif)', fontSize: 22, color: 'var(--fg-1)' }}>{t.value}</div>
            <div style={{ color: 'var(--fg-3)', fontSize: 11, marginTop: 2 }}>{t.sub}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Stage 2 ───────────────────────────────────────────────────────────── //

function AssetCatalogViz({ plan }: { plan: InvestmentPlan }) {
  const assets = plan.assets
  const byType = assets.reduce<Record<string, number>>((acc, a) => {
    acc[a.asset_type] = (acc[a.asset_type] ?? 0) + 1
    return acc
  }, {})
  const totalCustomers = assets.reduce((s, a) => s + a.customers_served, 0)
  const totalCost = assets.reduce((s, a) => s + a.replacement_cost_cad, 0)
  const tiles = [
    { label: 'ASSETS', value: String(assets.length) },
    { label: 'CRITICAL', value: String(assets.filter((a) => a.criticality === 'critical').length) },
    { label: 'CUSTOMERS', value: totalCustomers.toLocaleString() },
    { label: 'REPLACEMENT VAL', value: `$${(totalCost / 1e9).toFixed(2)}B` },
  ]
  return (
    <>
      <div className="viz-grid">
        {tiles.map((t) => (
          <div key={t.label} className="viz-tile">
            <div className="viz-tile-head">
              <span className="viz-tile-label">{t.label}</span>
            </div>
            <div style={{ padding: '8px 12px 12px' }}>
              <div style={{ fontFamily: 'var(--font-serif)', fontSize: 22, color: 'var(--fg-1)' }}>{t.value}</div>
            </div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {Object.entries(byType).map(([type, n]) => (
          <span key={type} style={{
            fontSize: 10, padding: '4px 8px', borderRadius: 999,
            background: 'var(--bg-2)', color: 'var(--fg-2)', fontFamily: 'var(--font-mono)',
          }}>
            {type.replace(/_/g, ' ')} · {n}
          </span>
        ))}
      </div>
    </>
  )
}

// ── Stage 3 ───────────────────────────────────────────────────────────── //

function RiskMiniViz({ plan }: { plan: InvestmentPlan }) {
  const top = [...plan.risk_profiles]
    .sort((a, b) => b.aggregate_annual_loss_cad - a.aggregate_annual_loss_cad)
    .slice(0, 6)
  const max = top[0]?.aggregate_annual_loss_cad ?? 1
  const byId = new Map(plan.assets.map((a) => [a.asset_id, a]))
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--fg-3)', marginBottom: 8 }}>
        Top {top.length} assets by projected annual loss ({plan.spec.target_year})
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {top.map((p) => {
          const c = TIER_COLOR[p.risk_tier] ?? '#b3b1a8'
          const name = byId.get(p.asset_id)?.name ?? p.asset_id
          const pct = Math.round((p.aggregate_annual_loss_cad / max) * 100)
          return (
            <div key={p.asset_id} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--fg-3)', width: 28 }}>
                #{p.rank}
              </span>
              <span style={{ flex: 1, fontSize: 12, color: 'var(--fg-1)' }}>{name}</span>
              <div style={{ width: 120, height: 6, background: '#2a2824', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: c }} />
              </div>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: c, width: 56, textAlign: 'right' }}>
                ${(p.aggregate_annual_loss_cad / 1e6).toFixed(1)}M
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Stage 4 ───────────────────────────────────────────────────────────── //

function OptimizerMiniViz({ plan }: { plan: InvestmentPlan }) {
  const top = plan.funded_projects.slice(0, 5)
  const tiles = [
    { label: 'CANDIDATES', value: String(plan.candidate_projects.length) },
    { label: 'FUNDED', value: String(plan.funded_projects.length) },
    { label: 'CAPEX', value: `$${(plan.total_capex_committed_cad / 1e6).toFixed(0)}M` },
    { label: 'AVOIDED/YR', value: `$${(plan.total_annual_loss_avoided_cad / 1e6).toFixed(1)}M` },
  ]
  return (
    <>
      <div className="viz-grid">
        {tiles.map((t) => (
          <div key={t.label} className="viz-tile">
            <div className="viz-tile-head">
              <span className="viz-tile-label">{t.label}</span>
            </div>
            <div style={{ padding: '8px 12px 12px' }}>
              <div style={{ fontFamily: 'var(--font-serif)', fontSize: 22, color: 'var(--fg-1)' }}>{t.value}</div>
            </div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
        {top.map((f) => (
          <div key={f.project.project_id} style={{ display: 'flex', gap: 8, fontSize: 11, color: 'var(--fg-2)' }}>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--fg-3)', width: 26 }}>#{f.rank}</span>
            <span style={{ flex: 1 }}>{f.project.title}</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>{f.roi_ratio.toFixed(1)}×</span>
          </div>
        ))}
      </div>
    </>
  )
}

// ── Stage 5 ───────────────────────────────────────────────────────────── //

function FundedPortfolioViz({ plan }: { plan: InvestmentPlan }) {
  const byCategory = plan.funded_projects.reduce<Record<string, number>>((acc, f) => {
    acc[f.project.category] = (acc[f.project.category] ?? 0) + f.project.capex_cad
    return acc
  }, {})
  const entries = Object.entries(byCategory).sort((a, b) => b[1] - a[1])
  const total = entries.reduce((s, [, v]) => s + v, 0) || 1
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10 }}>
      {entries.map(([cat, v]) => (
        <div key={cat} style={{ background: 'var(--bg-2)', padding: 12, borderRadius: 4 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--fg-3)' }}>
            {cat.replace(/_/g, ' ').toUpperCase()}
          </div>
          <div style={{ fontFamily: 'var(--font-serif)', fontSize: 20, color: 'var(--fg-1)', marginTop: 6 }}>
            ${(v / 1e6).toFixed(0)}M
          </div>
          <div style={{ color: 'var(--fg-3)', fontSize: 11, marginTop: 2 }}>
            {((v / total) * 100).toFixed(0)}% of capex
          </div>
        </div>
      ))}
    </div>
  )
}
