import { useMemo } from 'react'
import type { SitingPlan } from '../../api/types'
import { MapView, type MapMarkerSpec } from '../MapView'

// Stage 3 — Site Generation. Mapbox basemap with the agent's actual
// candidate city dots. The earlier "k-nearest transmission mesh"
// overlay was removed because the lines were synthesized (nearest-
// neighbour geometry between dots, not real transmission corridors)
// and were being mistaken for live OSM transmission data.

const ACCENT_HOT = '#f38764'
const ACCENT_COLD = '#faf9f5'

// Hash-based "hot" classifier — gives a stable mix of accent / neutral dots
// across mounts so the map has visual rhythm without needing extra fields.
function intensity(label: string): number {
  let h = 0
  for (const ch of label) h = (h * 31 + ch.charCodeAt(0)) % 1000
  return (h % 1000) / 1000
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
      <MapView markers={markers} height={340} />
      <div className="viz-map-foot">
        <span className="t-mono">{dots.length} candidate sites</span>
      </div>
    </div>
  )
}
