import { useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api/client'
import type { ClimateRiskProfile, FundedProject, InvestmentPlan, JobStatus } from '../api/types'
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
} from './reportStyle'
import type { PipelineId } from '../pipelines'

// Climate-Adapted Grid Investment Optimizer — Final report. Sections:
//   01 · Funded portfolio (chart)
//   02 · At-risk asset map (signature MAP)
//   03 · Unfunded projects & methodology (text + hazard-exposure donut)

const TIER_COLOR: Record<string, string> = {
  critical: VERDICT_COLOR.critical,
  high:     VERDICT_COLOR.warning,
  medium:   CATEGORICAL_COLORS[3],   // lavender (informational)
  low:      VERDICT_COLOR.good,
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

interface InvestmentReportProps {
  jobId: string
  hasResults: boolean
  onPipelineChange?: (pipelineId: PipelineId) => void
}

export function InvestmentReport({ jobId, hasResults, onPipelineChange }: InvestmentReportProps) {
  const [plan, setPlan] = useState<InvestmentPlan | null>(null)
  const [job, setJob] = useState<JobStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!hasResults) return
    if (plan && plan.job_id === jobId) return
    setPlan(null)
    setJob(null)
    setError(null)
    api.getInvestmentResults(jobId).then(setPlan).catch((e) => setError(String(e)))
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
        pipelineId="grid-investment-optimizer"
        loading={!error && !plan}
        loadingLabel="Loading investment report…"
        error={error}
        errorLabel="Failed to load investment plan"
        headerStats={[]}
        agentRuntimeSeconds={null}
        winners={[]}
        sections={[]}
        execSummary={null}
        onPipelineChange={onPipelineChange}
      />
    )
  }

  const verdict = plan.funded_projects.length > 0 ? 'FUNDED' : 'UNDER-FUNDED'
  const verdictCol = plan.funded_projects.length > 0 ? VERDICT_COLOR.good : VERDICT_COLOR.critical
  const budgetUsedPct = plan.spec.budget_cad > 0
    ? Math.round((plan.total_capex_committed_cad / plan.spec.budget_cad) * 100)
    : 0

  const headerStats = [
    { label: 'Assets analyzed', value: plan.assets.length },
    { label: 'Candidates considered', value: plan.candidate_projects.length },
    { label: 'Projects funded', value: plan.funded_projects.length },
  ]

  const winners: ReportWinner[] = [
    {
      eyebrow: 'Verdict',
      value: verdict,
      sub: `${plan.funded_projects.length} of ${plan.candidate_projects.length} projects funded`,
      color: verdictCol,
    },
    {
      eyebrow: 'Capex committed',
      value: fmtCAD(plan.total_capex_committed_cad),
      sub: `${budgetUsedPct}% of ${fmtCAD(plan.spec.budget_cad)} budget`,
    },
    {
      eyebrow: 'Avoided loss / yr',
      value: fmtCAD(plan.total_annual_loss_avoided_cad),
      sub: `${fmt(plan.portfolio_roi_ratio, 2)}× lifetime ROI`,
    },
  ]

  const sections: ReportSection[] = [
    {
      id: '01',
      title: '01 · Funded portfolio',
      sub: 'Ranked list of projects committed within the budget.',
      body: <Section01Funded plan={plan} />,
    },
    {
      id: '02',
      title: '02 · At-risk asset map',
      sub: 'Grid assets across the service area, colored by climate risk tier.',
      body: <Section02RiskMap plan={plan} />,
    },
    {
      id: '03',
      title: '03 · Unfunded projects & methodology',
      sub: 'Hazard exposure breakdown, unfunded candidates, methodology notes.',
      body: <Section03UnfundedAndMethod plan={plan} />,
    },
  ]

  // Citations for the Investment pipeline. Static base list of upstream
  // registries the agents always draw from, extended with any dynamic
  // citations the backend emits in plan.sources — currently the ArcGIS
  // GeoEnrichment pull for the utility's representative service-area
  // city when Esri credentials are configured. Dynamic sources land
  // first so the most specific attribution is read first.
  const sources = [
    ...(plan.sources ?? []),
    'Utility asset filings (Hydro One, Toronto Hydro, EPCOR, Hydro-Québec)',
    'CCCS (Canadian Centre for Climate Services) hazard scenarios',
    'Insurance Bureau of Canada loss data',
    'ECCC historical weather extremes',
  ]

  return (
    <ReportShell
      jobId={jobId}
      pipelineId="grid-investment-optimizer"
      headerStats={headerStats}
      agentRuntimeSeconds={runtimeSeconds}
      winners={winners}
      sections={sections}
      execSummary={plan.executive_summary}
      sources={sources}
      citationSources={(plan as { citation_sources?: Record<string, { source_id: string; label: string; detail?: string | null; status: 'live' | 'frozen' | 'modeled' | 'llm' }> }).citation_sources}
      onPipelineChange={onPipelineChange}
    />
  )
}

// ── Section 01 · funded portfolio chart ──────────────────────────────── //

function Section01Funded({ plan }: { plan: InvestmentPlan }) {
  if (plan.funded_projects.length === 0) {
    return (
      <VizPanel caption="No projects met the ROI threshold within the budget.">
        <p className="fr-empty">Nothing funded.</p>
      </VizPanel>
    )
  }
  const data = plan.funded_projects.map((f) => ({
    rank: `#${f.rank}`,
    capex_m: Number((f.project.capex_cad / 1e6).toFixed(1)),
    avoided_m: Number((f.project.risk_reduction_cad_per_year / 1e6).toFixed(1)),
  }))
  return (
    <VizPanel
      caption={
        <>
          {plan.funded_projects.length} projects funded · committed{' '}
          <strong>{fmtCAD(plan.total_capex_committed_cad)}</strong> of {fmtCAD(plan.spec.budget_cad)}
        </>
      }
      details={
        <div className="fr-insights">
          {plan.funded_projects.slice(0, 6).map((f) => (
            <FundedCard key={f.project.project_id} f={f} />
          ))}
        </div>
      }
    >
      <div style={{ width: '100%', height: CHART_HEIGHT.hero }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
            <CartesianGrid stroke={CHART_GRID_STROKE} />
            <XAxis dataKey="rank" stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} />
            <YAxis stroke={CHART_AXIS.stroke} tick={CHART_AXIS.tick} unit=" $M" />
            <Tooltip cursor={CHART_HOVER_CURSOR} contentStyle={CHART_TOOLTIP_STYLE} itemStyle={CHART_TOOLTIP_ITEM_STYLE_LEGEND} labelStyle={CHART_TOOLTIP_LABEL_STYLE} />
            <Legend wrapperStyle={CHART_LEGEND_STYLE} />
            <Bar dataKey="capex_m"   name="Capex ($M)"          fill={CATEGORICAL_COLORS[1]} />
            <Bar dataKey="avoided_m" name="Avoided $/yr ($M)"    fill={CATEGORICAL_COLORS[2]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </VizPanel>
  )
}

function FundedCard({ f }: { f: FundedProject }) {
  return (
    <div className="fr-insight">
      <div className="fr-insight-head">
        <strong>#{f.rank} · {f.project.title}</strong>
        <span className="t-mono" style={{ color: 'var(--accent)' }}>{f.roi_ratio.toFixed(1)}× ROI</span>
      </div>
      <dl>
        <dt>Category</dt>
        <dd>{f.project.category.replace(/_/g, ' ')}</dd>
        <dt>Capex</dt>
        <dd>{fmtCAD(f.project.capex_cad)} · {f.project.deployment_months}mo deploy</dd>
        <dt>Avoided loss</dt>
        <dd>{fmtCAD(f.project.risk_reduction_cad_per_year)}/yr</dd>
        <dt>Customers protected</dt>
        <dd>{f.project.customers_protected.toLocaleString()}</dd>
        <dt>Hazards</dt>
        <dd>{f.project.hazards_addressed.join(', ')}</dd>
      </dl>
      {f.project.rationale && (
        <p style={{ marginTop: 6, fontSize: 12, color: 'var(--fg-2)' }}>{f.project.rationale}</p>
      )}
    </div>
  )
}

// ── Section 02 · at-risk asset map (signature MAP) ──────────────────── //

function Section02RiskMap({ plan }: { plan: InvestmentPlan }) {
  // One marker per asset with coords. Color = risk tier. Size = risk magnitude.
  // Shape diamond = "hardening funded", circle = unfunded.
  const profileByAsset = new Map(plan.risk_profiles.map((p) => [p.asset_id, p]))
  const fundedAssetIds = new Set(
    plan.funded_projects.flatMap((f) => f.project.target_assets),
  )
  const markers: MapMarkerSpec[] = plan.assets
    .filter((a) => a.latitude != null && a.longitude != null)
    .map((a) => {
      const p = profileByAsset.get(a.asset_id)
      const tier = p?.risk_tier ?? 'low'
      const color = TIER_COLOR[tier] ?? VERDICT_COLOR.neutral
      // Size by aggregate annual loss — split at $1M and $5M.
      const loss = p?.aggregate_annual_loss_cad ?? 0
      const size: 'sm' | 'md' | 'lg' = loss >= 5_000_000 ? 'lg' : loss >= 1_000_000 ? 'md' : 'sm'
      const funded = fundedAssetIds.has(a.asset_id)
      return {
        id: a.asset_id,
        lat: a.latitude!,
        lon: a.longitude!,
        color,
        size,
        shape: funded ? 'diamond' : 'circle',
        popup: {
          eyebrow: `${a.asset_type.replace(/_/g, ' ')} · age ${a.age_years}y${funded ? ' · hardened' : ''}`,
          title: a.name,
          meta: `Annual loss ${fmtCAD(p?.aggregate_annual_loss_cad)} · tier ${tier.toUpperCase()} · ${a.customers_served.toLocaleString()} customers`,
        },
      }
    })

  if (markers.length === 0) {
    return (
      <VizPanel caption="Asset coordinates unavailable. Risk table shown below.">
        <RiskTable plan={plan} />
      </VizPanel>
    )
  }

  return (
    <VizPanel
      caption={
        <>
          {markers.length} grid asset{markers.length === 1 ? '' : 's'} plotted. Color = risk tier · size = annual loss ·{' '}
          <strong>diamond</strong> = hardening funded
        </>
      }
      details={<RiskTable plan={plan} />}
    >
      <MapView
        markers={markers}
        height={MAP_HEIGHT.dense}
        legend={[
          { label: 'CRITICAL', color: TIER_COLOR.critical },
          { label: 'HIGH',     color: TIER_COLOR.high },
          { label: 'MEDIUM',   color: TIER_COLOR.medium },
          { label: 'LOW',      color: TIER_COLOR.low },
        ]}
      />
    </VizPanel>
  )
}

function RiskTable({ plan }: { plan: InvestmentPlan }) {
  const top = [...plan.risk_profiles]
    .sort((a, b) => b.aggregate_annual_loss_cad - a.aggregate_annual_loss_cad)
    .slice(0, 12)
  const byId = new Map(plan.assets.map((a) => [a.asset_id, a]))
  const fundedAssetIds = new Set(
    plan.funded_projects.flatMap((f) => f.project.target_assets),
  )
  return (
    <div className="reports">
      <div style={{ marginBottom: 8, fontSize: 12, color: 'var(--fg-3)' }}>
        Top {top.length} assets by projected annual climate loss for {plan.spec.target_year}.
      </div>
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Asset</th>
            <th>Type</th>
            <th>Age</th>
            <th>Annual loss</th>
            <th>Tier</th>
            <th>Hardening funded?</th>
            <th>Dominant hazard</th>
          </tr>
        </thead>
        <tbody>
          {top.map((p) => {
            const a = byId.get(p.asset_id)
            const tierC = TIER_COLOR[p.risk_tier] ?? VERDICT_COLOR.neutral
            const dominant = topHazard(p)
            return (
              <tr key={p.asset_id}>
                <td className="num">{p.rank}</td>
                <td className="label">{a?.name ?? p.asset_id}</td>
                <td>{a?.asset_type.replace(/_/g, ' ') ?? '—'}</td>
                <td className="num">{a?.age_years ?? '—'}y</td>
                <td className="num" style={{ color: tierC, fontWeight: 600 }}>{fmtCAD(p.aggregate_annual_loss_cad)}</td>
                <td style={{ color: tierC, fontFamily: 'var(--font-mono)', fontSize: 11 }}>{p.risk_tier.toUpperCase()}</td>
                <td>{fundedAssetIds.has(p.asset_id) ? 'Yes' : '—'}</td>
                <td style={{ fontSize: 12, color: 'var(--fg-2)' }}>{dominant}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function topHazard(p: ClimateRiskProfile): string {
  if (p.hazard_exposures.length === 0) return '—'
  const t = p.hazard_exposures.reduce((acc, h) =>
    !acc || h.annual_probability * h.expected_loss_cad > acc.annual_probability * acc.expected_loss_cad ? h : acc,
  )
  return `${t.hazard.replace(/_/g, ' ')} (${(t.annual_probability * 100).toFixed(0)}%/yr)`
}

// ── Section 03 · hazard donut + unfunded + methodology ───────────────── //

function Section03UnfundedAndMethod({ plan }: { plan: InvestmentPlan }) {
  // Mini-viz: hazard exposure breakdown. Aggregate expected_loss_cad across
  // every (asset × hazard) pair, grouped by hazard string. Shown as a donut
  // so the operator can see "where is the climate loss coming from?"
  const hazardTotals = new Map<string, number>()
  for (const p of plan.risk_profiles) {
    for (const h of p.hazard_exposures) {
      const prev = hazardTotals.get(h.hazard) ?? 0
      hazardTotals.set(h.hazard, prev + h.expected_loss_cad)
    }
  }
  const donutData = Array.from(hazardTotals.entries())
    .map(([hazard, value]) => ({
      name: hazard.replace(/_/g, ' '),
      value: Math.round(value),
    }))
    .sort((a, b) => b.value - a.value)
  const totalLoss = donutData.reduce((s, d) => s + d.value, 0)

  const unfundedTop = plan.unfunded_projects.slice(0, 6)

  return (
    <VizPanel
      caption={
        <>
          Hazard exposure breakdown · total expected loss <strong>{fmtCAD(totalLoss)}/yr</strong> across {plan.risk_profiles.length} assets
        </>
      }
    >
      <div style={{ width: '100%', height: CHART_HEIGHT.mini }}>
        <ResponsiveContainer>
          <PieChart>
            <Tooltip contentStyle={CHART_TOOLTIP_STYLE} itemStyle={CHART_TOOLTIP_ITEM_STYLE_LEGEND} labelStyle={CHART_TOOLTIP_LABEL_STYLE} formatter={(v: unknown) => fmtCAD(Number(v))} />
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
              {donutData.map((_, i) => (
                <Cell key={i} fill={CATEGORICAL_COLORS[i % CATEGORICAL_COLORS.length]} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>

      <div className="fr-meta" style={{ marginTop: 16 }}>
        {unfundedTop.length > 0 && (
          <div>
            <span className="t-eyebrow">Recommended for next budget</span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 10, marginTop: 8 }}>
              {unfundedTop.map((p) => (
                <div key={p.project_id} style={{ background: 'var(--bg-2)', padding: 12, borderRadius: 4 }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--accent)', letterSpacing: 1 }}>
                    {p.category.replace(/_/g, ' ').toUpperCase()}
                  </div>
                  <div style={{ fontFamily: 'var(--font-serif)', fontSize: 15, color: 'var(--fg-1)', marginTop: 4 }}>
                    {p.title}
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, fontSize: 11, color: 'var(--fg-2)', marginTop: 6 }}>
                    <span>Capex: <strong style={{ color: 'var(--fg-1)' }}>{fmtCAD(p.capex_cad)}</strong></span>
                    <span>Avoided/yr: <strong style={{ color: 'var(--fg-1)' }}>{fmtCAD(p.risk_reduction_cad_per_year)}</strong></span>
                    <span>{p.deployment_months}mo</span>
                  </div>
                  {p.rationale && (
                    <div style={{ marginTop: 6, fontSize: 11, color: 'var(--fg-3)' }}>{p.rationale}</div>
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
      </div>
    </VizPanel>
  )
}
