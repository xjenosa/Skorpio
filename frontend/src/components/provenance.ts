// Per-pipeline data-provenance descriptors. The chips rendered in the
// report's "Data provenance" block (REPORTS_COHESION.md §7b) read off this
// helper. Each chip says "this stage of the pipeline ran on <status>
// data", colored by the four-tier scale defined in ProvenanceChips.tsx.
//
// Sources flow: the helper takes the pipeline id (always known by the
// shell) plus the existing `plan.sources` citation list, and toggles
// optional chips based on whether the matching citation actually fired
// this run. That way "Demographics: live" only shows when ArcGIS
// GeoEnrichment actually answered, and falls back to the frozen Census
// baseline otherwise. The non-conditional chips (Summary, Modeled stages)
// are always present because they reflect a fixed property of the
// pipeline's design, not a runtime overlay.

import type { PipelineId } from '../pipelines'

export type ProvenanceStatus = 'live' | 'frozen' | 'modeled' | 'llm'

export interface ProvenanceChip {
  /** Short stage label rendered inside the pill. Keep to 1-3 words. */
  stage: string
  status: ProvenanceStatus
  /** Optional tooltip text. Names the underlying source / method. */
  hint?: string
}

function hasSource(sources: string[], needle: string): boolean {
  const n = needle.toLowerCase()
  return sources.some((s) => s.toLowerCase().includes(n))
}

const SUMMARY_HINT = 'Claude prose, reconciled to computed numbers'

export function provenanceFor(
  pipelineId: PipelineId,
  sources: string[] | null | undefined,
): ProvenanceChip[] {
  const src = sources ?? []

  switch (pipelineId) {
    case 'datacenter-siting': {
      const chips: ProvenanceChip[] = [
        {
          stage: 'Grid telemetry',
          status: 'live',
          hint: 'IESO, AESO, Hydro Quebec carbon + LMP feeds',
        },
        {
          stage: 'POI anchors',
          status: 'frozen',
          hint: 'OpenStreetMap substation snapshot',
        },
      ]
      if (hasSource(src, 'arxiv')) {
        chips.push({
          stage: 'arXiv research',
          status: 'live',
          hint: 'Live arXiv preprint search',
        })
      }
      if (hasSource(src, 'arcgis geoenrichment')) {
        chips.push({
          stage: 'City demographics',
          status: 'live',
          hint: 'ArcGIS GeoEnrichment (Esri Canada)',
        })
      }
      chips.push(
        {
          stage: 'Site picks',
          status: 'llm',
          hint: 'Claude generates candidates anchored on real POIs',
        },
        { stage: 'Summary', status: 'llm', hint: SUMMARY_HINT },
      )
      return chips
    }

    case 'datacenter-expansion': {
      const chips: ProvenanceChip[] = [
        {
          stage: 'Operator footprint',
          status: 'frozen',
          hint: 'Public datacenter operator catalog (DC Byte, press releases)',
        },
        {
          stage: 'Provincial carbon',
          status: 'live',
          hint: 'Live ISO fuel-mix feeds + IPCC AR5 factors',
        },
      ]
      if (hasSource(src, 'arcgis geoenrichment')) {
        chips.push({
          stage: 'City demographics',
          status: 'live',
          hint: 'ArcGIS GeoEnrichment (Esri Canada)',
        })
      }
      chips.push(
        {
          stage: 'Demand forecast',
          status: 'modeled',
          hint: 'Workload-class CAGR heuristic',
        },
        { stage: 'Summary', status: 'llm', hint: SUMMARY_HINT },
      )
      return chips
    }

    case 'winter-peak-stress': {
      const chips: ProvenanceChip[] = [
        // Substation locations come from OSM tags via the
        // _substations_generated catalog. Only the feeder connections
        // between them are synthesized — the substation list itself
        // is real.
        {
          stage: 'Substation locations',
          status: 'frozen',
          hint: 'OpenStreetMap power=substation tags',
        },
        {
          stage: 'Feeder topology',
          status: 'modeled',
          hint: 'Synthesized connections between real substations (Canadian distributor GIS is not public)',
        },
        // OEB Yearbook 2021 customer + peak-load numbers for Ontario
        // utilities, AESO AIL P95 for Edmonton, StatsCan provincial
        // sanity-check for the rest. Always applied.
        {
          stage: 'Utility load baseline',
          status: 'frozen',
          hint: 'OEB Yearbook 2021 (ON) + AESO AIL P95 (AB) + StatsCan Table 25-10-0021 provincial check',
        },
      ]
      // Live ArcGIS city household total used to rescale per-feeder
      // customer counts. Fires only when ARCGIS_CLIENT_ID is set.
      if (hasSource(src, 'arcgis geoenrichment')) {
        chips.push({
          stage: 'City demographics',
          status: 'live',
          hint: 'ArcGIS GeoEnrichment (Esri Canada): rescales feeder customer totals to real Census Subdivision households',
        })
      }
      // Live provincial grid baseline from canada_grid.get_provincial_snapshot
      // (IESO realtime, AESO CSD, Hydro-Quebec demand JSON + IPCC factors).
      if (hasSource(src, 'provincial snapshot')) {
        chips.push({
          stage: 'Provincial grid baseline',
          status: 'live',
          hint: 'IESO / AESO / Hydro-Quebec realtime totals + IPCC AR5 factors',
        })
      }
      chips.push(
        {
          stage: 'Cold event archive',
          status: 'frozen',
          hint: 'ECCC historical hourly observations, 7 stations x 6 winter months',
        },
        {
          stage: 'Scenario application',
          status: 'modeled',
          hint: 'Picks an observed cold snap from the archive (or a user scenario) and applies it to the feeder model',
        },
        {
          stage: 'Load simulation',
          status: 'modeled',
          hint: 'Deterministic hourly load math against the selected scenario',
        },
        {
          stage: 'Risk rationale',
          status: 'llm',
          hint: 'Per-feeder Claude prose, reconciled to capacity math',
        },
        { stage: 'Summary', status: 'llm', hint: SUMMARY_HINT },
      )
      return chips
    }

    case 'electrification-readiness': {
      const chips: ProvenanceChip[] = []
      const arcgisDemo = hasSource(src, 'arcgis geoenrichment')
      // Geocoding shows when the FSA registry returned live coords. ArcGIS
      // World Geocoding is the primary path; zippopotam is the fallback.
      chips.push({
        stage: 'Geocoding',
        status: 'live',
        hint: arcgisDemo
          ? 'ArcGIS World Geocoding (Esri)'
          : 'Live postal-code geocoding (ArcGIS primary, zippopotam fallback)',
      })
      chips.push(
        arcgisDemo
          ? {
              stage: 'Demographics',
              status: 'live',
              hint: 'ArcGIS GeoEnrichment (Esri Canada): households, income, dwelling mix',
            }
          : {
              stage: 'Demographics',
              status: 'frozen',
              hint: 'StatsCan Census 2021 FSA registry',
            },
        {
          stage: 'Vehicle stock',
          status: 'frozen',
          hint: 'StatsCan Table 23-10-0308 + Ontario MTO vehicle registrations',
        },
        {
          stage: 'Heating mix',
          status: 'frozen',
          hint: 'StatsCan SHEU 2019 (Survey of Household Energy Use)',
        },
        {
          stage: 'Climate normals',
          status: 'frozen',
          hint: 'ECCC Climate Normals 1981-2010, nearest station',
        },
        {
          stage: 'Adoption model',
          status: 'modeled',
          hint: 'Parametric load curves per FSA x scenario, calibrated to the baselines above',
        },
        {
          stage: 'Readiness scoring',
          status: 'modeled',
          hint: 'Deterministic grid math + CSA C22.1 policy constants',
        },
        { stage: 'Summary', status: 'llm', hint: SUMMARY_HINT },
      )
      return chips
    }

    case 'grid-investment-optimizer': {
      const chips: ProvenanceChip[] = [
        // Per-asset metadata (asset class, capacity, voltage, age,
        // historical issues) calibrated from utility public filings.
        {
          stage: 'Asset catalog',
          status: 'frozen',
          hint: 'Utility filings (OEB rate cases, AESO long-term outlook, Hydro-Quebec strategic plan)',
        },
        // Per-asset latitude / longitude pulled from real OSM tags
        // (utility_assets._real_substations + _real_transmission_lines).
        // Drives the climate-hazard point queries against ArcGIS.
        {
          stage: 'Asset locations',
          status: 'frozen',
          hint: 'OpenStreetMap substation + transmission line tags (operator-matched)',
        },
        // Customer-count + peak-load anchor per utility, sourced from
        // the OEB Yearbook for Ontario utilities and used downstream
        // by the ROI optimizer to weight customers-protected per dollar.
        {
          stage: 'Utility load baseline',
          status: 'frozen',
          hint: 'OEB Yearbook 2021 customer counts and peak load per utility',
        },
      ]
      const haveHazards =
        hasSource(src, 'nrcan') || hasSource(src, 'cwfis') || hasSource(src, 'living atlas')
      chips.push(
        haveHazards
          ? {
              stage: 'Climate hazards',
              status: 'live',
              hint: 'NRCan Historical Flood + CWFIS Wildfire via Esri Living Atlas',
            }
          : {
              stage: 'Climate hazards',
              status: 'modeled',
              hint: 'Province-average heuristic (Esri Living Atlas overlay unavailable for this run)',
            },
      )
      if (hasSource(src, 'arcgis geoenrichment')) {
        chips.push({
          stage: 'City demographics',
          status: 'live',
          hint: 'ArcGIS GeoEnrichment (Esri Canada)',
        })
      }
      chips.push(
        {
          stage: 'Portfolio',
          status: 'modeled',
          hint: 'Deterministic knapsack / ROI optimization',
        },
        { stage: 'Summary', status: 'llm', hint: SUMMARY_HINT },
      )
      return chips
    }
  }
}
