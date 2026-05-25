import { useMemo } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Tooltip,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
} from 'recharts'
import type { PlacementScore, SitingPlan } from '../../api/types'
import { CATEGORICAL_COLORS } from '../reportStyle'

// Stage 5 — Plan Synthesis. Two side-by-side charts: a ranked bar of the top
// candidates' LCOE, and a 6-axis radar of the top-1 candidate's normalised
// Pareto objectives. Both built from real plan data only — empty-state when
// the plan or its pareto_objectives aren't available.

export interface SynthesisRadarBarProps {
  plan?: SitingPlan | null
}

function radarFromCandidate(c: PlacementScore | undefined) {
  if (!c?.site.pareto_objectives) return null
  const p = c.site.pareto_objectives
  return [
    { axis: 'Cost', value: p.cost_economics },
    { axis: 'Carbon', value: p.carbon_intensity },
    { axis: 'Latency', value: p.latency_fit },
    { axis: 'Headroom', value: p.transmission_headroom },
    { axis: 'Speed', value: p.deployment_speed },
    { axis: 'Resilience', value: p.operational_resilience },
  ]
}

export function SynthesisRadarBar({ plan }: SynthesisRadarBarProps) {
  const top = plan?.top_candidates?.slice(0, 6) ?? []
  const bars = useMemo(
    () => top.map((c) => ({ label: c.site.name, cost: c.levelized_cost_usd_mwh })),
    [top],
  )
  const radar = useMemo(() => radarFromCandidate(top[0]), [top])
  const winner = top[0]?.site.name ?? 'Top candidate'

  if (bars.length === 0) {
    return (
      <div className="stage-viz-pending">
        <span className="t-eyebrow">No data</span>
        <p>Ranked candidates will appear after the run finishes.</p>
      </div>
    )
  }

  return (
    <div className="viz-split">
      <div className="viz-card">
        <div className="viz-card-head">
          <span className="t-eyebrow">Ranked candidates</span>
          <span className="t-mono">{bars.length}</span>
        </div>
        <div className="viz-card-body">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bars} layout="vertical" margin={{ top: 4, right: 16, bottom: 8, left: 8 }}>
              <XAxis
                type="number"
                stroke="var(--fg-3)"
                tick={{ fill: 'var(--fg-3)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
              />
              <YAxis
                type="category"
                dataKey="label"
                width={130}
                stroke="var(--fg-3)"
                tick={{ fill: 'var(--fg-2)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
              />
              <Tooltip
                cursor={{ fill: 'rgba(243,135,100,0.06)' }}
                contentStyle={{
                  background: 'rgba(38,38,36,0.95)',
                  border: '1px solid var(--rule-2)',
                  borderRadius: 8,
                  color: 'var(--fg-1)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                }}
                itemStyle={{ color: 'var(--fg-1)' }}
                labelStyle={{ color: 'var(--fg-1)', fontWeight: 600 }}
                formatter={(v: unknown) => [`$${v} /MWh`, 'LCOE']}
              />
              <Bar dataKey="cost" fill={CATEGORICAL_COLORS[0]} radius={[2, 2, 2, 2]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="viz-card">
        <div className="viz-card-head">
          <span className="t-eyebrow">Top objective profile</span>
          <span className="t-mono">{winner}</span>
        </div>
        <div className="viz-card-body">
          {radar ? (
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radar}>
                <PolarGrid stroke="rgba(250,249,245,0.08)" />
                <PolarAngleAxis
                  dataKey="axis"
                  tick={{ fill: 'var(--fg-2)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
                />
                <PolarRadiusAxis
                  domain={[0, 1]}
                  tick={false}
                  axisLine={false}
                  stroke="rgba(250,249,245,0.08)"
                />
                <Radar
                  dataKey="value"
                  stroke={CATEGORICAL_COLORS[0]}
                  fill={CATEGORICAL_COLORS[0]}
                  fillOpacity={0.25}
                  isAnimationActive
                />
              </RadarChart>
            </ResponsiveContainer>
          ) : (
            <div className="viz-card-empty">
              <span className="t-mono">Pareto objectives not scored for top candidate.</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
