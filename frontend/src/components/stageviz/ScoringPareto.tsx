import { useMemo } from 'react'
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  ZAxis,
} from 'recharts'
import type { SitingPlan } from '../../api/types'
import { CATEGORICAL_COLORS } from '../reportStyle'

// Stage 4 — Scoring. Cost-vs-deployment scatter (lower-left wins on both
// axes). Points are drawn from `plan.top_candidates` only — no synthetic
// fallback. Renders an empty-state panel when the plan isn't loaded yet.

export interface ScoringParetoProps {
  plan: SitingPlan | null
}

interface Point {
  cost: number
  speed: number
  label: string
  rank: number
}

export function ScoringPareto({ plan }: ScoringParetoProps) {
  const points: Point[] = useMemo(() => {
    if (!plan?.top_candidates?.length) return []
    return plan.top_candidates.map((c) => ({
      cost: c.levelized_cost_usd_mwh,
      speed: c.site.profile.deployment_months ?? 18,
      label: c.site.name,
      rank: c.rank,
    }))
  }, [plan])

  if (points.length === 0) {
    return (
      <div className="stage-viz-pending">
        <span className="t-eyebrow">No data</span>
        <p>Scored candidates will appear after the run finishes.</p>
      </div>
    )
  }

  const winners = points.filter((p) => p.rank <= 3)
  const others = points.filter((p) => p.rank > 3)

  return (
    <div className="viz-pareto">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 12, right: 16, bottom: 32, left: 40 }}>
          <CartesianGrid stroke="rgba(250,249,245,0.06)" />
          <XAxis
            type="number"
            dataKey="cost"
            name="LCOE"
            unit="$"
            stroke="var(--fg-3)"
            tick={{ fill: 'var(--fg-3)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
            label={{
              value: 'Levelized cost ($/MWh), lower is better',
              position: 'insideBottom',
              offset: -16,
              fill: 'var(--fg-3)',
              fontSize: 11,
            }}
          />
          <YAxis
            type="number"
            dataKey="speed"
            name="Deploy"
            unit="mo"
            stroke="var(--fg-3)"
            tick={{ fill: 'var(--fg-3)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
            label={{
              value: 'Time to power (months)',
              angle: -90,
              position: 'insideLeft',
              fill: 'var(--fg-3)',
              fontSize: 11,
            }}
          />
          <ZAxis range={[40, 120]} />
          <Tooltip
            cursor={{ stroke: 'var(--accent-line)' }}
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
            formatter={(value: unknown, _name, item) => {
              const payload = (item as { payload?: Point }).payload
              return [`${value}`, payload?.label ?? '']
            }}
          />
          <Scatter name="Candidates" data={others} fill="rgba(250,249,245,0.55)" />
          <Scatter name="Top 3" data={winners} fill={CATEGORICAL_COLORS[0]} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}
