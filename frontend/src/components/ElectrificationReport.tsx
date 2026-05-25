import { useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api/client'
import type {
  ElectrificationPlan,
  FSAOutcome,
  JobStatus,
  ReadinessScore,
} from '../api/types'
import { MapView, type MapMarkerSpec } from './MapView'
import { ReportShell, type ReportWinner, type ReportSection } from './ReportShell'
import { VizPanel } from './VizPanel'
import {
  CATEGORICAL_COLORS,
  CHART_AXIS,
  CHART_GRID_STROKE,
  CHART_HEIGHT,
  CHART_HOVER_CURSOR,
  CHART_LEGEND_STYLE,
  CHART_TOOLTIP_ITEM_STYLE,
  CHART_TOOLTIP_ITEM_STYLE_LEGEND,
  CHART_TOOLTIP_LABEL_STYLE,
  CHART_TOOLTIP_STYLE,
  MAP_HEIGHT,
  VERDICT_COLOR,
  verdictColor,
} from './reportStyle'
import type { PipelineId } from '../pipelines'

// Neighborhood Electrification Readiness — Final report. Sections:
//   01 · Per-FSA load impact   (chart)
//   02 · FSA readiness map     (signature MAP)
//   03 · Interventions + methodology (text + scenario-severity mini-bars)

function fmt(n: number | null | undefined, digits = 1, fallback = '—') {
  return n == null ? fallback : n.toFixed(digits)
}

function fmtCAD(n: number | null | undefined) {
  if (n == null) return '—'
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`
  return `$${n.toFixed(0)}`
}

function parseBackendTs(iso: string | null | undefined): Date | null {
  if (!iso) return null
  if (/[Zz]$|[+-]\d{2}:?\d{2}$/.test(iso)) return new Date(iso)
  return new Date(iso + 'Z')
}

function pickWorstScenarioOutcomes(plan: ElectrificationPlan): FSAOutcome[] {
  const target = plan.spec.scenarios.reduce<typeof plan.spec.scenarios[number] | null>(
    (acc, s) =>
      !acc || s.heat_pump_conversion_pct + s.ev_adoption_pct > acc.heat_pump_conversion_pct + acc.ev_adoption_pct
        ? s
        : acc,
    null,
  )
  if (!target) return []
  return plan.fsa_outcomes
    .filter((o) => o.scenario.name === target.name)
    .sort((a, b) => b.readiness.overall_score - a.readiness.overall_score)
}

function pickHeadlineVerdict(plan: ElectrificationPlan): { verdict: string; color: string; headline: string } {
  const all = plan.fsa_outcomes.map((o) => o.readiness)
  const blocked = all.filter((r) => r.verdict === 'BLOCKED').length
  const constrained = all.filter((r) => r.verdict === 'CONSTRAINED').length
  const ready = all.filter((r) => r.verdict === 'READY').length
  let verdict: 'READY' | 'CONSTRAINED' | 'BLOCKED' = 'READY'
  if (blocked >= all.length / 2) verdict = 'BLOCKED'
  else if (constrained + blocked >= all.length / 2) verdict = 'CONSTRAINED'
  return {
    verdict,
    color: verdictColor(verdict),
    headline:
      verdict === 'READY'
        ? `${ready}/${all.length} pairings READY across all scenarios`
        : verdict === 'CONSTRAINED'
          ? `${constrained + blocked}/${all.length} pairings need intervention`
          : `${blocked}/${all.length} pairings BLOCKED. Service risk by target year.`,
  }
}

interface ElectrificationReportProps {
  jobId: string
  hasResults: boolean
  onPipelineChange?: (pipelineId: PipelineId) => void
}

export function ElectrificationReport({ jobId, hasResults, onPipelineChange }: ElectrificationReportProps) {
  const [plan, setPlan] = useState<ElectrificationPlan | null>(null)
  const [job, setJob] = useState<JobStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!hasResults) return
    if (plan && plan.job_id === jobId) return
    setPlan(null)
    setJob(null)
    setError(null)
    api.getElectrificationResults(jobId).then(setPlan).catch((e) => setError(String(e)))
    api.getJob(jobId).then(setJob).catch(() => {})
  }, [jobId, hasResults, plan])

  const runtimeSeconds = useMemo(() => {
    const start = parseBackendTs(job?.started_at ?? null)
    const end = parseBackendTs(job?.updated_at ?? null)
    if (!start || !end) return null
    return (end.getTime() - start.getTime()) / 1000
  }, [job?.started_at, job?.updated_at])

  if (!hasResults) return null

  if (error || !plan) {
    return (
      <ReportShell
        jobId={jobId}
        pipelineId="electrification-readiness"
        loading={!error && !plan}
        loadingLabel="Loading electrification report…"
        error={error}
        errorLabel="Failed to load electrification plan"
        headerStats={[]}
        agentRuntimeSeconds={null}
        winners={[]}
        sections={[]}
        execSummary={null}
        onPipelineChange={onPipelineChange}
      />
    )
  }

  const totalHH = plan.neighborhoods.reduce((s, p) => s + p.households, 0)
  const headline = pickHeadlineVerdict(plan)
  const worstOutcomes = pickWorstScenarioOutcomes(plan)
  const worstScenarioLabel = worstOutcomes[0]?.scenario.label ?? '—'
  const worstIncrementalMW = worstOutcomes.reduce((s, o) => s + o.load_impact.incremental_peak_mw, 0)
  const totalInterventionCost = plan.interventions.reduce(
    (s, i) => s + (i.estimated_cost_cad ?? 0),
    0,
  )

  const headerStats = [
    { label: 'FSAs studied', value: plan.neighborhoods.length },
    { label: 'Households modeled', value: totalHH.toLocaleString() },
    { label: 'Scenarios tested', value: plan.spec.scenarios.length },
  ]

  const winners: ReportWinner[] = [
    {
      eyebrow: 'Verdict (worst case)',
      value: headline.verdict,
      sub: headline.headline,
      color: headline.color,
    },
    {
      eyebrow: 'Incremental peak load',
      value: `+${fmt(worstIncrementalMW, 1)} MW`,
      sub: `under ${worstScenarioLabel.toLowerCase()}`,
    },
    {
      eyebrow: 'Intervention cost',
      value: fmtCAD(totalInterventionCost),
      sub: `${plan.interventions.length} recommended action(s)`,
    },
  ]

  const sections: ReportSection[] = [
    {
      id: '01',
      title: '01 · Per-FSA load impact',
      sub: 'Incremental winter-peak demand and panel-upgrade burden by neighborhood.',
      body: <Section01LoadImpact worst={worstOutcomes} />,
    },
    {
      id: '02',
      title: '02 · FSA readiness map',
      sub: 'Neighborhoods colored by readiness verdict, sized by households modeled.',
      body: <Section02ReadinessMap plan={plan} worst={worstOutcomes} />,
    },
    {
      id: '03',
      title: '03 · Interventions & methodology',
      sub: 'Scenario severity, recommended unblockers, methodology notes.',
      body: <Section03Interventions plan={plan} />,
    },
  ]

  // De-duplicate citations across all FSA neighborhood profiles.
  const sources = Array.from(
    new Set(plan.neighborhoods.flatMap((n) => n.sources ?? [])),
  )

  return (
    <ReportShell
      jobId={jobId}
      pipelineId="electrification-readiness"
      headerStats={headerStats}
      agentRuntimeSeconds={runtimeSeconds}
      winners={winners}
      sections={sections}
      execSummary={plan.executive_summary}
      sources={sources}
      onPipelineChange={onPipelineChange}
    />
  )
}

// ── Section 01 · per-FSA incremental MW chart ────────────────────────── //

function Section01LoadImpact({ worst }: { worst: FSAOutcome[] }) {
  if (worst.length === 0) return <p className="fr-empty">No FSA outcomes available.</p>
  const data = worst.map((o) => ({
    fsa: o.profile.fsa,
    incremental_mw: Number(o.load_impact.incremental_peak_mw.toFixed(2)),
    color: verdictColor(o.readiness.verdict),
  }))
  return (
    <VizPanel
      caption={
        <>
          Worst-case scenario: <strong>{worst[0].scenario.label}</strong> ·
          {' '}+{fmt(worst.reduce((s, o) => s + o.load_impact.incremental_peak_mw, 0), 1)} MW total
        </>
      }
      details={
        <div className="fr-insights">
          {worst.map((o) => {
            const c = verdictColor(o.readiness.verdict)
            return (
              <div className="fr-insight" key={o.profile.fsa}>
                <div className="fr-insight-head">
                  <strong>{o.profile.label}</strong>
                  <span className="t-mono" style={{ color: c }}>{o.readiness.verdict}</span>
                </div>
                <dl>
                  <dt>Incremental peak</dt>
                  <dd>+{fmt(o.load_impact.incremental_peak_mw, 1)} MW (peak hour {o.load_impact.peak_hour}:00)</dd>
                  <dt>Per-household peak</dt>
                  <dd>{fmt(o.load_impact.peak_kw_per_household, 1)} kW</dd>
                  <dt>Panel upgrades</dt>
                  <dd>{Math.round(o.load_impact.panel_upgrade_household_pct * 100)}% of {o.profile.households.toLocaleString()} homes</dd>
                  <dt>Transformer overloads</dt>
                  <dd>{o.load_impact.transformer_overload_count}</dd>
                </dl>
              </div>
            )
          })}
        </div>
      }
    >
      <div style={{ width: '100%', height: CHART_HEIGHT.hero }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={CHART_GRID_STROKE} />
            <XAxis dataKey="fsa" stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} />
            <YAxis stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} unit=" MW" />
            <Tooltip cursor={CHART_HOVER_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} itemStyle={CHART_TOOLTIP_ITEM_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
            <Legend wrapperStyle={CHART_LEGEND_STYLE} />
            <Bar dataKey="incremental_mw" name="Incremental peak MW">
              {data.map((d, i) => <Cell key={i} fill={d.color} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </VizPanel>
  )
}

// ── Section 02 · FSA readiness map (signature MAP) ──────────────────── //

function Section02ReadinessMap({ plan, worst }: { plan: ElectrificationPlan; worst: FSAOutcome[] }) {
  // One marker per FSA — color by worst-case readiness verdict, size by
  // households modeled. FSA centroids come from NeighborhoodProfile.lat/lon
  // (nullable; skip if missing). Falls back gracefully when no coords.
  const worstByFsa = new Map(worst.map((o) => [o.profile.fsa, o]))
  const markers: MapMarkerSpec[] = plan.neighborhoods
    .filter((n) => n.latitude != null && n.longitude != null)
    .map((n) => {
      const outcome = worstByFsa.get(n.fsa)
      const v = outcome?.readiness.verdict ?? 'UNKNOWN'
      const color = verdictColor(v)
      const hh = n.households
      // Households → marker size band. Toronto downtown FSAs are typically
      // ~10-25k HH, so split at 8k / 18k.
      const size: 'sm' | 'md' | 'lg' = hh >= 18_000 ? 'lg' : hh >= 8_000 ? 'md' : 'sm'
      const incremental = outcome?.load_impact.incremental_peak_mw
      return {
        id: n.fsa,
        lat: n.latitude!,
        lon: n.longitude!,
        color,
        size,
        popup: {
          eyebrow: `${n.fsa} · ${v}`,
          title: n.label,
          meta: `${hh.toLocaleString()} households${
            incremental != null ? ` · +${incremental.toFixed(1)} MW worst case` : ''
          }`,
        },
      }
    })

  if (markers.length === 0) {
    return (
      <VizPanel caption="No FSA coordinates available. Readiness scorecards shown below.">
        <p className="fr-empty">FSA centroid data unavailable for the studied neighborhoods.</p>
      </VizPanel>
    )
  }

  return (
    <VizPanel
      caption={
        <>
          {markers.length} FSA{markers.length === 1 ? '' : 's'} plotted. Marker color = worst-case readiness, size = households modeled.
        </>
      }
      details={<ReadinessTable plan={plan} />}
    >
      <MapView
        markers={markers}
        height={MAP_HEIGHT.standard}
        legend={[
          { label: 'READY',       color: VERDICT_COLOR.good },
          { label: 'CONSTRAINED', color: VERDICT_COLOR.warning },
          { label: 'BLOCKED',     color: VERDICT_COLOR.critical },
        ]}
      />
    </VizPanel>
  )
}

function ReadinessTable({ plan }: { plan: ElectrificationPlan }) {
  return (
    <div className="reports">
      <div style={{ marginBottom: 8, fontSize: 12, color: 'var(--fg-3)' }}>
        Multi-dimensional readiness across all {plan.fsa_outcomes.length} (FSA × scenario) pairings.
      </div>
      <table>
        <thead>
          <tr>
            <th>FSA</th>
            <th>Scenario</th>
            <th>Grid</th>
            <th>Building</th>
            <th>Afford.</th>
            <th>Policy</th>
            <th>Overall</th>
            <th>Verdict</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {plan.fsa_outcomes.map((o) => (
            <ReadinessRow
              key={`${o.profile.fsa}-${o.scenario.name}`}
              fsa={o.profile.fsa}
              scenarioLabel={o.scenario.label}
              r={o.readiness}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ReadinessRow({ fsa, scenarioLabel, r }: { fsa: string; scenarioLabel: string; r: ReadinessScore }) {
  const c = verdictColor(r.verdict)
  return (
    <tr>
      <td className="num">{fsa}</td>
      <td>{scenarioLabel}</td>
      <td className="num">{(r.grid_score * 100).toFixed(0)}</td>
      <td className="num">{(r.building_score * 100).toFixed(0)}</td>
      <td className="num">{(r.affordability_score * 100).toFixed(0)}</td>
      <td className="num">{(r.policy_score * 100).toFixed(0)}</td>
      <td className="num" style={{ color: c, fontWeight: 600 }}>{(r.overall_score * 100).toFixed(0)}</td>
      <td style={{ color: c, fontFamily: 'var(--mono)', fontSize: 11 }}>{r.verdict}</td>
      <td style={{ color: 'var(--fg-2)', fontSize: 12 }}>{r.rationale || '—'}</td>
    </tr>
  )
}

// ── Section 03 · interventions + scenario severity mini-bars ─────────── //

function Section03Interventions({ plan }: { plan: ElectrificationPlan }) {
  // Mini-viz: each scenario's HP conversion %, EV adoption %, target year
  // (as years-from-now) as parallel horizontal bars.
  const now = new Date().getFullYear()
  const severityData = plan.spec.scenarios.map((s) => ({
    label: s.label,
    // Backend stores adoption as a fraction (0.30 = 30%). Multiply before
    // rounding so the bars show the actual prompted % instead of collapsing
    // every fraction <1.0 to 0. (Same bug pattern as WinterPeakReport.)
    hp:    Math.round(s.heat_pump_conversion_pct * 100),
    ev:    Math.round(s.ev_adoption_pct * 100),
    years: Math.max(0, s.target_year - now),
  }))

  return (
    <VizPanel
      caption="Scenario severity (HP conversion %, EV adoption %, years out), recommended interventions, and methodology."
    >
      <div style={{ width: '100%', height: CHART_HEIGHT.mini }}>
        <ResponsiveContainer>
          <BarChart data={severityData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }} layout="vertical">
            <CartesianGrid stroke={CHART_GRID_STROKE} />
            <XAxis type="number" stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} />
            <YAxis type="category" dataKey="label" width={120} stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} />
            <Tooltip cursor={CHART_HOVER_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} itemStyle={CHART_TOOLTIP_ITEM_STYLE_LEGEND} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
            <Legend wrapperStyle={CHART_LEGEND_STYLE} />
            <Bar dataKey="hp"    name="Heat pump %" fill={CATEGORICAL_COLORS[2]} />
            <Bar dataKey="ev"    name="EV %"        fill={CATEGORICAL_COLORS[1]} />
            <Bar dataKey="years" name="Years out"   fill={CATEGORICAL_COLORS[0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="fr-meta" style={{ marginTop: 16 }}>
        {plan.interventions.length > 0 && (
          <div>
            <span className="t-eyebrow">Recommended interventions</span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 10, marginTop: 8 }}>
              {plan.interventions.map((iv) => (
                <div key={iv.intervention_id} style={{ background: 'var(--bg-2)', padding: 12, borderRadius: 4 }}>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--accent)', letterSpacing: 1 }}>
                    {iv.category.replace(/_/g, ' ').toUpperCase()}
                  </div>
                  <div style={{ fontFamily: 'var(--serif)', fontSize: 15, color: 'var(--fg-1)', marginTop: 4 }}>
                    {iv.title}
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, fontSize: 11, color: 'var(--fg-2)', marginTop: 6 }}>
                    <span>Lift: <strong style={{ color: 'var(--fg-1)' }}>+{iv.readiness_lift_pct.toFixed(0)} pts</strong></span>
                    <span>Cost: <strong style={{ color: 'var(--fg-1)' }}>{fmtCAD(iv.estimated_cost_cad)}</strong></span>
                    {iv.deployment_months != null && <span>{iv.deployment_months}mo</span>}
                    {iv.households_unlocked > 0 && <span>{iv.households_unlocked.toLocaleString()} HH</span>}
                  </div>
                  {iv.rationale && (
                    <div style={{ marginTop: 6, fontSize: 11, color: 'var(--fg-3)' }}>{iv.rationale}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
        {plan.methodology_notes && (
          <div>
            <span className="t-eyebrow">Methodology</span>
            <p>{plan.methodology_notes}</p>
          </div>
        )}
        {plan.safety_flags.length > 0 && (
          <div>
            <span className="t-eyebrow">Safety flags</span>
            <ul>{plan.safety_flags.map((f, i) => <li key={i}>{f}</li>)}</ul>
          </div>
        )}
        {plan.limitations.length > 0 && (
          <div>
            <span className="t-eyebrow">Limitations</span>
            <ul>{plan.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
          </div>
        )}
        {plan.neighborhoods.some((n) => n.is_synthesized) && (
          <div style={{ marginTop: 8, fontSize: 11, color: 'var(--fg-3)' }}>
            ⓘ Some FSAs were synthesized from province averages. See per-FSA sources in the data.
          </div>
        )}
      </div>
    </VizPanel>
  )
}
