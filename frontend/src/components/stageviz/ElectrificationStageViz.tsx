import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type {
  ElectrificationPlan,
  FSAOutcome,
  PipelineStage,
} from '../../api/types'
import {
  CATEGORICAL_COLORS,
  CHART_HOVER_CURSOR,
  CHART_LEGEND_STYLE,
  CHART_TOOLTIP_ITEM_STYLE,
  CHART_TOOLTIP_LABEL_STYLE,
  CHART_TOOLTIP_STYLE,
  VERDICT_COLOR as STYLE_VERDICT,
} from '../reportStyle'
import './stageviz.css'

// Per-stage viz dispatcher for the Neighborhood Electrification Readiness
// pipeline. Same chrome as WinterStageViz; data tailored to electrification.

const TITLES: Record<string, string> = {
  electrification_workload: 'Readiness scope',
  neighborhood_profile: 'FSA profiles',
  adoption_modeling: 'Per-FSA load impact',
  readiness_scoring: 'Readiness scores',
  electrification_synthesis: 'Final verdicts',
  completed: 'Final verdicts',
}

// Verdicts mirror the shared reportStyle palette so this stage panel reads
// the same as the final report's verdict chips.
const VERDICT_COLOR: Record<string, string> = {
  READY: STYLE_VERDICT.good,
  CONSTRAINED: STYLE_VERDICT.warning,
  BLOCKED: STYLE_VERDICT.critical,
}

export interface ElectrificationStageVizProps {
  stage: PipelineStage
  progress: number
  plan: ElectrificationPlan | null
}

export function ElectrificationStageViz({ stage, plan }: ElectrificationStageVizProps) {
  const body = (() => {
    if (!plan) return null
    switch (stage) {
      case 'electrification_workload':
        return <WorkloadSpecViz plan={plan} />
      case 'neighborhood_profile':
        return <NeighborhoodMixViz plan={plan} />
      case 'adoption_modeling':
        return <LoadImpactMiniViz plan={plan} />
      case 'readiness_scoring':
        return <ReadinessMiniViz plan={plan} />
      case 'electrification_synthesis':
      case 'completed':
        return <FinalVerdictsViz plan={plan} />
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

// ── Stage 1: Workload Intelligence ────────────────────────────────────── //

function WorkloadSpecViz({ plan }: { plan: ElectrificationPlan }) {
  const { spec } = plan
  const tiles = [
    { label: 'CITY', value: spec.city, sub: spec.province },
    { label: 'FSAS', value: String(spec.fsas.length), sub: spec.fsas.join(' · ') || '—' },
    { label: 'SCENARIOS', value: String(spec.scenarios.length), sub: spec.scenarios.map((s) => s.name).join(' · ') },
    { label: 'HORIZON', value: String(spec.horizon_year), sub: spec.scope.replace(/_/g, ' ') },
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

// ── Stage 2: Neighborhood Profile ─────────────────────────────────────── //

function NeighborhoodMixViz({ plan }: { plan: ElectrificationPlan }) {
  const profiles = plan.neighborhoods
  const totalHH = profiles.reduce((s, p) => s + p.households, 0)
  const tiles = [
    { label: 'FSAS LOADED', value: String(profiles.length) },
    { label: 'HOUSEHOLDS', value: totalHH.toLocaleString() },
    {
      label: 'AVG HDD18',
      value: profiles.length
        ? `${Math.round(profiles.reduce((s, p) => s + p.heating_degree_days_18c, 0) / profiles.length)}`
        : '—',
      sub: 'heating degree days',
    },
    {
      label: 'AVG INCOME',
      value: profiles.length
        ? `$${Math.round(profiles.reduce((s, p) => s + p.median_household_income_cad, 0) / profiles.length / 1000)}K`
        : '—',
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
      {profiles.some((p) => p.is_synthesized) && (
        <div style={{ marginTop: 8, fontSize: 11, color: 'var(--fg-3)' }}>
          ⓘ Some FSAs synthesized from province averages. See report for sources.
        </div>
      )}
    </>
  )
}

// ── Stage 3: Adoption Modeling ────────────────────────────────────────── //

function LoadImpactMiniViz({ plan }: { plan: ElectrificationPlan }) {
  // Pick the most aggressive scenario; aggregate per-FSA incremental MW.
  const scenarios = plan.spec.scenarios
  const target = scenarios.reduce(
    (acc, s) => (!acc || s.heat_pump_conversion_pct + s.ev_adoption_pct > acc.heat_pump_conversion_pct + acc.ev_adoption_pct ? s : acc),
    scenarios[0],
  )
  if (!target) return null
  const data = plan.fsa_outcomes
    .filter((o) => o.scenario.name === target.name)
    .map((o) => ({
      fsa: o.profile.fsa,
      hp_mw: Number((o.load_impact.peak_kw_per_household * o.profile.households / 2000).toFixed(1)),
      ev_mw: Number((o.load_impact.peak_kw_per_household * o.profile.households / 4000).toFixed(1)),
      total: Number(o.load_impact.incremental_peak_mw.toFixed(1)),
    }))

  return (
    <>
      <div style={{ marginBottom: 8, fontSize: 11, color: 'var(--fg-3)' }}>
        Worst-case scenario · <strong style={{ color: 'var(--fg-2)' }}>{target.label}</strong>
      </div>
      <div style={{ width: '100%', height: 200 }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
            <CartesianGrid stroke="#2a2824" />
            <XAxis dataKey="fsa" stroke="#6f6c63" tick={{ fontSize: 10 }} />
            <YAxis stroke="#6f6c63" tick={{ fontSize: 10 }} unit=" MW" />
            <Tooltip cursor={CHART_HOVER_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} itemStyle={CHART_TOOLTIP_ITEM_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
            <Legend wrapperStyle={CHART_LEGEND_STYLE} />
            <Bar dataKey="total" fill={CATEGORICAL_COLORS[1]} name="Incremental peak MW" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  )
}

// ── Stage 4: Readiness Scoring ────────────────────────────────────────── //

function ReadinessMiniViz({ plan }: { plan: ElectrificationPlan }) {
  const target = plan.spec.scenarios.reduce(
    (acc, s) => (!acc || s.heat_pump_conversion_pct + s.ev_adoption_pct > acc.heat_pump_conversion_pct + acc.ev_adoption_pct ? s : acc),
    plan.spec.scenarios[0],
  )
  if (!target) return null
  const items = plan.fsa_outcomes
    .filter((o) => o.scenario.name === target.name)
    .sort((a, b) => b.readiness.overall_score - a.readiness.overall_score)
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--fg-3)', marginBottom: 8 }}>
        Worst-case scenario · <strong style={{ color: 'var(--fg-2)' }}>{target.label}</strong>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {items.map((o) => {
          const r = o.readiness
          const c = VERDICT_COLOR[r.verdict] ?? '#b3b1a8'
          return (
            <div key={o.profile.fsa} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)', width: 36 }}>
                {o.profile.fsa}
              </span>
              <span style={{ flex: 1, fontSize: 12, color: 'var(--fg-1)' }}>
                {o.profile.label.split(' · ')[1] ?? o.profile.label}
              </span>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: c, fontWeight: 600 }}>
                {r.verdict}
              </span>
              <div style={{ width: 100, height: 6, background: '#2a2824', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{ width: `${Math.round(r.overall_score * 100)}%`, height: '100%', background: c }} />
              </div>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-2)', width: 40, textAlign: 'right' }}>
                {(r.overall_score * 100).toFixed(0)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Stage 5: Plan Synthesis ───────────────────────────────────────────── //

function FinalVerdictsViz({ plan }: { plan: ElectrificationPlan }) {
  // One column per scenario, listing FSA verdicts.
  const scenarios = plan.spec.scenarios
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${scenarios.length}, 1fr)`, gap: 10 }}>
      {scenarios.map((sc) => {
        const items = plan.fsa_outcomes
          .filter((o) => o.scenario.name === sc.name)
          .sort((a, b) => b.readiness.overall_score - a.readiness.overall_score)
        const headlineColor = items[0] ? VERDICT_COLOR[items[0].readiness.verdict] ?? '#b3b1a8' : '#b3b1a8'
        return (
          <div key={sc.name} style={{ background: 'var(--bg-2)', padding: 12, borderRadius: 4 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--fg-3)' }}>
              {sc.label.toUpperCase()}
            </div>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 12, color: headlineColor, fontWeight: 700, marginTop: 6 }}>
              {items[0]?.readiness.verdict ?? '—'}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 8 }}>
              {items.slice(0, 4).map((o) => (
                <FsaRow key={o.profile.fsa} o={o} />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function FsaRow({ o }: { o: FSAOutcome }) {
  const c = VERDICT_COLOR[o.readiness.verdict] ?? '#b3b1a8'
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
      <span style={{ fontFamily: 'var(--mono)', color: 'var(--fg-2)' }}>{o.profile.fsa}</span>
      <span style={{ color: c, fontFamily: 'var(--mono)' }}>{o.readiness.verdict}</span>
    </div>
  )
}
