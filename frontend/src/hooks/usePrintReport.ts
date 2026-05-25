import { useEffect, useState } from 'react'
import { prepareAllMapsForPrint } from '../components/MapView'

// Coordinates the "Print report" flow for the report tabs. Returns a
// `printing` flag that callers should OR into their section-open checks so
// every collapsed section renders in the print snapshot, plus a `print()`
// trigger that fires the native browser print dialog after the next paint.
//
// We wait two animation frames before calling window.print() so React has
// committed the expanded-section DOM (and recharts has rendered its SVG)
// before the browser captures the page. The `afterprint` event resets the
// flag once the user closes the dialog (or cancels), collapsing the
// previously-closed sections back.
export function usePrintReport(title?: string) {
  const [printing, setPrinting] = useState(false)

  useEffect(() => {
    if (!printing) return

    // Browsers use document.title for the print dialog header and the default
    // "Save as PDF" filename. Swap it for the report-specific title while the
    // dialog is open, then restore on afterprint so the tab title doesn't
    // stay clobbered.
    const previousTitle = document.title
    if (title) document.title = title

    const onAfter = () => {
      document.title = previousTitle
      setPrinting(false)
    }
    window.addEventListener('afterprint', onAfter)

    // Wait two animation frames so React has committed the expanded
    // sections, then a longer timeout so recharts' ResponsiveContainer can
    // measure its parent + paint the SVG, and so any in-flight images
    // settle. 150ms wasn't enough when several previously-collapsed
    // sections mount at once — Chrome would snapshot half-rendered charts
    // and emit a corrupted PDF ("Failed to load PDF document").
    //
    // After the settle, we await prepareAllMapsForPrint() so every
    // MapView resizes for the print stylesheet's height, re-fits to its
    // current marker bbox, bumps pixel ratio for sharp rasterisation,
    // and signals 'idle' before the snapshot reads the WebGL framebuffer.
    // Without this, sections that were collapsed on screen (and only
    // forced open by the print CSS) tended to print at the default
    // Canada view because their fitBounds hadn't run.
    let timer: ReturnType<typeof setTimeout> | null = null
    let cancelled = false
    let raf2 = 0
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        timer = setTimeout(async () => {
          await prepareAllMapsForPrint()
          if (cancelled) return
          window.print()
        }, 500)
      })
    })

    return () => {
      cancelled = true
      window.removeEventListener('afterprint', onAfter)
      cancelAnimationFrame(raf1)
      if (raf2) cancelAnimationFrame(raf2)
      if (timer) clearTimeout(timer)
      document.title = previousTitle
    }
  }, [printing, title])

  return { printing, print: () => setPrinting(true) }
}
