import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { PIPELINES, type PipelineId } from '../pipelines'

// Shared dropdown for re-tagging a job's pipeline. Used by:
//   - the "Routed to ... · change" pill in the Agent pipeline header
//   - the pipeline badge inside each Reports table row
//
// The menu is portaled to document.body and `position: fixed` so it never
// gets clipped by table/overflow ancestors. Placement flips upward when
// there isn't enough room below. Visual identity matches the NewSession
// composer's pipeline picker (.pipeline-menu rules).

const MENU_WIDTH = 280       // matches .pipeline-menu min-width
const MENU_MAX_HEIGHT = 360  // matches .pipeline-menu max-height
const GAP = 6                // gap between trigger and menu

interface Placement {
  top: number
  left: number
  flipped: boolean
}

export interface PipelineTagPickerProps {
  /** Current pipeline_id on the job — highlighted as active in the menu. */
  current: PipelineId | null | undefined
  /** Called with the selected pipeline_id when the user picks one. */
  onSelect: (pipelineId: PipelineId) => void
  /** Render-prop for the trigger. Receives the open/close handler + state. */
  renderTrigger: (args: {
    open: boolean
    toggle: () => void
    triggerRef: React.RefObject<HTMLButtonElement>
    disabled: boolean
  }) => React.ReactNode
  /** Menu alignment relative to the trigger — left edge (default) or right edge. */
  align?: 'left' | 'right'
  /** Optional extra className on the wrapper (used by callers for layout/z-index). */
  wrapperClassName?: string
  /** When true, the picker is non-interactive: the menu never opens and
   *  selection is blocked. The trigger render-prop receives `disabled` so it
   *  can reflect the state visually. Used while a job is still running, since
   *  re-tagging a live job mid-stream can confuse the orchestrator. */
  disabled?: boolean
}

export function PipelineTagPicker({
  current,
  onSelect,
  renderTrigger,
  align = 'left',
  wrapperClassName,
  disabled = false,
}: PipelineTagPickerProps) {
  const [open, setOpen] = useState(false)
  const [placement, setPlacement] = useState<Placement | null>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLUListElement>(null)

  // If we become disabled while the menu is open, close it.
  useEffect(() => {
    if (disabled && open) setOpen(false)
  }, [disabled, open])

  const toggle = () => {
    if (disabled) return
    setOpen((o) => !o)
  }
  const pick = (id: PipelineId) => {
    if (disabled) return
    onSelect(id)
    setOpen(false)
  }

  // Compute menu placement (fixed-position coords + flip-up if needed).
  // Re-runs on open + scroll + resize so the menu tracks the trigger.
  const recomputePlacement = () => {
    if (!triggerRef.current) return
    const r = triggerRef.current.getBoundingClientRect()
    const menuH = menuRef.current?.offsetHeight ?? MENU_MAX_HEIGHT
    const spaceBelow = window.innerHeight - r.bottom
    const flipped = spaceBelow < menuH + GAP && r.top > menuH + GAP
    const top = flipped ? r.top - menuH - GAP : r.bottom + GAP
    const left = align === 'right'
      ? Math.max(8, r.right - MENU_WIDTH)
      : Math.min(r.left, window.innerWidth - MENU_WIDTH - 8)
    setPlacement({ top, left, flipped })
  }

  // useLayoutEffect so the position is set before paint — no visual jump.
  useLayoutEffect(() => {
    if (!open) {
      setPlacement(null)
      return
    }
    recomputePlacement()
    // Capture-phase scroll listener catches scrolling inside nested
    // containers too (not just window scroll).
    const onScroll = () => recomputePlacement()
    const onResize = () => recomputePlacement()
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onResize)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, align])

  // Re-measure once the menu has actually rendered (we used MENU_MAX_HEIGHT
  // as a placeholder before; now we know the real height).
  useLayoutEffect(() => {
    if (open && menuRef.current) recomputePlacement()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, placement === null])

  // Click-outside + Escape to close. The menu lives in a portal, so we
  // need to check menuRef as well as wrapperRef.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (wrapperRef.current?.contains(t)) return
      if (menuRef.current?.contains(t)) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div
      ref={wrapperRef}
      className={`pipeline-picker${wrapperClassName ? ` ${wrapperClassName}` : ''}`}
    >
      {renderTrigger({ open, toggle, triggerRef, disabled })}
      {open && !disabled && createPortal(
        <ul
          ref={menuRef}
          className="pipeline-menu pipeline-menu--portal"
          role="listbox"
          aria-label="Re-tag pipeline"
          style={{
            position: 'fixed',
            top: placement?.top ?? -9999,
            left: placement?.left ?? -9999,
            right: 'auto',
            minWidth: MENU_WIDTH,
            // Hide the menu until the first placement calc lands so the
            // first paint isn't a flash in the top-left corner.
            visibility: placement ? 'visible' : 'hidden',
          }}
        >
          {PIPELINES.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                role="option"
                aria-selected={current === p.id}
                className={`pipeline-menu-item${current === p.id ? ' active' : ''}`}
                onClick={(e) => {
                  e.stopPropagation()
                  pick(p.id)
                }}
              >
                <span className="pipeline-menu-row">
                  <span
                    className="pipeline-menu-dot"
                    style={{ background: p.accent }}
                  />
                  <span className="pipeline-menu-label" style={{ color: p.accent }}>
                    {p.label}
                  </span>
                </span>
                <span className="pipeline-menu-sub">{p.blurb}</span>
              </button>
            </li>
          ))}
        </ul>,
        document.body,
      )}
    </div>
  )
}
