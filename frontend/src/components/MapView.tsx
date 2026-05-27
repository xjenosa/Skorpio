import { useEffect, useRef } from 'react'
import mapboxgl, { LngLatBoundsLike, Map as MapboxMap, Marker, Popup } from 'mapbox-gl'
import './MapView.css'

// Skorpio-styled wrapper around mapbox-gl. Used in every pipeline's report
// (one section per pipeline gets the map as its headline visual). When
// VITE_MAPBOX_TOKEN isn't set, falls back to a coords list so the UI
// still renders for contributors without a token.

const TOKEN = (import.meta.env.VITE_MAPBOX_TOKEN as string | undefined) ?? ''
// Skorpio's dark style — minimal land/roads, no POI clutter. We hide the
// remaining POI/transit layers programmatically once the style loads.
const MAP_STYLE = 'mapbox://styles/mapbox/dark-v11'
const HIDE_LAYERS_PREFIXES = ['poi-', 'transit-', 'airport-', 'natural-point-']

if (TOKEN) {
  mapboxgl.accessToken = TOKEN
}

export interface MapMarkerSpec {
  id: string
  lat: number
  lon: number
  color: string                              // hex, e.g. '#f38764'
  size?: 'sm' | 'md' | 'lg'                  // default 'md'
  shape?: 'circle' | 'diamond'               // default 'circle'
  popup?: {
    eyebrow?: string
    title: string
    meta?: string
  }
}

export interface MapLineSpec {
  id: string
  // [lon, lat] pairs (Mapbox order is lon-lat, not lat-lon).
  coordinates: [number, number][]
  color: string
  width?: number
  opacity?: number
  dashed?: boolean
}

export interface MapLegendItem {
  label: string
  color: string
}

export interface MapViewProps {
  markers: MapMarkerSpec[]
  lines?: MapLineSpec[]
  legend?: MapLegendItem[]
  /** Height in px. Default 420. */
  height?: number
  /** 'auto' (default) fits to marker extent + padding. */
  initialView?: 'canada' | 'gta' | 'auto'
}

const PRESET_BOUNDS: Record<string, LngLatBoundsLike> = {
  canada: [[-141, 41], [-52, 70]],
  gta:    [[-80.0, 43.3], [-79.0, 44.0]],
}

// ── Print coordination ────────────────────────────────────────────────── #
//
// usePrintReport calls prepareAllMapsForPrint() before window.print() so
// every MapView on the page has a chance to (a) resize for the print
// stylesheet's forced height, (b) re-fit to its current marker bbox so
// the snapshot doesn't capture a stale default-Canada view, (c) bump the
// canvas pixel ratio for sharper rasterisation, and (d) settle (idle
// event) before the print engine reads the WebGL framebuffer.
//
// Each MapView registers a preparer on mount and deregisters on unmount.
// Promise.race against a hard 4s timeout so a hung map can't block the
// print dialog forever.
type MapPreparer = () => Promise<void>
const printPreparers = new Set<MapPreparer>()

export async function prepareAllMapsForPrint(): Promise<void> {
  const all = Array.from(printPreparers)
  if (all.length === 0) return
  await Promise.race([
    Promise.all(all.map((p) => p().catch(() => undefined))),
    new Promise<void>((resolve) => setTimeout(resolve, 4000)),
  ])
}


export function MapView({
  markers,
  lines = [],
  legend,
  height = 420,
  initialView = 'auto',
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapboxMap | null>(null)
  const markerObjectsRef = useRef<Marker[]>([])
  // Hover popups are added to the map on mouseenter and removed on
  // mouseleave (with a short grace period), so they aren't bound to the
  // marker via setPopup. Track them so they can be wiped on re-render.
  const popupObjectsRef = useRef<Popup[]>([])
  // Auto-fit should happen ONCE per map mount. Without this guard, every
  // parent re-render (which creates a new markers[] reference) snaps the
  // user's pan/zoom back to the marker bounds — the classic "I scrolled and
  // it bounced back" bug.
  const hasFitOnceRef = useRef(false)
  // Latest markers snapshot for the print preparer (registered once on
  // mount, so it would otherwise close over stale data).
  const markersRef = useRef(markers)
  markersRef.current = markers

  // One-time map construction. Hooks always run regardless of TOKEN so the
  // hook order stays stable across renders (rules of hooks).
  useEffect(() => {
    if (!TOKEN || !containerRef.current || mapRef.current) return
    const container = containerRef.current
    const map = new mapboxgl.Map({
      container,
      style: MAP_STYLE,
      bounds: PRESET_BOUNDS[initialView] ?? PRESET_BOUNDS.canada,
      fitBoundsOptions: { padding: 40 },
      attributionControl: true,
      dragRotate: false,
      pitchWithRotate: false,
      // Mapbox v3 enables "cooperative gestures" by default on small viewports,
      // which makes plain scroll-wheel pan the page instead of zoom the map
      // and shows a "Use ctrl + scroll to zoom" hint. We want raw wheel-zoom,
      // so disable it explicitly.
      cooperativeGestures: false,
      // Keep the WebGL framebuffer around between paints so Chrome's
      // print snapshot can read the rendered tiles into the PDF. With
      // this off (the default), the map prints as a blank box because
      // the GPU has already discarded the framebuffer by the time the
      // snapshot captures the page. The cost is a small bump in GPU
      // memory per map instance, which is negligible for the handful
      // of map panels a report renders.
      preserveDrawingBuffer: true,
    })
    map.scrollZoom.enable()
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right')

    // On touch devices the map's pan/pinch gestures swallow vertical page
    // scrolls — a judge swiping through a report gets stuck inside any map
    // they touch. Disable interactive gestures on coarse pointers so the
    // map becomes a static-with-markers thumbnail and the page scrolls
    // straight past it. Desktop behavior is unchanged.
    if (typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches) {
      map.dragPan.disable()
      map.scrollZoom.disable()
      map.touchZoomRotate.disable()
      map.doubleClickZoom.disable()
    }

    // Block page scroll while the cursor is over the map container.
    // ``capture: true`` runs this BEFORE any descendant handler (incl.
    // Mapbox's own canvas wheel handler), and ``passive: false`` is what
    // actually allows ``preventDefault`` to work on wheel events — without
    // it Chrome silently ignores the call (since 2017). Mapbox still gets
    // the event afterwards in the target/bubble phase and zooms the map.
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
    }
    container.addEventListener('wheel', onWheel, { passive: false, capture: true })

    map.on('load', () => {
      const style = map.getStyle()
      style?.layers?.forEach((layer) => {
        if (HIDE_LAYERS_PREFIXES.some((p) => layer.id.startsWith(p))) {
          map.setLayoutProperty(layer.id, 'visibility', 'none')
        }
      })
    })

    mapRef.current = map
    return () => {
      container.removeEventListener('wheel', onWheel, { capture: true })
      map.remove()
      mapRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Print-prep registration. Mounts once per map instance and reads
  // markersRef.current at print time so the bbox reflects the latest
  // data even if markers updated after registration. The preparer:
  //   1. Temporarily forces the container's inline height to match what
  //      the print stylesheet will impose (.skorpio-map { height: 360px })
  //      and restores it on afterprint. Without this, resize() picks up
  //      the on-screen height and Mapbox sizes the canvas to that, so
  //      when the print media query activates the canvas overflows and
  //      the bottom gets clipped.
  //   2. resize() so the canvas matches the print-target container size.
  //   3. setPixelRatio bumps canvas resolution so the rasterised print
  //      isn't blurry. Capped at 3 to stay sane on weaker GPUs.
  //   4. fitBounds re-centres on the current data with print-aspect-ratio
  //      aware padding so a section that was collapsed on screen (and
  //      only forced open by the print stylesheet) doesn't snapshot at
  //      the default Canada view.
  //   5. Resolves on the next idle event so the framebuffer has settled
  //      before the print snapshot reads it.
  useEffect(() => {
    if (!TOKEN) return
    const PRINT_MAP_HEIGHT = 360
    const preparer: MapPreparer = () => {
      return new Promise<void>((resolve) => {
        const map = mapRef.current
        const container = containerRef.current
        if (!map || !container) {
          resolve()
          return
        }
        // Snapshot the current inline height (usually empty string since
        // the component sets it via the style prop, but capture defensively)
        // so afterprint can restore exactly what was there before.
        const previousHeight = container.style.height
        container.style.setProperty('height', `${PRINT_MAP_HEIGHT}px`, 'important')

        const restore = () => {
          if (previousHeight) {
            container.style.height = previousHeight
          } else {
            container.style.removeProperty('height')
          }
          map.resize()
        }
        window.addEventListener('afterprint', restore, { once: true })

        try {
          map.resize()
          const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1
          const target = Math.min(3, Math.max(2, dpr * 2))
          const mAny = map as unknown as { setPixelRatio?: (n: number) => void }
          if (typeof mAny.setPixelRatio === 'function') {
            mAny.setPixelRatio(target)
          }
          const ms = markersRef.current
          if (ms.length > 0) {
            const bounds = new mapboxgl.LngLatBounds()
            ms.forEach((m) => bounds.extend([m.lon, m.lat]))
            map.fitBounds(bounds, {
              padding: 40,
              maxZoom: 11,
              animate: false,
              duration: 0,
            })
          }
          map.once('idle', () => resolve())
        } catch {
          resolve()
        }
      })
    }
    printPreparers.add(preparer)
    return () => {
      printPreparers.delete(preparer)
    }
  }, [])

  // Sync markers + lines + auto-fit. Runs whenever those props change.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const applyMarkersAndLines = () => {
      // Markers — drop all previous, recreate from scratch. Cheap for the
      // marker counts we deal with (~10-100 per pipeline). Popups added on
      // hover are tracked separately so we can wipe any that happen to be
      // open mid-render.
      markerObjectsRef.current.forEach((m) => m.remove())
      markerObjectsRef.current = []
      popupObjectsRef.current.forEach((p) => p.remove())
      popupObjectsRef.current = []
      markers.forEach((m) => {
        const el = document.createElement('div')
        const sizeClass = m.size ? ` skorpio-marker--${m.size}` : ''
        const shapeClass = m.shape === 'diamond' ? ' skorpio-marker--diamond' : ''
        el.className = `skorpio-marker${sizeClass}${shapeClass}`
        el.style.color = m.color
        el.style.background = m.color
        // No popup = nothing happens on click/hover, so the marker should
        // feel like part of the map underneath it. `grab` matches Mapbox's
        // canvas cursor so the operator's mental model is "this diamond is
        // map, not UI" — e.g. anchor diamonds in the Expansion footprint
        // map. Default `.skorpio-marker` CSS sets `pointer`; we override.
        if (!m.popup) {
          el.style.cursor = 'grab'
        }

        const marker = new Marker(el).setLngLat([m.lon, m.lat])
        marker.addTo(map)
        markerObjectsRef.current.push(marker)

        if (m.popup) {
          // Hover-only popup. We don't use `marker.setPopup()` because that
          // binds click-to-toggle; the spec is pure hover. `closeButton:
          // false` removes the x (no click target needed) and
          // `closeOnClick: false` keeps an accidental map-pan click from
          // dismissing it before the cursor leaves. A short grace period
          // lets the cursor cross the gap from marker to popup body
          // without flicker.
          const html = `
            ${m.popup.eyebrow ? `<div class="skorpio-popup-eyebrow">${escapeHtml(m.popup.eyebrow)}</div>` : ''}
            <div class="skorpio-popup-title">${escapeHtml(m.popup.title)}</div>
            ${m.popup.meta ? `<div class="skorpio-popup-meta">${escapeHtml(m.popup.meta)}</div>` : ''}
          `.trim()
          const popup = new Popup({
            offset: 14,
            closeButton: false,
            closeOnClick: false,
          }).setHTML(html)
          popupObjectsRef.current.push(popup)

          let hideTimer: ReturnType<typeof setTimeout> | null = null
          const cancelHide = () => {
            if (hideTimer) {
              clearTimeout(hideTimer)
              hideTimer = null
            }
          }
          const scheduleHide = () => {
            cancelHide()
            hideTimer = setTimeout(() => popup.remove(), 120)
          }
          const show = () => {
            cancelHide()
            if (!popup.isOpen()) {
              popup.setLngLat([m.lon, m.lat]).addTo(map)
            }
            const popupEl = popup.getElement()
            if (popupEl) {
              popupEl.onmouseenter = cancelHide
              popupEl.onmouseleave = scheduleHide
            }
          }
          el.addEventListener('mouseenter', show)
          el.addEventListener('mouseleave', scheduleHide)
        }
      })

      // Lines — strip previous, add fresh.
      const style = map.getStyle()
      style?.layers?.forEach((l) => {
        if (l.id.startsWith('skorpio-line-') && map.getLayer(l.id)) {
          map.removeLayer(l.id)
        }
      })
      Object.keys(style?.sources ?? {}).forEach((sid) => {
        if (sid.startsWith('skorpio-line-') && map.getSource(sid)) {
          map.removeSource(sid)
        }
      })
      lines.forEach((line) => {
        const sourceId = `skorpio-line-${line.id}`
        map.addSource(sourceId, {
          type: 'geojson',
          data: {
            type: 'Feature',
            properties: {},
            geometry: { type: 'LineString', coordinates: line.coordinates },
          },
        })
        map.addLayer({
          id: sourceId,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': line.color,
            'line-width': line.width ?? 2,
            'line-opacity': line.opacity ?? 0.8,
            ...(line.dashed ? { 'line-dasharray': [2, 2] } : {}),
          },
        })
      })

      // Only auto-fit on the FIRST render that has markers. After that, the
      // user owns the viewport — pan/zoom must stick across re-renders.
      if (!hasFitOnceRef.current && initialView === 'auto' && markers.length > 0) {
        const bounds = new mapboxgl.LngLatBounds()
        markers.forEach((m) => bounds.extend([m.lon, m.lat]))
        map.fitBounds(bounds, { padding: 60, maxZoom: 11, duration: 0 })
        hasFitOnceRef.current = true
      }
    }

    if (map.loaded()) {
      applyMarkersAndLines()
    } else {
      map.once('load', applyMarkersAndLines)
    }
  }, [markers, lines, initialView])

  // Fallback render when no token. Hooks above still ran (they no-op'd on
  // the !TOKEN check inside) so this conditional return is rule-safe.
  if (!TOKEN) {
    return (
      <div className="skorpio-map-fallback">
        <div className="skorpio-map-fallback-head">
          <svg
            className="skorpio-map-fallback-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M9 20l-5.447 -2.724a1 1 0 0 1 -.553 -.894v-13.382a1 1 0 0 1 1.447 -.894l5.553 2.894 6 -3 5.447 2.724a1 1 0 0 1 .553 .894v13.382a1 1 0 0 1 -1.447 .894l-5.553 -2.894z" />
            <path d="M9 4v16" />
            <path d="M15 7v13" />
          </svg>
          <strong>Map preview unavailable</strong>
        </div>
        <p className="skorpio-map-fallback-body">
          The interactive map needs a configured Mapbox token. Marker coordinates
          are listed below so the data is still inspectable.
        </p>
        {markers.length > 0 && (
          <ul>
            {markers.slice(0, 6).map((m) => (
              <li key={m.id}>
                {m.popup?.title ?? m.id} · {m.lat.toFixed(3)}, {m.lon.toFixed(3)}
              </li>
            ))}
            {markers.length > 6 && <li>… and {markers.length - 6} more</li>}
          </ul>
        )}
      </div>
    )
  }

  return (
    <div>
      <div ref={containerRef} className="skorpio-map" style={{ height }} />
      {legend && legend.length > 0 && (
        <div className="skorpio-map-legend">
          {legend.map((l) => (
            <span className="skorpio-map-legend-item" key={l.label}>
              <span className="skorpio-map-legend-dot" style={{ background: l.color }} />
              {l.label}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
