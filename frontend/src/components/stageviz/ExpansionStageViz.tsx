import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type {
  ExpansionPlan,
  PipelineStage,
} from '../../api/types'
import {
  CATEGORICAL_COLORS,
  CHART_TOOLTIP_ITEM_STYLE,
  CHART_TOOLTIP_LABEL_STYLE,
  CHART_TOOLTIP_STYLE,
  VERDICT_COLOR as STYLE_VERDICT,
} from '../reportStyle'
import './stageviz.css'

// Per-stage viz dispatcher for the Datacenter Expansion Planner.
// Same chrome as the other StageViz components; data tailored.

const TITLES: Record<string, string> = {
  expansion_workload: 'Expansion scope',
  operator_footprint: 'Operator footprint',
  demand_forecast: 'Demand projection',
  expansion_scoring: 'Scored options',
  expansion_synthesis: 'Phased rollout',
  completed: 'Phased rollout',
}

// Brownfield/greenfield colors mirror the final-report ExpansionReport so
// "green = brownfield expansion" reads the same in both layers.
const TYPE_COLOR: Record<string, string> = {
  brownfield: STYLE_VERDICT.good,
  greenfield: CATEGORICAL_COLORS[1],
}

export interface ExpansionStageVizProps {
  stage: PipelineStage
  progress: number
  plan: ExpansionPlan | null
}

export function ExpansionStageViz({ stage, plan }: ExpansionStageVizProps) {
  const body = (() => {
    if (!plan) return null
    switch (stage) {
      case 'expansion_workload':
        return <WorkloadSpecViz plan={plan} />
      case 'operator_footprint':
        return <FootprintViz plan={plan} />
      case 'demand_forecast':
        return <DemandViz plan={plan} />
      case 'expansion_scoring':
        return <ScoringMiniViz plan={plan} />
      case 'expansion_synthesis':
      case 'completed':
        return <RolloutViz plan={plan} />
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

function WorkloadSpecViz({ plan }: { plan: ExpansionPlan }) {
  const { spec } = plan
  const tiles = [
    { label: 'OPERATOR', value: spec.operator, sub: spec.province },
    { label: 'TARGET', value: `+${spec.target_additional_mw.toFixed(0)} MW`, sub: `${spec.horizon_years}y horizon` },
    { label: 'TARGET YEAR', value: String(spec.target_year), sub: spec.workload_mix.replace(/_/g, ' ') },
    { label: 'PREFERENCE', value: spec.prefer_brownfield ? 'Brownfield' : 'Open', sub: 'expansion mode' },
  ]
  return (
    <div className="viz-grid">
      {tiles.map((t) => (
        <div key={t.label} className="viz-tile">
          <div className="viz-tile-head">
            <span className="viz-tile-label">{t.label}</span>
          </div>
          <div style={{ padding: '8px 12px 12px' }}>
            <div style={{ fontFamily: 'var(--serif)', fontSize: 22, color: 'var(--fg-1)' }}>{t.value}</div>
            <div style={{ color: 'var(--fg-3)', fontSize: 11, marginTop: 2 }}>{t.sub}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Stage 2 ───────────────────────────────────────────────────────────── //

function FootprintViz({ plan }: { plan: ExpansionPlan }) {
  const sites = plan.footprint.sites
  const headroom = sites.reduce((s, x) => s + x.transformer_headroom_mw, 0)
  const tiles = [
    { label: 'SITES', value: String(sites.length) },
    { label: 'OPERATING MW', value: `${plan.footprint.total_current_capacity_mw.toFixed(0)}` },
    { label: 'HEADROOM', value: `${headroom.toFixed(0)} MW` },
    {
      label: 'AVG CARBON',
      value: sites.length
        ? `${Math.round(sites.reduce((s, x) => s + x.avg_carbon_g_kwh, 0) / sites.length)} g`
        : '—',
      sub: 'gCO₂eq / kWh (live)',
    },
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
              <div style={{ fontFamily: 'var(--serif)', fontSize: 22, color: 'var(--fg-1)' }}>{t.value}</div>
              {t.sub && <div style={{ color: 'var(--fg-3)', fontSize: 11, marginTop: 2 }}>{t.sub}</div>}
            </div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
        {sites.map((s) => (
          <div key={s.site_id} style={{ display: 'flex', gap: 8, fontSize: 11, color: 'var(--fg-2)' }}>
            <span style={{ fontFamily: 'var(--mono)', color: 'var(--fg-3)', width: 110 }}>{s.site_id}</span>
            <span style={{ flex: 1 }}>{s.name}</span>
            <span style={{ fontFamily: 'var(--mono)', color: 'var(--fg-3)' }}>
              {s.current_capacity_mw.toFixed(0)} MW · {s.cooling.replace(/_/g, ' ')}
            </span>
          </div>
        ))}
      </div>
    </>
  )
}

// ── Stage 3 ───────────────────────────────────────────────────────────── //

function DemandViz({ plan }: { plan: ExpansionPlan }) {
  const f = plan.demand_forecast
  const data = f.annual_demand_mw.map((mw, i) => ({
    year: `Y${i + 1}`,
    mw: Number(mw.toFixed(1)),
  }))
  data.unshift({ year: 'Y0', mw: Number(f.baseline_mw.toFixed(1)) })
  return (
    <>
      <div style={{ marginBottom: 8, fontSize: 11, color: 'var(--fg-3)' }}>
        {f.workload_mix.replace(/_/g, ' ')} · {(f.annual_growth_rate * 100).toFixed(0)}% CAGR
      </div>
      <div style={{ width: '100%', height: 180 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
            <CartesianGrid stroke="#2a2824" />
            <XAxis dataKey="year" stroke="#6f6c63" tick={{ fontSize: 10 }} />
            <YAxis stroke="#6f6c63" tick={{ fontSize: 10 }} unit=" MW" />
            <Tooltip contentStyle={CHART_TOOLTIP_STYLE} itemStyle={CHART_TOOLTIP_ITEM_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
            <Line type="monotone" dataKey="mw" stroke={CATEGORICAL_COLORS[1]} strokeWidth={1.8} dot={true} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {f.drivers.map((d, i) => (
          <span key={i} style={{
            fontSize: 10, padding: '4px 8px', borderRadius: 999,
            background: 'var(--bg-2)', color: 'var(--fg-2)',
          }}>
            {d}
          </span>
        ))}
      </div>
    </>
  )
}

// ── Stage 4 ───────────────────────────────────────────────────────────── //

function ScoringMiniViz({ plan }: { plan: ExpansionPlan }) {
  const top = [...plan.options].sort((a, b) => b.overall_score - a.overall_score).slice(0, 6)
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--fg-3)', marginBottom: 8 }}>
        Top {top.length} candidate options by overall score
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {top.map((o) => {
          const c = TYPE_COLOR[o.option_type] ?? '#b3b1a8'
          return (
            <div key={o.option_id} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)', width: 28 }}>
                #{o.rank}
              </span>
              <span style={{ flex: 1, fontSize: 12, color: 'var(--fg-1)' }}>{o.title}</span>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: c }}>{o.option_type}</span>
              <div style={{ width: 80, height: 6, background: '#2a2824', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{ width: `${Math.round(o.overall_score * 100)}%`, height: '100%', background: c }} />
              </div>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-2)', width: 40, textAlign: 'right' }}>
                {(o.overall_score * 100).toFixed(0)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Stage 5 ───────────────────────────────────────────────────────────── //

function RolloutViz({ plan }: { plan: ExpansionPlan }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${plan.phased_rollout.length}, 1fr)`, gap: 10 }}>
      {plan.phased_rollout.map((p) => (
        <div key={p.year} style={{ background: 'var(--bg-2)', padding: 12, borderRadius: 4 }}>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--fg-3)' }}>YEAR {p.year}</div>
          <div style={{ fontFamily: 'var(--serif)', fontSize: 18, color: 'var(--fg-1)', marginTop: 6 }}>
            {p.cumulative_new_mw.toFixed(0)} MW
          </div>
          <div style={{ color: 'var(--fg-3)', fontSize: 11, marginTop: 2 }}>
            ${(p.cumulative_capex_cad / 1e9).toFixed(2)}B cumulative
          </div>
          <div style={{ marginTop: 6, fontSize: 10, color: 'var(--fg-3)' }}>
            {p.options.length} option(s) commissioned
          </div>
        </div>
      ))}
    </div>
  )
}
