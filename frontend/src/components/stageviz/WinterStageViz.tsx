import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { PipelineStage, ResiliencePlan, ScenarioOutcome } from '../../api/types'
import {
  CATEGORICAL_COLORS,
  CHART_TOOLTIP_ITEM_STYLE,
  CHART_TOOLTIP_LABEL_STYLE,
  CHART_TOOLTIP_STYLE,
  VERDICT_COLOR as STYLE_VERDICT,
} from '../reportStyle'
import './stageviz.css'

// Per-stage viz dispatcher for the Winter Peak Stress Tester pipeline.
// Mirrors the role of StageViz (which is siting-specific). Each case
// renders a compact panel showing the data produced by that stage.

const TITLES: Record<string, string> = {
  winter_workload: 'Stress-test spec',
  winter_grid: 'Distribution network',
  cold_event_sim: 'Hourly load curve',
  feeder_risk: 'Top at-risk feeders',
  winter_synthesis: 'Scenario verdicts',
  completed: 'Resilience verdict',
}

// Local alias to keep call sites compact — semantics pulled from the
// shared reportStyle so this stage viz reads the same as the final report.
const VERDICT_COLOR: Record<string, string> = {
  PASS: STYLE_VERDICT.good,
  MARGINAL: STYLE_VERDICT.warning,
  FAIL: STYLE_VERDICT.critical,
}

export interface WinterStageVizProps {
  stage: PipelineStage
  progress: number
  plan: ResiliencePlan | null
}

export function WinterStageViz({ stage, plan }: WinterStageVizProps) {
  const body = (() => {
    if (!plan) return null
    switch (stage) {
      case 'winter_workload':
        return <WorkloadSpecViz plan={plan} />
      case 'winter_grid':
        return <NetworkSummaryViz plan={plan} />
      case 'cold_event_sim':
        return <LoadCurveMiniViz plan={plan} />
      case 'feeder_risk':
        return <FeederRiskMiniViz plan={plan} />
      case 'winter_synthesis':
      case 'completed':
        return <ScenarioVerdictViz plan={plan} />
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

function WorkloadSpecViz({ plan }: { plan: ResiliencePlan }) {
  const { spec, cold_event } = plan
  const tiles = [
    { label: 'CITY', value: spec.city, sub: spec.utility ?? '' },
    {
      label: 'COLD EVENT',
      value: cold_event.name.split(' ').slice(0, 2).join(' '),
      sub: `${cold_event.min_temp_c.toFixed(1)}°C × ${cold_event.duration_hours}h`,
    },
    { label: 'SCENARIOS', value: String(spec.scenarios.length), sub: spec.scenarios.map((s) => s.name).join(' · ') },
    { label: 'HORIZON', value: String(spec.horizon_year), sub: 'adoption target year' },
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

// ── Stage 2: Grid Intelligence ────────────────────────────────────────── //

function NetworkSummaryViz({ plan }: { plan: ResiliencePlan }) {
  const { network } = plan
  const customers = network.feeders.reduce((s, f) => s + f.customer_count, 0)
  const tiles = [
    { label: 'SUBSTATIONS', value: String(network.substations.length) },
    { label: 'FEEDERS', value: String(network.feeders.length) },
    { label: 'CUSTOMERS', value: customers.toLocaleString() },
    { label: 'WINTER PEAK', value: `${network.baseline_winter_peak_mw.toFixed(0)} MW`, sub: `baseline ${network.baseline_year}` },
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
      {network.is_synthesized && (
        <div style={{ marginTop: 8, fontSize: 11, color: 'var(--fg-3)' }}>
          ⓘ Per-feeder values modeled from {network.sources.length} public source(s).
        </div>
      )}
    </>
  )
}

// ── Stage 3: Cold-Event Simulation ────────────────────────────────────── //

function LoadCurveMiniViz({ plan }: { plan: ResiliencePlan }) {
  // Show the temperature curve from the cold event itself (always available)
  const tempData = plan.cold_event.hourly_curve.map((h) => ({
    hour: h.hour_offset,
    temp: h.temp_c,
  }))
  const peakLoads = plan.scenarios.map((s) => ({
    name: s.scenario.label,
    peak: s.load_profile.peak_load_mw,
    headroom: s.load_profile.headroom_pct_at_peak,
    color: VERDICT_COLOR[s.summary_verdict] ?? '#b3b1a8',
  }))
  return (
    <>
      <div style={{ width: '100%', height: 160 }}>
        <ResponsiveContainer>
          <LineChart data={tempData} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
            <CartesianGrid stroke="#2a2824" />
            <XAxis dataKey="hour" stroke="#6f6c63" tick={{ fontSize: 10 }} />
            <YAxis stroke="#6f6c63" tick={{ fontSize: 10 }} unit="°C" />
            <Tooltip contentStyle={CHART_TOOLTIP_STYLE} itemStyle={CHART_TOOLTIP_ITEM_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
            <Line type="monotone" dataKey="temp" stroke={CATEGORICAL_COLORS[1]} strokeWidth={1.8} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${peakLoads.length}, 1fr)`, gap: 8, marginTop: 8 }}>
        {peakLoads.map((p) => (
          <div key={p.name} style={{ background: 'var(--bg-2)', padding: 10, borderRadius: 4 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--fg-3)' }}>
              {p.name.toUpperCase()}
            </div>
            <div style={{ fontFamily: 'var(--serif)', fontSize: 18, color: p.color, marginTop: 4 }}>
              {p.peak.toFixed(0)} MW
            </div>
            <div style={{ color: 'var(--fg-3)', fontSize: 10 }}>{p.headroom.toFixed(0)}% headroom</div>
          </div>
        ))}
      </div>
    </>
  )
}

// ── Stage 4: Risk Scoring ─────────────────────────────────────────────── //

function FeederRiskMiniViz({ plan }: { plan: ResiliencePlan }) {
  const worst = pickWorstScenario(plan.scenarios)
  if (!worst) return null
  const top = worst.feeder_risks.slice(0, 5)
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--fg-3)', marginBottom: 8 }}>
        Worst case · <strong style={{ color: 'var(--fg-2)' }}>{worst.scenario.label}</strong> ·
        {' '}{worst.feeder_risks.filter((f) => f.overload_risk >= 0.5).length} feeder(s) at risk
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {top.map((fr) => {
          const c = fr.overload_risk >= 0.8 ? STYLE_VERDICT.critical : fr.overload_risk >= 0.5 ? STYLE_VERDICT.warning : STYLE_VERDICT.good
          return (
            <div key={fr.feeder_id} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)', width: 24 }}>
                #{fr.rank}
              </span>
              <span style={{ flex: 1, fontSize: 12, color: 'var(--fg-1)' }}>{fr.feeder_name}</span>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--fg-3)' }}>
                {fr.capacity_utilization_pct.toFixed(0)}% util
              </span>
              <div style={{ width: 100, height: 6, background: '#2a2824', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{ width: `${Math.min(100, fr.overload_risk * 100)}%`, height: '100%', background: c }} />
              </div>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: c, width: 36, textAlign: 'right' }}>
                {(fr.overload_risk * 100).toFixed(0)}%
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Stage 5: Plan Synthesis ───────────────────────────────────────────── //

function ScenarioVerdictViz({ plan }: { plan: ResiliencePlan }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${plan.scenarios.length}, 1fr)`, gap: 10 }}>
      {plan.scenarios.map((s) => {
        const c = VERDICT_COLOR[s.summary_verdict] ?? '#b3b1a8'
        return (
          <div key={s.scenario.name} style={{ background: 'var(--bg-2)', padding: 12, borderRadius: 4 }}>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--fg-3)' }}>
              {s.scenario.label.toUpperCase()}
            </div>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 12, color: c, fontWeight: 700, marginTop: 6 }}>
              {s.summary_verdict}
            </div>
            <div style={{ fontFamily: 'var(--serif)', fontSize: 18, color: 'var(--fg-1)', marginTop: 4 }}>
              {s.load_profile.peak_load_mw.toFixed(0)} MW
            </div>
            <div style={{ color: 'var(--fg-2)', fontSize: 11, marginTop: 2 }}>{s.headline}</div>
          </div>
        )
      })}
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────── //

function pickWorstScenario(scenarios: ScenarioOutcome[]): ScenarioOutcome | null {
  return scenarios.reduce<ScenarioOutcome | null>(
    (acc, s) => (!acc || s.load_profile.peak_load_mw > acc.load_profile.peak_load_mw ? s : acc),
    null,
  )
}

