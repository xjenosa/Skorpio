import type { ReactNode } from 'react'
import './VizPanel.css'

// Shared 4-slot body template used inside every stage viz panel (live
// pipeline) AND every report section body (final report). Enforces a
// consistent "caption → viz → details → note" rhythm across all 5
// pipelines × 2 layers so every panel reads as a sibling.
//
//   ┌─ VizPanel ────────────────────────────────────┐
//   │ CAPTION  → one-line mono context              │
//   │ VIZ      → primary chart or map (children)    │
//   │ DETAILS  → insight cards / table              │
//   │ NOTE     → small sources / caveats line       │
//   └───────────────────────────────────────────────┘
//
// All slots except `children` are optional — a stage that only has a viz
// renders as just the viz.

export interface VizPanelProps {
  /** One-line context line above the viz, mono font, dimmed. */
  caption?: ReactNode
  /** The visualization itself — chart, map, donut, etc. */
  children: ReactNode
  /** Insight cards row, ranked table, or any below-the-fold detail. */
  details?: ReactNode
  /** Tiny sources / caveats line at the very bottom. */
  note?: ReactNode
}

export function VizPanel({ caption, children, details, note }: VizPanelProps) {
  return (
    <div className="viz-panel">
      {caption != null && <div className="viz-panel-caption">{caption}</div>}
      <div className="viz-panel-viz">{children}</div>
      {details != null && <div className="viz-panel-details">{details}</div>}
      {note != null && <div className="viz-panel-note">{note}</div>}
    </div>
  )
}
