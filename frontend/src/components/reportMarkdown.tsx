import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

// Shared light-markdown renderer used by every Final report's executive
// summary. Handles paragraphs, bullet lists, `#` / `##` / `###` headers,
// `**bold**`, `*italic*`, `` `code` ``, and `[[sN|cited text]]` provenance
// markers (Phase 1: rendered as hover-popover spans tinted by source
// status). Lifted out of FinalReport.tsx so all 5 pipelines render their
// summary the same way (the agents emit markdown markers in every
// pipeline; only siting used to render them).

// ── Citation types ────────────────────────────────────────────────────── //
//
// CitationSource is the metadata for a single source id referenced from
// the executive-summary text via `[[sN|cited text]]` markers. The frontend
// looks the id up in the `sources` dict and renders the wrapped phrase as
// a styled hover/tap target. `status` follows the four-state provenance
// palette documented in REPORTS_COHESION §7b.

export type CitationStatus = 'live' | 'frozen' | 'modeled' | 'llm'

export interface CitationSource {
  source_id: string
  label: string
  detail?: string | null
  status: CitationStatus
}

export type CitationSources = Record<string, CitationSource>

const STATUS_LABEL: Record<CitationStatus, string> = {
  live: 'LIVE',
  frozen: 'FROZEN',
  modeled: 'MODELED',
  llm: 'LLM',
}

// ── Citation popover ─────────────────────────────────────────────────── //
//
// Reuses the design tokens from the Mapbox popup (.skorpio-map .mapboxgl-
// popup-content in MapView.css) so this card reads as a peer of the other
// hover surfaces in the project. Positioned via fixed coords measured from
// the anchor; portaled to document.body so the panel's overflow can't clip
// it. Touch devices: tap toggles instead of hover (matches the rest of the
// hint chrome on mobile).

function CitationPopover({
  anchor,
  source,
}: {
  anchor: HTMLElement
  source: CitationSource
}) {
  const popRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number; flip: 'above' | 'below' }>({
    top: -9999,
    left: -9999,
    flip: 'above',
  })

  useLayoutEffect(() => {
    const place = () => {
      const a = anchor.getBoundingClientRect()
      const pop = popRef.current?.getBoundingClientRect()
      const popW = pop?.width ?? 240
      const popH = pop?.height ?? 80
      const gap = 8
      const margin = 12
      const viewportW = window.innerWidth
      const viewportH = window.innerHeight
      // Prefer above; flip below if there's no room.
      const roomAbove = a.top
      const roomBelow = viewportH - a.bottom
      const flip: 'above' | 'below' = roomAbove >= popH + gap + margin || roomAbove >= roomBelow ? 'above' : 'below'
      const top = flip === 'above' ? Math.max(margin, a.top - popH - gap) : Math.min(viewportH - popH - margin, a.bottom + gap)
      // Center horizontally on the anchor, then clamp to viewport.
      const rawLeft = a.left + a.width / 2 - popW / 2
      const left = Math.max(margin, Math.min(viewportW - popW - margin, rawLeft))
      setPos({ top, left, flip })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [anchor])

  return createPortal(
    <div
      ref={popRef}
      className={`fr-cite-popup fr-cite-popup--${pos.flip}`}
      role="tooltip"
      style={{ top: pos.top, left: pos.left }}
    >
      <div className="fr-cite-popup-eyebrow">Source · {STATUS_LABEL[source.status]}</div>
      <div className="fr-cite-popup-title">{source.label}</div>
      {source.detail && <div className="fr-cite-popup-meta">{source.detail}</div>}
      <span className={`pc-badge pc-${source.status}`}>
        <span className="pc-dot" aria-hidden />
        {STATUS_LABEL[source.status]}
      </span>
    </div>,
    document.body,
  )
}

// ── Citation span ────────────────────────────────────────────────────── //
//
// One inline highlighted phrase. Hover (mouse) or tap (touch) opens the
// popover. Focus also opens it so keyboard users can read the source. A
// global document click outside the span closes it.

function CitationSpan({ source, children }: { source: CitationSource; children: ReactNode }) {
  const ref = useRef<HTMLSpanElement>(null)
  const [open, setOpen] = useState(false)
  // Touch devices: highlights stay visually styled (color + underline) so the
  // provenance signal still reads, but tapping does NOT open a popover. On
  // mobile the cards would block prose and the judge can't scroll past them
  // without dismissing first — strictly worse than no card. Source detail is
  // still available in the desktop view and in the sources panel below.
  const [isTouch] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches,
  )

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [open])

  if (isTouch) {
    return (
      <span ref={ref} className={`fr-cite fr-cite--${source.status}`}>
        {children}
      </span>
    )
  }

  return (
    <>
      <span
        ref={ref}
        className={`fr-cite fr-cite--${source.status}`}
        tabIndex={0}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((o) => !o)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        aria-describedby={open ? `cite-pop-${source.source_id}` : undefined}
      >
        {children}
      </span>
      {open && ref.current && <CitationPopover anchor={ref.current} source={source} />}
    </>
  )
}

// ── Inline renderer ──────────────────────────────────────────────────── //
//
// Order of tokens matters: citation markers are checked FIRST so a `*`
// inside cited text doesn't get eaten as italic. Unknown source ids fall
// back to plain text — backward compat for fixtures without citations.

function renderInline(text: string, baseKey: string, sources?: CitationSources): ReactNode {
  const out: ReactNode[] = []
  let rem = text
  let k = 0
  while (rem.length > 0) {
    let m = rem.match(/^\[\[(s\w+)\|([^\]]+)\]\]/)
    if (m) {
      const id = m[1]
      let inner = m[2]
      let consumed = m[0].length
      // If the marker ends mid-word — e.g. "[[s1|Mississauga]]'s" — the
      // synthesis agent dropped the possessive outside the wrapper.
      // Absorb a trailing apostrophe-suffix or contiguous word-suffix into
      // the highlighted span so the underline reads as one connected word.
      const tail = rem.slice(consumed).match(/^(?:['’]\w+|-\w+)/)
      if (tail) {
        inner = inner + tail[0]
        consumed += tail[0].length
      }
      const src = sources?.[id]
      if (src) {
        out.push(
          <CitationSpan key={`${baseKey}-${k++}`} source={src}>
            {inner}
          </CitationSpan>,
        )
      } else {
        out.push(inner)
      }
      rem = rem.slice(consumed)
      continue
    }
    m = rem.match(/^\*\*([^*]+)\*\*/)
    if (m) {
      out.push(<strong key={`${baseKey}-${k++}`}>{m[1]}</strong>)
      rem = rem.slice(m[0].length)
      continue
    }
    m = rem.match(/^\*([^*]+)\*/)
    if (m) {
      out.push(<em key={`${baseKey}-${k++}`}>{m[1]}</em>)
      rem = rem.slice(m[0].length)
      continue
    }
    m = rem.match(/^`([^`]+)`/)
    if (m) {
      out.push(<code key={`${baseKey}-${k++}`}>{m[1]}</code>)
      rem = rem.slice(m[0].length)
      continue
    }
    const next = rem.search(/[*`[]/)
    if (next === -1) { out.push(rem); break }
    if (next === 0) { out.push(rem[0]); rem = rem.slice(1) }
    else { out.push(rem.slice(0, next)); rem = rem.slice(next) }
  }
  return out
}

export function renderMarkdown(text: string, sources?: CitationSources): ReactNode[] {
  return text
    .split(/\n\n+/)
    .map((raw, i) => {
      const block = raw.trim()
      if (!block) return null
      if (block.startsWith('### ')) return <h4 key={i}>{renderInline(block.slice(4), `h4-${i}`, sources)}</h4>
      if (block.startsWith('## ')) return <h3 key={i}>{renderInline(block.slice(3), `h3-${i}`, sources)}</h3>
      if (block.startsWith('# ')) return <h2 key={i}>{renderInline(block.slice(2), `h2-${i}`, sources)}</h2>
      const lines = block.split('\n')
      if (lines.every((l) => l.trim().startsWith('- '))) {
        return (
          <ul key={i}>
            {lines.map((l, j) => (
              <li key={j}>{renderInline(l.trim().slice(2), `li-${i}-${j}`, sources)}</li>
            ))}
          </ul>
        )
      }
      return <p key={i}>{renderInline(block, `p-${i}`, sources)}</p>
    })
    .filter(Boolean) as ReactNode[]
}
