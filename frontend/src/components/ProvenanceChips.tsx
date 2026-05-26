// Renders the "Data provenance" chip row inside every report shell, plus
// a one-line legend below the row decoding the four colors. The visual
// vocabulary mirrors the existing design-system badges
// (uiux/designsystem/preview/components-chips.html) so the chips read as
// siblings of the Energy-state badges used elsewhere: mono caps label,
// colored dot, soft tinted background, 1px currentColor border.

import type { ProvenanceChip, ProvenanceStatus } from './provenance'

const STATUS_LABEL: Record<ProvenanceStatus, string> = {
  live: 'Live API',
  frozen: 'Frozen snapshot',
  modeled: 'Modeled',
  llm: 'LLM narrative',
}

const LEGEND_ORDER: ProvenanceStatus[] = ['live', 'frozen', 'modeled', 'llm']

export function ProvenanceChips({ chips }: { chips: ProvenanceChip[] }) {
  if (chips.length === 0) return null

  const statusesUsed = new Set(chips.map((c) => c.status))
  const legend = LEGEND_ORDER.filter((s) => statusesUsed.has(s))

  return (
    <div className="pc-block">
      <div className="pc-row" role="list">
        {chips.map((c, i) => (
          <span
            key={i}
            role="listitem"
            className={`pc-chip pc-${c.status}`}
            title={c.hint ?? STATUS_LABEL[c.status]}
          >
            <span className="pc-dot" aria-hidden />
            {c.stage}
          </span>
        ))}
      </div>
      <div className="pc-legend">
        {legend.map((s) => (
          <span key={s} className={`pc-legend-item pc-${s}`}>
            <span className="pc-dot" aria-hidden />
            {STATUS_LABEL[s]}
          </span>
        ))}
      </div>
    </div>
  )
}
