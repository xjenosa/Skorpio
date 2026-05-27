import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api/client'
import type { ExpansionOption, ExpansionPlan, JobStatus } from '../api/types'
import { MapView, type MapMarkerSpec } from './MapView'
import { ReportShell, type ReportWinner, type ReportSection } from './ReportShell'
import { VizPanel } from './VizPanel'
import {
  CATEGORICAL_COLORS,
  CHART_AXIS,
  CHART_GRID_STROKE,
  CHART_HEIGHT,
  CHART_LEGEND_STYLE,
  CHART_TOOLTIP_ITEM_STYLE_LEGEND,
  CHART_TOOLTIP_LABEL_STYLE,
  CHART_TOOLTIP_STYLE,
  MAP_HEIGHT,
  VERDICT_COLOR,
} from './reportStyle'
import type { PipelineId } from '../pipelines'

// Datacenter Expansion Planner — Final report. Sections:
//   01 · Phased rollout (line chart)
//   02 · Operator footprint map (signature MAP)
//   03 · Methodology + limitations (text + brownfield/greenfield donut)

const TYPE_COLOR: Record<string, string> = {
  brownfield: VERDICT_COLOR.good,
  greenfield: CATEGORICAL_COLORS[1],   // cool blue
}

function fmt(n: number | null | undefined, digits = 1, fallback = '—') {
  return n == null ? fallback : n.toFixed(digits)
}

function fmtCAD(n: number | null | undefined) {
  if (n == null) return '—'
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(0)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`
  return `$${n.toFixed(0)}`
}

function parseBackendTs(iso: string | null | undefined): Date | null {
  if (!iso) return null
  if (/[Zz]$|[+-]\d{2}:?\d{2}$/.test(iso)) return new Date(iso)
  return new Date(iso + 'Z')
}

interface ExpansionReportProps {
  jobId: string
  hasResults: boolean
  onPipelineChange?: (pipelineId: PipelineId) => void
}

export function ExpansionReport({ jobId, hasResults, onPipelineChange }: ExpansionReportProps) {
  const [plan, setPlan] = useState<ExpansionPlan | null>(null)
  const [job, setJob] = useState<JobStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!hasResults) return
    if (plan && plan.job_id === jobId) return
    setPlan(null)
    setJob(null)
    setError(null)
    api.getExpansionResults(jobId).then(setPlan).catch((e) => setError(String(e)))
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
        pipelineId="datacenter-expansion"
        loading={!error && !plan}
        loadingLabel="Loading expansion report…"
        error={error}
        errorLabel="Failed to load expansion plan"
        headerStats={[]}
        agentRuntimeSeconds={null}
        winners={[]}
        sections={[]}
        execSummary={null}
        onPipelineChange={onPipelineChange}
      />
    )
  }

  const verdict =
    plan.coverage_pct >= 100 ? 'ON-TARGET'
    : plan.coverage_pct >= 80 ? 'SHORTFALL'
    : 'UNDER-PLANNED'
  const verdictColor_ =
    plan.coverage_pct >= 100 ? VERDICT_COLOR.good
    : plan.coverage_pct >= 80 ? VERDICT_COLOR.warning
    : VERDICT_COLOR.critical

  const headerStats = [
    { label: 'Existing sites', value: plan.footprint.sites.length },
    { label: 'Candidates scored', value: plan.options.length },
    { label: 'Options funded', value: plan.funded_options.length },
  ]

  const winners: ReportWinner[] = [
    {
      eyebrow: 'Verdict',
      value: verdict,
      sub: `${plan.coverage_pct.toFixed(0)}% of +${plan.spec.target_additional_mw.toFixed(0)} MW target`,
      color: verdictColor_,
    },
    {
      eyebrow: 'New capacity',
      value: `+${plan.total_new_capacity_mw.toFixed(0)} MW`,
      sub: `at ${fmt(plan.blended_carbon_g_kwh, 0)} g/kWh blended`,
    },
    {
      eyebrow: 'Capex',
      value: fmtCAD(plan.total_capex_cad),
      sub: `${plan.funded_options.length} funded option(s)`,
    },
  ]

  const sections: ReportSection[] = [
    {
      id: '01',
      title: '01 · Phased rollout',
      sub: 'Year-by-year commissioning schedule and cumulative capex.',
      body: <Section01Rollout plan={plan} />,
    },
    {
      id: '02',
      title: '02 · Operator footprint',
      sub: 'Existing anchor sites and funded expansion options on a single map.',
      body: <Section02FootprintMap plan={plan} />,
    },
    {
      id: '03',
      title: '03 · Methodology + limitations',
      sub: 'Capacity-type mix donut, demand drivers, assumptions, safety flags.',
      body: <Section03Methodology plan={plan} />,
    },
  ]

  // Operator footprint citations (Cushman & Wakefield, DC Byte, etc.) + live
  // carbon-intensity feed.
  const sources = [
    ...(plan.footprint.sources ?? []),
    'Provincial carbon intensity (live): IESO / AESO / Hydro-Québec fuel mix + IPCC AR5 lifecycle factors',
  ]

  return (
    <ReportShell
      jobId={jobId}
      pipelineId="datacenter-expansion"
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

// ── Section 01 · phased rollout line chart ────────────────────────────── //

function Section01Rollout({ plan }: { plan: ExpansionPlan }) {
  const demand = plan.demand_forecast.annual_demand_mw
  const baseline = plan.demand_forecast.baseline_mw
  const data = plan.phased_rollout.map((p, i) => ({
    year: `Y${p.year}`,
    supply_mw: Number((baseline + p.cumulative_new_mw).toFixed(1)),
    demand_mw: Number((demand[i] ?? 0).toFixed(1)),
    capex_b: Number((p.cumulative_capex_cad / 1e9).toFixed(2)),
  }))

  return (
    <VizPanel
      caption={
        <>
          Cumulative supply (baseline + funded options) vs projected demand under{' '}
          <strong>{plan.spec.workload_mix.replace(/_/g, ' ')}</strong> workload mix.
        </>
      }
      details={
        <div className="fr-insights">
          {plan.phased_rollout.map((p) => {
            const options = plan.funded_options.filter((o) => p.options.includes(o.option_id))
            return (
              <div className="fr-insight" key={p.year}>
                <div className="fr-insight-head">
                  <strong>Year {p.year}</strong>
                  <span className="t-mono" style={{ color: 'var(--accent)' }}>
                    +{p.cumulative_new_mw.toFixed(0)} MW · {fmtCAD(p.cumulative_capex_cad)}
                  </span>
                </div>
                {options.length > 0 ? (
                  <dl>
                    {options.map((o) => (
                      <div key={o.option_id}>
                        <dt>{o.title.split(',')[0]}</dt>
                        <dd>{o.new_capacity_mw.toFixed(0)} MW · {fmtCAD(o.capex_cad)} · {o.deployment_months}mo</dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p style={{ color: 'var(--fg-3)', fontSize: 12 }}>No new commissioning this year.</p>
                )}
              </div>
            )
          })}
        </div>
      }
    >
      <div style={{ width: '100%', height: CHART_HEIGHT.hero }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
            <CartesianGrid stroke={CHART_GRID_STROKE} />
            <XAxis dataKey="year" stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} />
            <YAxis stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} unit=" MW" />
            <Tooltip contentStyle={CHART_TOOLTIP_STYLE} itemStyle={CHART_TOOLTIP_ITEM_STYLE_LEGEND} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
            <Legend wrapperStyle={CHART_LEGEND_STYLE} />
            <Line type="monotone" dataKey="supply_mw" stroke={CATEGORICAL_COLORS[2]} strokeWidth={2} dot isAnimationActive={false} name="Cumulative supply (MW)" />
            <Line type="monotone" dataKey="demand_mw" stroke={CATEGORICAL_COLORS[0]} strokeWidth={2} dot isAnimationActive={false} name="Projected demand (MW)" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </VizPanel>
  )
}

// ── Section 02 · operator footprint map (signature MAP) ──────────────── //

function Section02FootprintMap({ plan }: { plan: ExpansionPlan }) {
  // Two layers of markers: existing sites (diamond, mint green = brownfield
  // anchor) + funded options (circle, color by type, size by MW).
  // No popup on the anchor diamond — a brownfield expansion option sits
  // directly on top of it (offset=0), so its popup would always lose to or
  // fight with the anchor's. The legend already labels the diamond as
  // "EXISTING (anchor)" so the marker reads correctly without click-through.
  const existing: MapMarkerSpec[] = plan.footprint.sites.map((s) => ({
    id: `existing-${s.site_id}`,
    lat: s.latitude,
    lon: s.longitude,
    color: VERDICT_COLOR.good,
    size: 'md',
    shape: 'diamond',
  }))

  // Funded option markers — coordinates come from the linked existing site
  // (brownfield) or the option's own coords if available. ExpansionOption
  // typically carries a target_site_id + lat/lon; fall back if missing.
  const siteById = new Map(plan.footprint.sites.map((s) => [s.site_id, s]))
  const options: MapMarkerSpec[] = plan.funded_options
    .map((o, i) => {
      const target = o.target_site_id ? siteById.get(o.target_site_id) : null
      const lat = o.latitude ?? target?.latitude
      const lon = o.longitude ?? target?.longitude
      if (lat == null || lon == null) return null
      const color = TYPE_COLOR[o.option_type] ?? VERDICT_COLOR.neutral
      // Slight offset for greenfield options so they don't overlap their
      // anchor site visually.
      const offset = o.option_type === 'greenfield' ? 0.15 : 0
      // For brownfield options the circle sits on top of the anchor diamond
      // (offset=0), so the anchor's popup was dropped to avoid the overlap.
      // Fold its useful baseline data — current capacity + PUE — into the
      // brownfield circle's popup meta so the operator still sees "what
      // exists today" alongside "what gets added". Greenfield options are
      // displaced (offset=0.15) and represent new builds, so anchor context
      // there would just clutter.
      const isBrownfield = o.option_type === 'brownfield'
      const baselineSuffix = isBrownfield && target
        ? ` · today ${target.current_capacity_mw.toFixed(0)} MW → ${(target.current_capacity_mw + o.new_capacity_mw).toFixed(0)} MW total · PUE ${target.pue.toFixed(2)}`
        : ''
      return {
        id: `funded-${o.option_id}-${i}`,
        lat: lat + offset,
        lon: lon + offset,
        color,
        size: o.new_capacity_mw >= 50 ? 'lg' : o.new_capacity_mw >= 20 ? 'md' : 'sm',
        shape: 'circle',
        popup: {
          eyebrow: `Funded #${o.rank} · ${o.option_type.toUpperCase()}`,
          title: o.title,
          meta: `+${o.new_capacity_mw.toFixed(0)} MW · ${fmtCAD(o.capex_cad)} · ${o.deployment_months}mo${baselineSuffix}`,
        },
      } as MapMarkerSpec
    })
    .filter((m): m is MapMarkerSpec => m != null)

  const markers = [...existing, ...options]

  if (markers.length === 0) {
    return (
      <VizPanel caption="No coordinates available for footprint or funded options.">
        <FundedTable plan={plan} />
      </VizPanel>
    )
  }

  // Legend entries reflect what's actually on the map. If the plan is
  // all-brownfield (or all-greenfield) we don't surface the absent
  // category — a "GREENFIELD expansion" legend row with zero markers
  // misleads readers into hunting for circles that don't exist.
  const presentTypes = new Set(plan.funded_options.map((o) => o.option_type))
  const legendEntries: { label: string; color: string }[] = [
    { label: 'EXISTING (anchor)', color: VERDICT_COLOR.good },
  ]
  if (presentTypes.has('brownfield')) {
    legendEntries.push({ label: 'BROWNFIELD expansion', color: TYPE_COLOR.brownfield })
  }
  if (presentTypes.has('greenfield')) {
    legendEntries.push({ label: 'GREENFIELD expansion', color: TYPE_COLOR.greenfield })
  }

  // Caption color for the "circle" word: match the dominant funded type so
  // the inline marker color matches what the operator sees on the map.
  const circleColor = presentTypes.has('greenfield') && !presentTypes.has('brownfield')
    ? TYPE_COLOR.greenfield
    : TYPE_COLOR.brownfield

  return (
    <VizPanel
      caption={
        <>
          {existing.length} existing site{existing.length === 1 ? '' : 's'} (
          <strong style={{ color: VERDICT_COLOR.good }}>diamond</strong>) and {options.length} funded
          option{options.length === 1 ? '' : 's'} (<strong style={{ color: circleColor }}>circle</strong>).
        </>
      }
      details={<FundedTable plan={plan} />}
    >
      <MapView
        markers={markers}
        height={MAP_HEIGHT.dense}
        legend={legendEntries}
      />
    </VizPanel>
  )
}

function FundedTable({ plan }: { plan: ExpansionPlan }) {
  if (plan.funded_options.length === 0) {
    return <p className="fr-empty">No options were funded.</p>
  }
  return (
    <div className="fr-insights">
      {plan.funded_options.map((o) => (
        <OptionCard key={o.option_id} o={o} />
      ))}
    </div>
  )
}

function OptionCard({ o }: { o: ExpansionOption }) {
  const c = TYPE_COLOR[o.option_type] ?? VERDICT_COLOR.neutral
  return (
    <div className="fr-insight">
      <div className="fr-insight-head">
        <strong>#{o.rank} · {o.title}</strong>
        <span className="t-mono" style={{ color: c }}>{o.option_type.toUpperCase()}</span>
      </div>
      <dl>
        <dt>New capacity</dt>
        <dd>{o.new_capacity_mw.toFixed(0)} MW · {o.deployment_months}mo</dd>
        <dt>Capex</dt>
        <dd>{fmtCAD(o.capex_cad)} ({fmtCAD(o.capex_per_mw_cad)}/MW)</dd>
        <dt>Carbon</dt>
        <dd>{o.avg_carbon_g_kwh.toFixed(0)} g/kWh · zone {o.grid_zone ?? '—'}</dd>
        <dt>Overall</dt>
        <dd>{(o.overall_score * 100).toFixed(0)} / 100</dd>
      </dl>
      {o.rationale && (
        <p style={{ marginTop: 6, fontSize: 12, color: 'var(--fg-2)' }}>{o.rationale}</p>
      )}
      {o.blockers.length > 0 && (
        <ul style={{ marginTop: 4, paddingLeft: 18, fontSize: 11, color: 'var(--fg-3)' }}>
          {o.blockers.map((b, i) => <li key={i}>{b}</li>)}
        </ul>
      )}
    </div>
  )
}

// ── Section 03 · methodology + brownfield/greenfield donut ────────────── //

function Section03Methodology({ plan }: { plan: ExpansionPlan }) {
  // Mini-viz: brownfield vs greenfield MW split. Tells the operator "how
  // much of our new capacity comes from expanding existing campuses vs
  // building from scratch?"
  const mixTotals = new Map<string, number>()
  for (const o of plan.funded_options) {
    const prev = mixTotals.get(o.option_type) ?? 0
    mixTotals.set(o.option_type, prev + o.new_capacity_mw)
  }
  const donutData = Array.from(mixTotals.entries())
    .map(([type, mw]) => ({
      name: type,
      value: Math.round(mw),
      color: TYPE_COLOR[type] ?? VERDICT_COLOR.neutral,
    }))
    .sort((a, b) => b.value - a.value)
  const totalMW = donutData.reduce((s, d) => s + d.value, 0)

  return (
    <VizPanel
      caption={
        <>
          Capacity-type mix · total <strong>{totalMW.toFixed(0)} MW</strong> across {plan.funded_options.length} funded option(s)
        </>
      }
    >
      {donutData.length > 0 && (
        <div style={{ width: '100%', height: CHART_HEIGHT.mini }}>
          <ResponsiveContainer>
            <PieChart>
              <Tooltip contentStyle={CHART_TOOLTIP_STYLE} itemStyle={CHART_TOOLTIP_ITEM_STYLE_LEGEND} labelStyle={CHART_TOOLTIP_LABEL_STYLE} formatter={(v: unknown) => `${v} MW`} />
              <Legend wrapperStyle={CHART_LEGEND_STYLE} />
              <Pie
                data={donutData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                innerRadius={40}
                outerRadius={70}
                isAnimationActive={false}
              >
                {donutData.map((d, i) => <Cell key={i} fill={d.color} />)}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="fr-meta" style={{ marginTop: 16 }}>
        {plan.demand_forecast.drivers.length > 0 && (
          <div>
            <span className="t-eyebrow">Demand drivers</span>
            <ul>{plan.demand_forecast.drivers.map((d, i) => <li key={i}>{d}</li>)}</ul>
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
        {plan.footprint.sources.length > 0 && (
          <div style={{ marginTop: 8, fontSize: 11, color: 'var(--fg-3)' }}>
            ⓘ Footprint sources: {plan.footprint.sources.join('; ')}.
          </div>
        )}
      </div>
    </VizPanel>
  )
}

