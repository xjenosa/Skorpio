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

  // Sort chips by status (live → frozen → modeled → llm) so the row reads
  // as colored blocks rather than speckled colors. Stable sort preserves
  // the original pipeline-stage order within each status bucket — JS
  // Array.sort has been spec-stable since ES2019.
  const statusRank: Record<ProvenanceStatus, number> = {
    live: 0, frozen: 1, modeled: 2, llm: 3,
  }
  const sortedChips = [...chips].sort((a, b) => statusRank[a.status] - statusRank[b.status])

  return (
    <div className="pc-block">
      <div className="pc-row" role="list">
        {sortedChips.map((c, i) => (
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
