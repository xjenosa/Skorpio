// Shared visual vocabulary for every report panel (stage vizes + report
// sections). Every chart and every map in Skorpio pulls colors, sizes, and
// chart styling from this file so the 5 pipelines × 2 layers (live stage
// panel + final report) all read like siblings.
//
// One rule: if you find yourself hardcoding a color, axis stroke, or chart
// height inside a section/stage body, you're probably introducing drift —
// pull from here instead.

// ── Verdict colors (severity semantics) ─────────────────────────────── //
// Use these whenever a viz is encoding "is this good/bad?". Same meaning
// across every pipeline, so green always reads as "good" and red as "bad."
export const VERDICT_COLOR = {
  good:     '#6fcf8e',   // PASS / READY / FUNDED / ON-TARGET / STABLE
  warning:  '#e0a44a',   // MARGINAL / CONSTRAINED / SHORTFALL / AT RISK
  critical: '#f38764',   // FAIL / BLOCKED / UNDER-PLANNED / CRITICAL
  neutral:  '#b3b1a8',   // UNKNOWN / not yet scored
} as const

// ── Categorical palette (when distinguishing types, not severity) ───── //
// Fixed order. The first chart series gets `[0]`, the second gets `[1]`,
// etc. — so "the orange one" reads the same in every chart.
export const CATEGORICAL_COLORS = [
  '#f38764',  // Skorpio accent orange
  '#7aa2f7',  // cool blue
  '#6fcf8e',  // mint green
  '#c889e6',  // lavender
  '#e0a44a',  // wheat
] as const

// ── Chart dimensions + axis styling ─────────────────────────────────── //
// Two heights: "hero" for the headline chart in a section (~340px) and
// "detail" for smaller in-line charts (~280px). Anything in between is
// drift — pick one.
export const CHART_HEIGHT = {
  hero:   340,
  detail: 280,
  mini:   180,   // for section-03 weight/severity strip charts
} as const

// Recharts axis + tooltip props shared across every chart.
export const CHART_AXIS = {
  stroke: '#6f6c63',
  tick: { fontSize: 10, fill: '#6f6c63' },
} as const

export const CHART_TOOLTIP_STYLE = {
  background: '#161614',
  border: '1px solid #2a2824',
  fontSize: 12,
  color: '#faf9f5',
} as const

// Recharts renders each metric row inside the tooltip as a separate <li>
// styled by `itemStyle` — which defaults to black on a dark background.
// Pass this prop on every <Tooltip> so the "<series-name> : <value>" line
// reads as cream-on-dark instead of being invisible. The heading row
// ("#2", "L6P") is controlled separately by `labelStyle`.
//
// Use the *_LEGEND variant on charts with a multi-series <Legend> (e.g.
// HP/EV/Years bars, Capex/Avoided bars, stacked area charts). The empty
// object lets Recharts fall back to each series's own stroke/fill color
// per row, so the tooltip rows match the legend chips and the bars they
// describe. Single-series charts should keep `CHART_TOOLTIP_ITEM_STYLE`
// (cream) — coloring one row with the series color when there's only one
// row reads as noise, not signal.
export const CHART_TOOLTIP_ITEM_STYLE = {
  color: '#faf9f5',
} as const

export const CHART_TOOLTIP_ITEM_STYLE_LEGEND = {} as const

export const CHART_TOOLTIP_LABEL_STYLE = {
  color: '#faf9f5',
  fontWeight: 600,
  marginBottom: 4,
} as const

export const CHART_GRID_STROKE = '#2a2824'

// Bar-chart Tooltip cursor. Recharts defaults to a light gray fill
// (`#ccc` @ 30%) which looks bad on our dark theme — set this on every
// <Tooltip> inside a <BarChart> so the hover overlay reads as a subtle
// dark highlight instead of a jarring white box.
export const CHART_HOVER_CURSOR = {
  fill: 'rgba(250, 249, 245, 0.05)',
} as const

// Recharts <Legend> wrapperStyle. Without an explicit color, Recharts
// renders legend labels in browser-default black — invisible against the
// dark `.fr-section-body` background. Set on every <Legend> across reports
// and stage vizes so all chart legends read as cream-on-dark.
export const CHART_LEGEND_STYLE = {
  fontSize: 10,
  color: '#faf9f5',
} as const

// Muted bar fill — used when a chart highlights a "top N" subset with the
// accent color and renders the rest as background context. The previous
// `rgba(250,249,245,0.45)` (near-white at 45% alpha) looked fine on the
// dark panel but vanished when printed (because print drops dark CSS
// backgrounds, leaving a near-white bar on a white page). This warm mid-
// grey is the same value as `CHART_AXIS.stroke` — visible on both the dark
// dashboard and a printed white page, and stays in the design palette.
export const CHART_MUTED_BAR = '#6f6c63'

// ── Map marker grammar ──────────────────────────────────────────────── //
// Shape + size encode the same meaning across every map:
//   shape — circle = candidate/data point, diamond = anchor/existing/known
//   size  — sm = low importance, md = default, lg = critical/highlighted
// The MapView component reads these via the MapMarkerSpec interface.
export const MARKER_SIZE = {
  low:  'sm',
  mid:  'md',
  high: 'lg',
} as const

// ── Map heights ─────────────────────────────────────────────────────── //
// Two heights: dense (many markers) and standard.
export const MAP_HEIGHT = {
  standard: 360,
  dense:    420,
} as const

// ── Verdict-color helpers ───────────────────────────────────────────── //
// Convenience map for the most common string-keyed verdicts the agents
// emit. Use these when a plan field gives you "PASS" / "FAIL" / etc.
export const VERDICT_BY_STRING: Record<string, string> = {
  PASS:           VERDICT_COLOR.good,
  READY:          VERDICT_COLOR.good,
  FUNDED:         VERDICT_COLOR.good,
  'ON-TARGET':    VERDICT_COLOR.good,
  STABLE:         VERDICT_COLOR.good,

  MARGINAL:       VERDICT_COLOR.warning,
  CONSTRAINED:    VERDICT_COLOR.warning,
  SHORTFALL:      VERDICT_COLOR.warning,
  'AT RISK':      VERDICT_COLOR.warning,
  'AT-RISK':      VERDICT_COLOR.warning,

  FAIL:           VERDICT_COLOR.critical,
  BLOCKED:        VERDICT_COLOR.critical,
  'UNDER-FUNDED': VERDICT_COLOR.critical,
  'UNDER-PLANNED':VERDICT_COLOR.critical,
  CRITICAL:       VERDICT_COLOR.critical,
}

export function verdictColor(verdict: string | null | undefined): string {
  if (!verdict) return VERDICT_COLOR.neutral
  return VERDICT_BY_STRING[verdict] ?? VERDICT_COLOR.neutral
}
