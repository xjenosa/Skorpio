import { useMemo } from 'react'
import type { SitingPlan } from '../../api/types'
import { MapView, type MapLineSpec, type MapMarkerSpec } from '../MapView'

// Stage 3 — Site Generation. Mapbox basemap with the agent's actual
// candidate city dots and a k-nearest "transmission mesh" overlaid on top.

const ACCENT_HOT = '#f38764'
const ACCENT_COLD = '#faf9f5'

// Hash-based "hot" classifier — gives a stable mix of accent / neutral dots
// across mounts so the map has visual rhythm without needing extra fields.
function intensity(label: string): number {
  let h = 0
  for (const ch of label) h = (h * 31 + ch.charCodeAt(0)) % 1000
  return (h % 1000) / 1000
}

// k-nearest mesh in lat/lon space. Euclidean over (lat, lon) is fine for the
// "connect each dot to its 3 closest neighbours" topology we want here.
function buildLinkMesh(pts: Array<{ lat: number; lon: number }>, k = 3) {
  const out: Array<{ a: number; b: number }> = []
  const seen = new Set<string>()
  for (let i = 0; i < pts.length; i++) {
    const dists: Array<[number, number]> = []
    for (let j = 0; j < pts.length; j++) {
      if (i === j) continue
      const dLat = pts[i].lat - pts[j].lat
      const dLon = pts[i].lon - pts[j].lon
      dists.push([j, dLat * dLat + dLon * dLon])
    }
    dists.sort((p, q) => p[1] - q[1])
    for (let n = 0; n < k && n < dists.length; n++) {
      const j = dists[n][0]
      const key = i < j ? `${i}-${j}` : `${j}-${i}`
      if (!seen.has(key)) {
        seen.add(key)
        out.push({ a: i, b: j })
      }
    }
  }
  return out
}

export interface GenerationMapProps {
  plan: SitingPlan | null
}

export function GenerationMap({ plan }: GenerationMapProps) {
  const dots = useMemo(() => {
    if (!plan?.top_candidates?.length) return []
    return plan.top_candidates.map((c) => ({
      id: c.site.site_id,
      lat: c.site.latitude,
      lon: c.site.longitude,
      label: c.site.name,
      region: c.region_iso,
      rank: c.rank,
    }))
  }, [plan])

  const markers = useMemo<MapMarkerSpec[]>(
    () =>
      dots.map((d) => {
        const hot = intensity(d.label) > 0.55
        return {
          id: d.id,
          lat: d.lat,
          lon: d.lon,
          color: hot ? ACCENT_HOT : ACCENT_COLD,
          size: hot ? 'md' : 'sm',
          popup: {
            eyebrow: d.region,
            title: d.label,
            meta: d.rank != null ? `Rank #${d.rank}` : undefined,
          },
        }
      }),
    [dots],
  )

  const lines = useMemo<MapLineSpec[]>(() => {
    const mesh = buildLinkMesh(dots, 3)
    return mesh.map((l, i) => ({
      id: `gen-link-${i}`,
      coordinates: [
        [dots[l.a].lon, dots[l.a].lat],
        [dots[l.b].lon, dots[l.b].lat],
      ],
      color: ACCENT_HOT,
      width: 1,
      opacity: 0.35,
    }))
  }, [dots])

  if (dots.length === 0) {
    return (
      <div className="stage-viz-pending">
        <span className="t-eyebrow">No data</span>
        <p>Candidate sites will appear after the run finishes.</p>
      </div>
    )
  }

  return (
    <div className="viz-map">
      <MapView markers={markers} lines={lines} height={340} />
      <div className="viz-map-foot">
        <span className="t-mono">{dots.length} candidate sites</span>
      </div>
    </div>
  )
}
