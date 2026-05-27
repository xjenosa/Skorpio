import { useEffect, useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api/client'
import type { JobStatus, ResiliencePlan, ScenarioOutcome } from '../api/types'
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
  CHART_TOOLTIP_ITEM_STYLE_LEGEND,
  CHART_TOOLTIP_LABEL_STYLE,
  CHART_TOOLTIP_STYLE,
  MAP_HEIGHT,
  VERDICT_COLOR,
  verdictColor,
} from './reportStyle'
import type { PipelineId } from '../pipelines'

// Winter Peak Stress Tester — Final report. Sections:
//   01 · Scenario load curves  (chart)
//   02 · At-risk substations   (signature MAP)
//   03 · Mitigations + methodology (text + scenario-severity mini-bars)
// All chrome lives in <ReportShell>; section bodies follow the <VizPanel>
// 4-slot template so they read as siblings to every other pipeline.

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

function pickWorst(scenarios: ScenarioOutcome[]): ScenarioOutcome | null {
  return scenarios.reduce<ScenarioOutcome | null>(
    (acc, s) => (!acc || s.load_profile.peak_load_mw > acc.load_profile.peak_load_mw ? s : acc),
    null,
  )
}

interface WinterPeakReportProps {
  jobId: string
  hasResults: boolean
  onPipelineChange?: (pipelineId: PipelineId) => void
}

export function WinterPeakReport({ jobId, hasResults, onPipelineChange }: WinterPeakReportProps) {
  const [plan, setPlan] = useState<ResiliencePlan | null>(null)
  const [job, setJob] = useState<JobStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!hasResults) return
    if (plan && plan.job_id === jobId) return
    setPlan(null)
    setJob(null)
    setError(null)
    api.getWinterResults(jobId).then(setPlan).catch((e) => setError(String(e)))
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
        pipelineId="winter-peak-stress"
        loading={!error && !plan}
        loadingLabel="Loading resilience report…"
        error={error}
        errorLabel="Failed to load resilience plan"
        headerStats={[]}
        agentRuntimeSeconds={null}
        winners={[]}
        sections={[]}
        execSummary={null}
        onPipelineChange={onPipelineChange}
      />
    )
  }

  const worst = pickWorst(plan.scenarios)
  const totalCustomers = plan.network.feeders.reduce((s, f) => s + f.customer_count, 0)
  const verdict = worst?.summary_verdict ?? 'UNKNOWN'

  const headerStats = [
    { label: 'Scenarios', value: plan.scenarios.length },
    { label: 'Feeders modeled', value: plan.network.feeders.length },
    { label: 'Customers tested', value: totalCustomers.toLocaleString() },
  ]

  // Always render all 3 cards (em-dash when there's no worst-case scenario),
  // matching the always-3-cards behavior of the other reports.
  const winners: ReportWinner[] = [
    {
      eyebrow: 'Verdict (worst case)',
      value: verdict,
      sub: worst?.headline ?? 'No scenarios returned by this run',
      color: verdictColor(verdict),
    },
    {
      eyebrow: 'Peak demand',
      value: worst ? `${fmt(worst.load_profile.peak_load_mw, 0)} MW` : '—',
      sub: worst
        ? `@ hour ${worst.load_profile.peak_hour_offset} · ${fmt(worst.load_profile.peak_temp_c, 1)}°C`
        : '—',
    },
    {
      eyebrow: 'Headroom at peak',
      value: worst ? `${fmt(worst.load_profile.headroom_pct_at_peak, 0)}%` : '—',
      sub: worst ? `${fmt(worst.load_profile.headroom_at_peak_mw, 0)} MW remaining` : '—',
    },
  ]

  const sections: ReportSection[] = [
    {
      id: '01',
      title: '01 · Scenario load curves',
      sub: 'Hourly load profile per scenario, with peak hour and headroom.',
      body: <Section01LoadCurves plan={plan} worst={worst} />,
    },
    {
      id: '02',
      title: '02 · At-risk substations',
      sub: 'Substation risk map with the top feeders ranked by overload risk.',
      body: <Section02SubstationMap plan={plan} worst={worst} />,
    },
    {
      id: '03',
      title: '03 · Mitigations & methodology',
      sub: 'Scenario severity, recommended interventions, methodology notes.',
      body: <Section03Mitigations plan={plan} />,
    },
  ]

  // Aggregate citations: cold-event meteorology + per-feeder topology.
  const sources = Array.from(
    new Set([...(plan.cold_event.sources ?? []), ...(plan.network.sources ?? [])]),
  )

  return (
    <ReportShell
      jobId={jobId}
      pipelineId="winter-peak-stress"
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

// ── Section 01 · load curves chart ───────────────────────────────────── //

function Section01LoadCurves({ plan, worst }: { plan: ResiliencePlan; worst: ScenarioOutcome | null }) {
  if (!worst) return <p className="fr-empty">No scenarios available.</p>
  const data = worst.load_profile.hours.map((h) => ({
    hour: h.hour_offset,
    base: h.base_load_mw,
    heat_pump: h.heat_pump_load_mw,
    backup: h.backup_resistance_mw,
    baseboard: h.baseboard_load_mw,
    ev: h.ev_load_mw,
    other: h.other_load_mw,
  }))

  // Capacity reference lines. Mirrors the headroom math in winter_simulator.py:
  //   nameplate_mw = sum(s.nameplate_mva * 0.95 for s in substations)  // PF derate
  //   headroom_pct_at_peak = (nameplate_mw - peak_load) / nameplate_mw * 100
  // Verdict thresholds in winter_synthesis.py:
  //   PASS  = headroom ≥ 15%  (load ≤ nameplate * 0.85)
  //   MARG  = headroom 5-15%  (load ≤ nameplate * 0.95)
  //   FAIL  = headroom < 5%   (load > nameplate * 0.95) OR over nameplate
  const nameplateMw = plan.network.substations.reduce(
    (acc, s) => acc + s.nameplate_mva * 0.95, 0,
  )
  const passFloorMw = nameplateMw * 0.85        // crossing this drops PASS → MARGINAL
  const failFloorMw = nameplateMw * 0.95        // crossing this drops MARGINAL → FAIL
  // Colors mirror the verdict palette so the lines round-trip with the
  // PASS/MARGINAL/FAIL chips elsewhere in the report.
  const PASS_LINE_COLOR = VERDICT_COLOR.good
  const MARG_LINE_COLOR = VERDICT_COLOR.warning
  const FAIL_LINE_COLOR = VERDICT_COLOR.critical

  // Recharts Legend doesn't pick up ReferenceLine entries automatically.
  // We inject a custom legend payload so the three threshold lines appear
  // in the legend strip below the chart alongside the stacked-area series.
  const customLegendPayload = [
    { value: 'Base residential', type: 'square' as const, color: CATEGORICAL_COLORS[1], id: 'base' },
    { value: 'Heat pump',        type: 'square' as const, color: CATEGORICAL_COLORS[2], id: 'heat_pump' },
    { value: 'Backup resistance',type: 'square' as const, color: CATEGORICAL_COLORS[4], id: 'backup' },
    { value: 'Baseboard',        type: 'square' as const, color: CATEGORICAL_COLORS[3], id: 'baseboard' },
    { value: 'EV charging',      type: 'square' as const, color: CATEGORICAL_COLORS[0], id: 'ev' },
    { value: 'Other (C&I)',      type: 'square' as const, color: '#3a3835',             id: 'other' },
    { value: `PASS limit · 15% headroom · ${passFloorMw.toFixed(0)} MW`,
      type: 'plainline' as const, color: PASS_LINE_COLOR, id: 'pass-floor',
      payload: { strokeDasharray: '6 4' } },
    { value: `MARGINAL limit · 5% headroom · ${failFloorMw.toFixed(0)} MW`,
      type: 'plainline' as const, color: MARG_LINE_COLOR, id: 'fail-floor',
      payload: { strokeDasharray: '6 4' } },
    { value: `FAIL · nameplate · ${nameplateMw.toFixed(0)} MW`,
      type: 'plainline' as const, color: FAIL_LINE_COLOR, id: 'nameplate',
      payload: { strokeDasharray: '4 4' } },
  ]
  return (
    <VizPanel
      caption={
        <>
          Worst-case scenario: <strong>{worst.scenario.label}</strong> · peak {fmt(worst.load_profile.peak_load_mw, 0)} MW
        </>
      }
      details={
        <div className="fr-insights">
          {plan.scenarios.map((s) => {
            const c = verdictColor(s.summary_verdict)
            return (
              <div className="fr-insight" key={s.scenario.name}>
                <div className="fr-insight-head">
                  <strong>{s.scenario.label}</strong>
                  <span className="t-mono" style={{ color: c }}>{s.summary_verdict}</span>
                </div>
                <dl>
                  <dt>Peak load</dt>
                  <dd>{fmt(s.load_profile.peak_load_mw, 0)} MW @ hour {s.load_profile.peak_hour_offset} ({fmt(s.load_profile.peak_temp_c, 1)}°C)</dd>
                  <dt>Headroom</dt>
                  <dd>{fmt(s.load_profile.headroom_pct_at_peak, 0)}% ({fmt(s.load_profile.headroom_at_peak_mw, 0)} MW)</dd>
                  <dt>At-risk feeders</dt>
                  <dd>{s.feeder_risks.filter((f) => f.overload_risk >= 0.5).length} of {s.feeder_risks.length}</dd>
                </dl>
              </div>
            )
          })}
        </div>
      }
    >
      <div style={{ width: '100%', height: CHART_HEIGHT.hero }}>
        <ResponsiveContainer>
          <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={CHART_GRID_STROKE} />
            <XAxis dataKey="hour" stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} />
            <YAxis stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} unit=" MW" />
            <Tooltip contentStyle={CHART_TOOLTIP_STYLE} itemStyle={CHART_TOOLTIP_ITEM_STYLE_LEGEND} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
            <Legend wrapperStyle={CHART_LEGEND_STYLE} {...({ payload: customLegendPayload } as object)} />
            <Area type="monotone" dataKey="other" stackId="1" stroke="#6f6c63" fill="#3a3835" name="Other" />
            <Area type="monotone" dataKey="base" stackId="1" stroke={CATEGORICAL_COLORS[1]} fill={CATEGORICAL_COLORS[1]} fillOpacity={0.4} name="Base residential" />
            <Area type="monotone" dataKey="heat_pump" stackId="1" stroke={CATEGORICAL_COLORS[2]} fill={CATEGORICAL_COLORS[2]} fillOpacity={0.6} name="Heat pump" />
            <Area type="monotone" dataKey="backup" stackId="1" stroke={CATEGORICAL_COLORS[4]} fill={CATEGORICAL_COLORS[4]} fillOpacity={0.7} name="Backup resistance" />
            <Area type="monotone" dataKey="baseboard" stackId="1" stroke={CATEGORICAL_COLORS[3]} fill={CATEGORICAL_COLORS[3]} fillOpacity={0.5} name="Baseboard" />
            <Area type="monotone" dataKey="ev" stackId="1" stroke={CATEGORICAL_COLORS[0]} fill={CATEGORICAL_COLORS[0]} fillOpacity={0.7} name="EV charging" />
            {/* Capacity thresholds — solid lines show the operator's safe
                operating zones. Crossing the PASS floor = MARGINAL; crossing
                the FAIL floor = FAIL; touching nameplate = hard overload. */}
            <ReferenceLine
              y={passFloorMw}
              stroke={PASS_LINE_COLOR}
              strokeDasharray="6 4"
              strokeWidth={1.5}
              ifOverflow="extendDomain"
              label={{ value: `PASS limit · ${passFloorMw.toFixed(0)} MW`, position: 'insideTopRight', fill: PASS_LINE_COLOR, fontSize: 10 }}
            />
            <ReferenceLine
              y={failFloorMw}
              stroke={MARG_LINE_COLOR}
              strokeDasharray="6 4"
              strokeWidth={1.5}
              ifOverflow="extendDomain"
              label={{ value: `MARGINAL limit · ${failFloorMw.toFixed(0)} MW`, position: 'insideTopRight', fill: MARG_LINE_COLOR, fontSize: 10 }}
            />
            <ReferenceLine
              y={nameplateMw}
              stroke={FAIL_LINE_COLOR}
              strokeDasharray="4 4"
              strokeWidth={2}
              ifOverflow="extendDomain"
              label={{ value: `FAIL · nameplate · ${nameplateMw.toFixed(0)} MW`, position: 'insideTopRight', fill: FAIL_LINE_COLOR, fontSize: 10 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </VizPanel>
  )
}

// ── Section 02 · substation map (signature MAP for Winter) ───────────── //

function Section02SubstationMap({
  plan,
  worst,
}: {
  plan: ResiliencePlan
  worst: ScenarioOutcome | null
}) {
  if (!worst) return <p className="fr-empty">No feeder risks available.</p>
  const top = worst.feeder_risks.slice(0, 10)

  // Map markers — one per substation, sized + colored by aggregate risk.
  const riskByStation = new Map(worst.substation_risks.map((r) => [r.substation_id, r]))
  const markers: MapMarkerSpec[] = plan.network.substations.map((sub) => {
    const risk = riskByStation.get(sub.substation_id)
    const score = risk?.aggregate_risk ?? 0
    const color = score >= 0.75 ? VERDICT_COLOR.critical : score >= 0.5 ? VERDICT_COLOR.warning : VERDICT_COLOR.good
    const atRiskFeeders = risk?.at_risk_feeder_count ?? 0
    return {
      id: sub.substation_id,
      lat: sub.latitude,
      lon: sub.longitude,
      color,
      size: score >= 0.75 ? 'lg' : score >= 0.5 ? 'md' : 'sm',
      popup: {
        eyebrow: `Substation · ${sub.voltage_kv} kV`,
        title: sub.name,
        meta: `Risk ${(score * 100).toFixed(0)}% · ${atRiskFeeders} of ${sub.feeders.length} feeders at risk · winter peak ${sub.winter_peak_mw.toFixed(0)} MW`,
      },
    }
  })

  return (
    <VizPanel
      caption={
        <>
          Substation risk map under <strong>{worst.scenario.label}</strong>. Click a marker for capacity + feeder counts.
        </>
      }
      details={
        <div className="reports">
          <div style={{ marginBottom: 8, fontSize: 12, color: 'var(--fg-3)' }}>
            Top {top.length} of {worst.feeder_risks.length} feeders, ranked by overload risk.
          </div>
          <table>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Feeder</th>
                <th>Util %</th>
                <th>Overload</th>
                <th>Failure mode</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {top.map((fr) => {
                const c = fr.overload_risk >= 0.8 ? VERDICT_COLOR.critical : fr.overload_risk >= 0.5 ? VERDICT_COLOR.warning : VERDICT_COLOR.good
                return (
                  <tr key={fr.feeder_id}>
                    <td className="num">{fr.rank}</td>
                    <td className="label">{fr.feeder_name}</td>
                    <td className="num">{fmt(fr.capacity_utilization_pct, 0)}%</td>
                    <td className="num" style={{ color: c, fontWeight: 600 }}>{fmt(fr.overload_risk * 100, 0)}%</td>
                    <td>{fr.failure_mode.replace(/_/g, ' ')}</td>
                    <td style={{ color: 'var(--fg-2)', fontSize: 12 }}>{fr.rationale || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      }
    >
      <MapView
        markers={markers}
        height={MAP_HEIGHT.dense}
        legend={[
          { label: 'CRITICAL ≥ 75%', color: VERDICT_COLOR.critical },
          { label: 'AT RISK 50–74%', color: VERDICT_COLOR.warning },
          { label: 'STABLE < 50%', color: VERDICT_COLOR.good },
        ]}
      />
    </VizPanel>
  )
}

// ── Section 03 · mitigations + scenario severity mini-bars ──────────── //

function Section03Mitigations({ plan }: { plan: ResiliencePlan }) {
  // Mini-viz: per-scenario severity strip. Each scenario's HP%, EV%, and
  // peak temp °C as parallel bars so the operator can eyeball "how harsh
  // was each scenario we tested?" without scrolling back up.
  const severityData = plan.scenarios.map((s) => ({
    label: s.scenario.label,
    // Backend stores adoption as a fraction (0.30 = 30%). Multiply before
    // rounding so the bars show the user's actual prompted % instead of
    // collapsing every fraction <1.0 to 0.
    hp:    Math.round(s.scenario.heat_pump_adoption_pct * 100),
    ev:    Math.round(s.scenario.ev_adoption_pct * 100),
    cold:  Math.abs(Math.round(s.load_profile.peak_temp_c)),  // shown as |°C|
  }))

  return (
    <VizPanel
      caption="Scenario severity (HP / EV adoption %, peak cold °C absolute), recommended mitigations, and methodology."
    >
      <div style={{ width: '100%', height: CHART_HEIGHT.mini }}>
        <ResponsiveContainer>
          <BarChart data={severityData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }} layout="vertical">
            <CartesianGrid stroke={CHART_GRID_STROKE} />
            <XAxis type="number" stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} />
            <YAxis type="category" dataKey="label" width={120} stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} />
            <Tooltip cursor={CHART_HOVER_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} itemStyle={CHART_TOOLTIP_ITEM_STYLE_LEGEND} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
            <Legend wrapperStyle={CHART_LEGEND_STYLE} />
            <Bar dataKey="hp"   name="Heat pumps %" fill={CATEGORICAL_COLORS[2]} />
            <Bar dataKey="ev"   name="EVs %"        fill={CATEGORICAL_COLORS[1]} />
            <Bar dataKey="cold" name="|°C| at peak" fill={CATEGORICAL_COLORS[0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="fr-meta" style={{ marginTop: 16 }}>
        {plan.mitigations.length > 0 && (
          <div>
            <span className="t-eyebrow">Recommended mitigations</span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 10, marginTop: 8 }}>
              {plan.mitigations.map((m) => (
                <div key={m.mitigation_id} style={{ background: 'var(--bg-2)', padding: 12, borderRadius: 4 }}>
                  <div style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--accent)', letterSpacing: 1 }}>
                    {m.category.replace(/_/g, ' ').toUpperCase()}
                  </div>
                  <div style={{ fontFamily: 'var(--serif)', fontSize: 15, color: 'var(--fg-1)', marginTop: 4 }}>
                    {m.title}
                  </div>
                  <div style={{ display: 'flex', gap: 10, fontSize: 11, color: 'var(--fg-2)', marginTop: 6 }}>
                    <span>Relief: <strong style={{ color: 'var(--fg-1)' }}>{fmt(m.estimated_load_relief_mw, 1)} MW</strong></span>
                    <span>Cost: <strong style={{ color: 'var(--fg-1)' }}>{fmtCAD(m.estimated_cost_cad)}</strong></span>
                    {m.deployment_months != null && <span>{m.deployment_months}mo</span>}
                  </div>
                  {m.rationale && (
                    <div style={{ marginTop: 6, fontSize: 11, color: 'var(--fg-3)' }}>{m.rationale}</div>
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
        {plan.network.is_synthesized && (
          <div style={{ marginTop: 8, fontSize: 11, color: 'var(--fg-3)' }}>
            ⓘ Per-feeder topology values are modeled from public utility filings. Sources: {plan.network.sources.join('; ')}.
          </div>
        )}
      </div>
    </VizPanel>
  )
}

