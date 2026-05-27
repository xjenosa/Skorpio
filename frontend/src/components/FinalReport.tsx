import type { ReactNode } from 'react'
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
import type { SitingPlan } from '../api/types'
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
  CHART_MUTED_BAR,
  CHART_TOOLTIP_ITEM_STYLE,
  CHART_TOOLTIP_LABEL_STYLE,
  CHART_TOOLTIP_STYLE,
  MAP_HEIGHT,
} from './reportStyle'
import type { PipelineId } from '../pipelines'

// Datacenter Siting — Final report. Sections:
//   01 · Ranked candidates (chart — LCOE bar of top candidates, top 3 in
//        Skorpio accent orange, rest neutral; ranked table below.)
//   02 · Sites & regions  (signature MAP — candidates on Canada basemap;
//        region-insight cards below as the details slot.)
//   03 · Methodology & caveats (text + avg-pareto-objectives mini-bar)

export interface FinalReportProps {
  plan: SitingPlan
  jobId: string
  onPipelineChange?: (pipelineId: PipelineId) => void
}

function fmt(n: number | null | undefined, digits = 1, fallback = '—') {
  return n == null ? fallback : n.toFixed(digits)
}

export function FinalReport({ plan, jobId, onPipelineChange }: FinalReportProps) {
  const winner = plan.top_candidates[0]
  const cheapest = plan.top_candidates.reduce<typeof winner | undefined>(
    (a, b) => (!a || b.levelized_cost_usd_mwh < a.levelized_cost_usd_mwh ? b : a),
    undefined,
  )
  const fastest = plan.top_candidates.reduce<typeof winner | undefined>(
    (a, b) => {
      const am = a?.site.profile.deployment_months ?? Infinity
      const bm = b.site.profile.deployment_months ?? Infinity
      return bm < am ? b : a
    },
    undefined,
  )

  const headerStats = [
    { label: 'Regions',      value: plan.regions_analyzed },
    { label: 'Sites scored', value: plan.sites_scored },
    { label: 'Top ranked',   value: plan.top_candidates.length },
  ]

  // Siting follows the "info-trio" winner pattern (see REPORTS_COHESION.md §3):
  // three parallel cards highlighting the best option on each axis the operator
  // cares about. Always render all 3 slots — when a run produces no candidates
  // we render em-dashes so the empty state is visible instead of an invisible
  // skip, matching the always-3-cards behavior of the other reports.
  const winners: ReportWinner[] = [
    {
      eyebrow: 'Best site overall',
      value: winner?.site.name ?? '—',
      sub: winner
        ? `${winner.region_iso} · $${fmt(winner.levelized_cost_usd_mwh)}/MWh · ${fmt(winner.site.profile.capacity_mw)} MW`
        : 'No candidates returned by this run',
    },
    {
      eyebrow: 'Lowest cost',
      value: cheapest?.site.name ?? '—',
      sub: cheapest ? `$${fmt(cheapest.levelized_cost_usd_mwh)}/MWh` : '—',
    },
    {
      eyebrow: 'Fastest deployment',
      value: fastest?.site.name ?? '—',
      sub: fastest ? `${fmt(fastest.site.profile.deployment_months, 0)} months` : '—',
    },
  ]

  const sections: ReportSection[] = [
    {
      id: '01',
      title: '01 · Ranked candidates',
      sub: 'LCOE for the top 10 candidates, full leaderboard table below.',
      body: <Section01Ranked plan={plan} />,
    },
    {
      id: '02',
      title: '02 · Sites & regions',
      sub: 'Top candidates on a Canada basemap, region-context cards below.',
      body: <Section02SitesMap plan={plan} />,
    },
    {
      id: '03',
      title: '03 · Methodology & caveats',
      sub: 'Average pareto profile (what the plan optimized for), methodology, caveats.',
      body: <Section03Methodology plan={plan} />,
    },
  ]

  // Sources for the Siting pipeline. Static base list of registries the
  // agents always draw from, extended with any dynamic citations the
  // backend emits in plan.sources — currently the ArcGIS GeoEnrichment
  // pull on the top candidate's city when Esri credentials are
  // configured. Dynamic sources land first so the most-specific
  // attribution is read first.
  const sources = [
    ...(plan.sources ?? []),
    'EIA grid demand telemetry',
    'NREL renewable resource data',
    'ECCC Canadian weather and climate feeds',
    'Provincial carbon intensity: IESO / AESO / Hydro-Québec fuel mix + IPCC AR5 lifecycle factors',
    'Skorpio site registry (Cushman & Wakefield, operator filings)',
  ]

  return (
    <ReportShell
      jobId={jobId}
      pipelineId="datacenter-siting"
      headerStats={headerStats}
      agentRuntimeSeconds={plan.pipeline_duration_seconds ?? null}
      winners={winners}
      sections={sections}
      execSummary={plan.executive_summary}
      sources={sources}
      onPipelineChange={onPipelineChange}
    />
  )
}

// ── Section 01 · LCOE bar chart of top candidates + ranked table ──────── //

function Section01Ranked({ plan }: { plan: SitingPlan }): ReactNode {
  const top = plan.top_candidates.slice(0, 10)
  if (top.length === 0) {
    return (
      <VizPanel caption="No candidates returned.">
        <p className="fr-empty">Nothing ranked.</p>
      </VizPanel>
    )
  }
  // Vertical bars: rank on X, LCOE on Y. Top-3 ranks get the Skorpio accent,
  // the rest get a quieter neutral so the eye finds the podium fast.
  const data = top.map((c) => ({
    rank: `#${c.rank}`,
    lcoe: Number(c.levelized_cost_usd_mwh.toFixed(1)),
    fill: c.rank <= 3 ? CATEGORICAL_COLORS[0] : CHART_MUTED_BAR,
  }))

  return (
    <VizPanel
      caption={
        <>
          LCOE for the top {top.length} candidates · winner{' '}
          <strong>{top[0]?.site.name}</strong> at ${fmt(top[0]?.levelized_cost_usd_mwh)}/MWh
        </>
      }
      details={
        <div className="reports">
          <table>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Site</th>
                <th>Region</th>
                <th>$/MWh</th>
                <th>Capacity</th>
                <th>PUE</th>
                <th>Deploy</th>
              </tr>
            </thead>
            <tbody>
              {top.map((c) => (
                <tr key={c.site.site_id || c.rank}>
                  <td className="num">{c.rank}</td>
                  <td className="label">{c.site.name}</td>
                  <td>{c.region_iso}</td>
                  <td className="num">{fmt(c.levelized_cost_usd_mwh)}</td>
                  <td className="num">{fmt(c.site.profile.capacity_mw)} MW</td>
                  <td className="num">{fmt(c.site.profile.pue, 2)}</td>
                  <td className="num">{fmt(c.site.profile.deployment_months, 0)} mo</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      }
    >
      <div style={{ width: '100%', height: CHART_HEIGHT.hero }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
            <CartesianGrid stroke={CHART_GRID_STROKE} />
            <XAxis dataKey="rank" stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} />
            <YAxis stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} unit=" $/MWh" />
            <Tooltip cursor={CHART_HOVER_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} itemStyle={CHART_TOOLTIP_ITEM_STYLE} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
            <Legend wrapperStyle={CHART_LEGEND_STYLE} />
            <Bar dataKey="lcoe" name="LCOE ($/MWh)">
              {data.map((d, i) => <Cell key={i} fill={d.fill} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </VizPanel>
  )
}

// ── Section 02 · candidates on Canada basemap (signature MAP) ────────── //

function Section02SitesMap({ plan }: { plan: SitingPlan }): ReactNode {
  // One marker per top candidate. Color: top-3 = orange accent (winner
  // podium), rest = cool blue. Size: capacity_mw bands (sm < 30, md 30–80,
  // lg ≥ 80).
  const markers: MapMarkerSpec[] = plan.top_candidates.map((c) => {
    const capacity = c.site.profile.capacity_mw ?? 0
    const size: 'sm' | 'md' | 'lg' = capacity >= 80 ? 'lg' : capacity >= 30 ? 'md' : 'sm'
    const color = c.rank <= 3 ? CATEGORICAL_COLORS[0] : CATEGORICAL_COLORS[1]
    return {
      id: c.site.site_id || `cand-${c.rank}`,
      lat: c.site.latitude,
      lon: c.site.longitude,
      color,
      size,
      popup: {
        eyebrow: `Rank #${c.rank} · ${c.region_iso}`,
        title: c.site.name,
        meta: `${fmt(c.site.profile.capacity_mw)} MW · $${fmt(c.levelized_cost_usd_mwh)}/MWh · ${fmt(c.site.profile.deployment_months, 0)}mo`,
      },
    }
  })

  if (markers.length === 0) {
    return (
      <VizPanel caption="No candidates to plot.">
        <p className="fr-empty">No ranked candidates returned.</p>
      </VizPanel>
    )
  }

  return (
    <VizPanel
      caption={
        <>
          {markers.length} candidate{markers.length === 1 ? '' : 's'} plotted. Top-3 podium in{' '}
          <strong style={{ color: CATEGORICAL_COLORS[0] }}>orange</strong>, others in{' '}
          <strong style={{ color: CATEGORICAL_COLORS[1] }}>blue</strong>. Size = capacity MW.
        </>
      }
      details={
        plan.region_insights.length > 0 ? (
          <div className="fr-insights">
            {plan.region_insights.map((r) => (
              <div className="fr-insight" key={r.region_iso}>
                <div className="fr-insight-head">
                  <strong>{r.region_iso}</strong>
                  <span className="t-mono">
                    {r.top_sites.length} site{r.top_sites.length === 1 ? '' : 's'}
                  </span>
                </div>
                <dl>
                  <dt>Market outlook</dt>
                  <dd>{r.market_outlook}</dd>
                  <dt>Transmission</dt>
                  <dd>{r.transmission_constraints}</dd>
                  <dt>Regulatory</dt>
                  <dd>{r.regulatory_context}</dd>
                </dl>
              </div>
            ))}
          </div>
        ) : null
      }
    >
      <MapView
        markers={markers}
        height={MAP_HEIGHT.dense}
        legend={[
          { label: 'TOP 3',  color: CATEGORICAL_COLORS[0] },
          { label: 'OTHERS', color: CATEGORICAL_COLORS[1] },
        ]}
      />
    </VizPanel>
  )
}

// ── Section 03 · pareto-axis averages + methodology ──────────────────── //

// A bar value of 0 means every candidate scored 0 on that axis — most
// commonly "transmission_headroom" when headroom_mw is below 50% of the
// workload size. Without a hint the empty bar reads as "data missing"
// rather than "scored zero." Render a faint 2-pixel sliver so the row is
// visually present, and add an "Insufficient" line inside the tooltip
// so hover discloses the why. Per REPORTS_COHESION.md §0, the underlying
// score stays honest (still 0%); only the visual treatment changes.
function ParetoAxisTooltip({
  active, payload, label,
}: { active?: boolean; payload?: ReadonlyArray<{ value: number }>; label?: string }): ReactNode {
  if (!active || !payload?.length) return null
  const score = payload[0]?.value ?? 0
  return (
    <div style={CHART_TOOLTIP_STYLE}>
      <div style={CHART_TOOLTIP_LABEL_STYLE}>{label}</div>
      <div style={CHART_TOOLTIP_ITEM_STYLE}>Avg score: {score}%</div>
      {score === 0 && (
        <div style={{ ...CHART_TOOLTIP_ITEM_STYLE, opacity: 0.7, marginTop: 4 }}>
          Insufficient on this axis at the workload size.
        </div>
      )}
    </div>
  )
}

function Section03Methodology({ plan }: { plan: SitingPlan }): ReactNode {
  // Mini-viz: average pareto-objective scores across the top candidates.
  // Tells the operator "what does this plan implicitly optimize for?" —
  // e.g., high "carbon" score means the agent picked low-carbon sites.
  const top = plan.top_candidates.slice(0, 10)
  const axesAvail = top.some((c) => c.site.pareto_objectives != null)
  const AXES: Array<{ key: keyof NonNullable<typeof top[number]['site']['pareto_objectives']>; label: string }> = [
    { key: 'cost_economics',         label: 'Cost' },
    { key: 'carbon_intensity',       label: 'Carbon' },
    { key: 'latency_fit',            label: 'Latency' },
    { key: 'transmission_headroom',  label: 'Headroom' },
    { key: 'deployment_speed',       label: 'Speed' },
    { key: 'operational_resilience', label: 'Resilience' },
  ]
  const avgData = AXES.map(({ key, label }) => {
    const vals = top
      .map((c) => c.site.pareto_objectives?.[key])
      .filter((v): v is number => typeof v === 'number')
    const avg = vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : 0
    return { axis: label, score: Math.round(avg * 100) }
  })

  return (
    <VizPanel
      caption={
        axesAvail
          ? `Average pareto profile across top ${top.length} candidates · 100 = perfect on that axis`
          : 'Methodology, safety flags, and limitations.'
      }
    >
      {axesAvail && (
        <div style={{ width: '100%', height: CHART_HEIGHT.mini }}>
          <ResponsiveContainer>
            <BarChart data={avgData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }} layout="vertical">
              <CartesianGrid stroke={CHART_GRID_STROKE} />
              <XAxis type="number" domain={[0, 100]} stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} />
              <YAxis type="category" dataKey="axis" width={90} stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} />
              <Tooltip cursor={CHART_HOVER_CURSOR} content={<ParetoAxisTooltip />} />
              <Bar
                dataKey="score"
                name="Avg score"
                fill={CATEGORICAL_COLORS[0]}
                // Render zero-score bars as a faint 2px sliver so the row
                // is visually present; non-zero bars are unaffected. See
                // ParetoAxisTooltip above for the matching disclosure.
                minPointSize={(v) => (v === 0 ? 2 : 0)}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="fr-meta" style={{ marginTop: 16 }}>
        {!plan.methodology_notes && plan.safety_flags.length === 0 && plan.limitations.length === 0 && (
          <p className="fr-empty">No methodology notes or caveats recorded.</p>
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
      </div>
    </VizPanel>
  )
}
