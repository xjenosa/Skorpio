# Skorpio Reports — Cohesion Spec

> **What this is:** the canonical naming, structure, and visual vocabulary
> shared by all 5 pipeline reports (Siting, Expansion, Winter Stress,
> Electrification, Investment). Same chrome everywhere; only the data and
> labels change per pipeline.
>
> **When to reference this:** when adding a new pipeline, refactoring a report,
> or asking Claude to make changes that should apply consistently across
> pipelines, point at this file (e.g. *"follow REPORTS_COHESION.md"*).

---

## 0. Data provenance — never fabricate (priority rule)

> **Rule:** No number in any report should be Claude inventing it. Every
> quantitative claim must come from one of:
>
> 1. A real public dataset ingested via `backend/scripts/ingest_*.py` and
>    emitted as a `backend/services/_*_generated.py` module.
> 2. A hand-curated catalog that explicitly cites its source in the file
>    header (e.g. utility annual reports, OEB rate filings).
> 3. A computed result derived from the above.
>
> When none of those is available, the number must be **labeled as an
> estimate in code comments** and the limitation must surface in the
> report's `limitations[]` array. Claude must never be asked to
> "estimate" or "fill in a plausible value" for a quantitative field —
> that is fabrication regardless of how confident the prose sounds.

### What to do when you need a number you don't have

In priority order:

1. **Find a free public CSV / Excel / XML / API.** Government open-data
   portals are first-line: StatsCan (CSVs at `www150.statcan.gc.ca/n1/tbl/csv/`),
   NRCan OEE, ECCC Climate Data Mart, OEB Yearbook XLSX, IESO public
   reports, OpenStreetMap Overpass, NREL AFDC. If you find one,
   wrap it in a `backend/scripts/ingest_*.py` script following the
   pattern in `ingest_vehicle_registrations.py`.
2. **If only a paywalled report exists, don't fake it.** Leave the
   existing rule-of-thumb estimate in code, mark it explicitly as
   "industry rule-of-thumb" or similar in the comment header, surface it
   in `limitations[]`, and stop. Fabricating a "transcription" from the
   paid report (or worse, citing it as if you ingested it) is worse than
   the honest estimate.
3. **Never prompt Claude with "estimate X based on your training data."**
   That is fabrication dressed up as research.
4. **When passing context to Claude for narrative or selection,
   always include the real catalog in the prompt** so the model is
   grounding on observed data, not its prior. See
   [`agents/site_generation.py::_real_substation_anchors`](../../../backend/agents/site_generation.py)
   for the pattern — real OSM substation list injected into the
   site-design prompt as anchors.

### Current data-provenance audit (snapshot)

| Pipeline | Stage 02 (substrate) | Stage 03 (modeling) | Synthesis text |
|---|---|---|---|
| **Siting** | ✅ Ontario LDC territory routing now uses real **OEB Distributor Service Territories** polygons (`backend/scripts/ingest_oeb_territories.py` → `_oeb_territories_generated.py`) — point-in-polygon check replaces the previous 40 km substation-radius proxy. ⚠️ Mixed elsewhere: ~50 hand-typed seed sites per ISO; Claude fallback anchored on real OSM substations per region; non-Ontario utilities fall back to substation-proximity routing | ⚠️ Real scoring algorithm; per-site economics (PUE, fiber, water, deploy time) still randomly jittered around plausible ranges. Jitter is **deterministic per region** via `zlib.crc32` seeding (§8c) | Claude prose, grounded in real numbers from earlier stages |
| **Winter Stress** | ✅ Ontario: real OEB Yearbook 2021 customer counts + winter peak per utility. ⚠️ Non-Ontario cities: hand-curated peak MW (StatsCan only publishes province-level); sanity-checked against StatsCan provincial totals | ⚠️ Real algorithm; physics constants (design heat 8 kW/home, EV draw 7.2 kW, 24-hour shape) are rule-of-thumb with sourcing comments to NRCan SHEU / IESO ResLoad. Scenario HP/EV adoption % is now horizon-parameterized via [`adoption_curves.py`](../../../backend/services/adoption_curves.py) — anchors cite CER 2023 Energy Future + IEA NZ Roadmap 2023, linearly interpolated to `spec.horizon_year` | Claude prose |
| **Electrification** | ✅ Real: 1,638-FSA StatsCan Census 2021 (households, income, dwelling mix); 637 ECCC HDD stations (nearest-station lookup); NRCan SHEU 2019 heating mix (province overlay); NREL AFDC EV chargers per FSA | ✅ Real per-province EV baseline (StatsCan 23-10-0308). ⚠️ 24-hour winter temperature + load shapes still hand-typed | Claude prose |
| **Investment** | ⚠️ Hand-curated assets for 5 named utilities cite public filings (Hydro One / Toronto Hydro / Alectra / EPCOR / Hydro-Québec). Unknown utilities now anchor synthesized substation to a real OSM coordinate when one exists for that operator | ✅ Real ECCC climate hazard base rates + IBC/CatIQ insurance loss share. ⚠️ Per-asset-type susceptibility multipliers are hand-typed | Claude prose |
| **Expansion** | ⚠️ Hand-curated catalog of 5 Canadian DC operators (eStruxture / Cologix / Hyperion / Q-Scale / Equinix) calibrated to public disclosures | ❌ Growth CAGRs (12 / 25 / 40 / 22 %) and capex/MW (\$9.5–13.5M) are industry rule-of-thumb estimates — paid JLL / CBRE / Synergy reports are not ingestible. Sourcing comments updated to flag this explicitly | Claude prose |

Legend: ✅ real ingested public data · ⚠️ hand-curated but cited ·
❌ synthetic / estimate (must be labeled in code + surfaced in `limitations[]`)

### ArcGIS / Esri live overlays (sponsor integration)

On top of the substrate above, four pipelines now apply **live ArcGIS REST overlays at run time** via the OAuth 2.0 `client_credentials` flow in
[`backend/services/arcgis_enrichment.py`](../../../backend/services/arcgis_enrichment.py)
and [`backend/services/arcgis_hazards.py`](../../../backend/services/arcgis_hazards.py).
When the overlay fires, the underlying field flips from frozen-snapshot
to live and `is_synthesized` is set to `False` on the affected model.
Citations land in `plan.sources`; the §7b provenance chips render the
same fact visually in the report footer.

| Pipeline | Esri overlay | Endpoint | Effect when it fires |
|---|---|---|---|
| **Siting** | GeoEnrichment (CAN.CSD) | `enrich_city(spec.city)` | Appends real Census Subdivision households + population to `plan.sources` |
| **Expansion** | GeoEnrichment (CAN.CSD) | `enrich_city(spec.city)` | Appends real CSD household count to `footprint.sources` |
| **Electrification** | World Geocoding + GeoEnrichment (CAN.FSA) | `geocode_fsa()` + `enrich_fsa()` | Primary FSA-to-coords path (zippopotam fallback); overlays live households, median income, dwelling mix on top of the 2021 Census base and flips `NeighborhoodProfile.is_synthesized=False` |
| **Investment** | GeoEnrichment (CAN.CSD) + Living Atlas | `enrich_city()` + `historical_flood_count()` + `historical_wildfire_count()` | Real Census household count for utility primary city; empirical 100-year flood probability (NRCan Historical Flood Events) and 55-year wildfire probability (CWFIS National Fire Database) replace the province-average heuristic per asset when lat/lon is known |

**Winter Peak** is the lone holdout: utility feeder-level GIS is not
publicly available in Canada, so there is no live Esri overlay that
maps onto its substrate. Its provenance chips render as `modeled` for
the topology + simulation stages by design, not as a gap to apologize
for.

**Cost protection:** per-process call cap (`MAX_LIVE_CALLS = 25` per
backend restart) + disk caches (`arcgis_enrich` 30 d, `arcgis_geocode`
1 yr, `arcgis_hazards` 1 h) keep a typical run under single-digit
Esri credits. Repeat runs for the same geography cost zero.

**Reviewer rule:** a new live external data source ingested in any
pipeline must (a) append a short citation to the relevant model's
`sources: list[str]` field, (b) flip the relevant `is_synthesized`
flag to `False` when the overlay materially replaces a baked field,
and (c) get a chip entry in
[`provenance.ts`](./provenance.ts) so §7b reflects it.

### Practical implications

- **Adding a new pipeline?** Identify a free public data source first.
  If none exists, build the pipeline with the synthetic substrate but
  label it `❌` in the table above and add a `limitations[]` entry on
  every report it produces.
- **Reviewing a PR?** A hardcoded quantitative constant introduced
  without a sourcing comment is a NACK. The fix is either a real
  ingestion script or an explicit "rule-of-thumb estimate" header.
- **User asks to "improve accuracy"?** Real ingestion
  (`backend/scripts/ingest_*.py`) beats tuning estimates. If a real
  source exists and isn't being used, that's the work.
- **Claude returns a quantitative field in JSON?** That field must
  either (a) come from a real catalog passed into the prompt as context,
  or (b) be flagged downstream as `generation_method="claude_design"` or
  equivalent so the report can disclose the synthesis.

---

## 1. Shared structure — `<ReportShell>` owns the chrome

Every pipeline-specific report file (`FinalReport.tsx`, `WinterPeakReport.tsx`,
`ElectrificationReport.tsx`, `InvestmentReport.tsx`, `ExpansionReport.tsx`) is a
thin wrapper around [`ReportShell`](./ReportShell.tsx). It owns:

- **Page head** — `<h1>Final report</h1>` + Print button
- **Panel chrome** — `.panel-pipeline` border, padding, background
- **Header strip** — 3 header stats on the left, agent runtime on the right
- **Winners row** — 3 winner cards (`<ReportWinner>[]`)
- **Sections row** — 3 expandable section cards (`<ReportSection>[]`, ids `01`/`02`/`03`)
- **Executive summary** — markdown block at the bottom
- **Sticky chatbar** — `<ReportChatBar>` pinned to viewport bottom

The pipeline-specific wrapper supplies all data via props; it never renders
chrome of its own.

---

## 2. Stage labels — `pipelineConfigs.ts`

Every pipeline's 5 stages map to the same 5-step rhythm:

| # | Canonical label | Role |
|---|---|---|
| 01 | **Workload Intelligence** | Parse the prompt into a structured spec (region, scope, target, horizon, etc.) and pull initial context |
| 02 | **[Domain] Intelligence / [Domain] Profile / Catalog / Footprint** | Load the per-pipeline substrate (grid, neighborhoods, assets, operator sites) |
| 03 | **[Modeling / Forecast / Simulation]** | Project what happens under the scenario (cold event, adoption curve, climate risk, demand) |
| 04 | **[Scoring / Optimization]** | Rank or select with the pipeline-specific scorer |
| 05 | **Plan Synthesis** | Roll up into the final report blob — exec summary, methodology, safety flags |

Per-pipeline instantiation:

| Pipeline | 01 | 02 | 03 | 04 | 05 |
|---|---|---|---|---|---|
| **Siting** | Workload Intelligence | Grid Intelligence | Site Generation | Site Scoring | Plan Synthesis |
| **Winter Stress** | Workload Intelligence | Grid Intelligence | Cold-Event Simulation | Risk Scoring | Plan Synthesis |
| **Electrification** | Workload Intelligence | Neighborhood Profile | Adoption Modeling | Readiness Scoring | Plan Synthesis |
| **Investment** | Workload Intelligence | Asset Catalog | Climate Risk Modeling | Portfolio Optimization | Plan Synthesis |
| **Expansion** | Workload Intelligence | Operator Footprint | Demand Forecast | Expansion Scoring | Plan Synthesis |

**Format:** `"01 · Workload Intelligence"` (number, middle-dot separator, then title-case label).
Descriptions are one sentence, parallel phrasing across pipelines.

---

## 3. Winner cards — always 3, two patterns

Every report renders **exactly 3 winner cards**. There are two acceptable
patterns depending on the pipeline's shape:

### Pattern A — Verdict-first (pass/fail or status pipelines)

For pipelines that produce a single overall assessment (the grid held / it
didn't, the budget covered it / it didn't), card 1 is a colored verdict pill:

1. **Verdict** — colored, all-caps, drawn from `VERDICT_COLOR`
   (good/warning/critical/neutral). Eyebrow is `"Verdict"`; value is the
   pipeline-specific verdict word.
2. **Headline metric** — the most operator-relevant single number/name
3. **Supporting metric** — a complementary single number/name

| Pipeline | Good | Warning | Critical |
|---|---|---|---|
| **Winter Stress** | PASS | MARGINAL | FAIL |
| **Electrification** | READY | CONSTRAINED | BLOCKED |
| **Investment** | FUNDED | — | UNDER-FUNDED |
| **Expansion** | ON-TARGET | SHORTFALL | UNDER-PLANNED |

### Pattern B — Info-trio (option / recommendation pipelines)

For pipelines that surface multiple equally-valid options (Siting recommends
the *best* site on each of several axes — there's no single pass/fail), all
three cards are parallel info cards highlighting the leader on each axis.

Card vocabulary should use parallel `[Best / Lowest / Fastest / Most] [thing]`
labels so the trio reads as a single comparison.

| Pipeline | Card 1 eyebrow | Card 2 eyebrow | Card 3 eyebrow |
|---|---|---|---|
| **Siting** | Best site overall | Lowest cost | Fastest deployment |

### Choosing a pattern

- **Pipeline produces a verdict** the operator hands to a stakeholder? → A
- **Pipeline surfaces a shortlist** the operator picks from? → B

The color for Pattern A comes from `VERDICT_COLOR` in
[`reportStyle.ts`](./reportStyle.ts). Use the `verdictColor()` helper when the
verdict string already matches a known vocabulary; otherwise compute the color
from the verdict logic and pass it via the `color` prop on `<ReportWinner>`.
Pattern B cards leave `color` undefined and use the default surface treatment.

---

## 4. Section bodies — 01 chart, 02 map, 03 methodology

The 01/02/03 sections follow a fixed signature pattern so every report's
expandable rows feel like siblings:

| Section | Pattern | Examples |
|---|---|---|
| **01** | Headline chart of the most important ranked output | LCOE bar (Siting), load curves (Winter), incremental MW (Electrification), capex vs avoided (Investment), supply vs demand (Expansion) |
| **02** | Signature **map** — geographic answer to "where?" | Candidates on Canada basemap, substation risk map, FSA readiness map, at-risk asset map, operator footprint map |
| **03** | Mini chart + methodology / mitigations / caveats | Pareto-axis averages, scenario severity bars, scenario severity, hazard donut, capacity-mix donut |

Every section body is wrapped in [`<VizPanel>`](./VizPanel.tsx), which provides
the 4-slot template: `caption` / `children` / `details` / `note`.

---

## 5. Visual vocabulary — `reportStyle.ts`

Colors and chart constants live in [`reportStyle.ts`](./reportStyle.ts) so
palette changes flow through both the live stage panels and the final reports.

- `VERDICT_COLOR` — `good` / `warning` / `critical` / `neutral`
- `CATEGORICAL_COLORS` — palette index 0 (Skorpio orange) through 4
- `CHART_AXIS`, `CHART_GRID_STROKE`, `CHART_TOOLTIP_STYLE` — Recharts defaults
- `CHART_TOOLTIP_ITEM_STYLE` + `CHART_TOOLTIP_LABEL_STYLE` — **must be passed alongside `CHART_TOOLTIP_STYLE` on every `<Tooltip>`**. Recharts colors the metric rows and the heading line through separate `itemStyle` / `labelStyle` props; without them those lines render in default black on the dark panel and are unreadable.
- `CHART_TOOLTIP_ITEM_STYLE_LEGEND` — use this **instead of** `CHART_TOOLTIP_ITEM_STYLE` on charts that render a multi-series `<Legend>` (e.g. Heat pump / EV / Years bars, Capex / Avoided bars, stacked area charts, multi-slice pies). The empty object lets Recharts fall back to each series's own stroke/fill color per row, so each tooltip row matches the legend chip and the bar it describes. Decision rule:
  - **Single series** (one `<Bar>` / one `<Line>` / one `<Area>`, even if individual cells are colored differently) → `CHART_TOOLTIP_ITEM_STYLE` (cream rows). Coloring one tooltip row with the series color when there's only one row reads as noise.
  - **Multiple series with a legend** → `CHART_TOOLTIP_ITEM_STYLE_LEGEND` (series-colored rows). The label heading stays cream via `CHART_TOOLTIP_LABEL_STYLE` either way.
- `CHART_HEIGHT` — `hero` / `detail` / `mini`
- `MAP_HEIGHT` — `standard` / `dense`
- `MARKER_SIZE` — `sm` / `md` / `lg`
- `verdictColor(verdictString)` — verdict → hex helper

Stage viz files (`stageviz/*.tsx`) import the same constants so the live
pipeline panels and the final report read as one visual family.

### Map marker interaction rule

If a `MapMarkerSpec` is rendered **without a `popup`**, [`MapView`](./MapView.tsx)
automatically swaps its cursor from `pointer` to `grab` — matching the Mapbox
canvas cursor underneath. This keeps the cursor honest: a marker that does
nothing on hover/click should feel like part of the map, not like UI. `grab`
specifically (not `default`) signals "you can drag the map here," which is
the truthful behavior for a decorative or anchor marker.

When to render popup-less markers:
- An anchor / background marker that visually grounds a related interactive
  marker stacked on top of it. Example: Expansion's "existing site" diamonds
  carry no popup because the funded brownfield circle sits exactly on top
  (offset=0) and owns the click — see [`ExpansionReport.tsx`](./ExpansionReport.tsx)
  Section 02. Fold the diamond's useful baseline data ("today X MW · PUE Y")
  into the overlaying circle's `meta` so no information is lost.
- Pure-decoration markers (rare in our reports — prefer no marker at all).

The legend should still describe the popup-less marker (e.g. `"EXISTING (anchor)"`)
so the reader can decode the symbol even though it isn't interactive.

### Map camera default — always `initialView='auto'`

Every report's section-02 map must let `<MapView>` fit the camera to the
actual marker extent. That's `initialView='auto'` — and since `'auto'` is
the default, **just omit the prop**. When markers cluster in southern
Ontario, the map shows southern Ontario; when they span provinces, the
map naturally zooms out to fit them all. Same chrome, different framing —
per §1.

**Never hardcode a preset** like `initialView='canada'` or `'gta'`. Two
ways this has bitten us:

- **Siting** originally used `initialView='canada'`, so every
  Ontario-only run rendered the markers as a tight knot in southern
  Ontario surrounded by empty arctic and ocean.
- **Electrification** originally used a dynamic predicate
  (`inGta ? 'gta' : 'auto'`), which seemed defensible but produced a
  too-wide GTA frame for single-FSA queries where `'auto'` would have
  given a tight one-pin frame. The dynamic-preset escape hatch turned out
  to never beat `'auto'` in practice — Mapbox's `fitBounds` already does
  the right thing for one pin, for a cluster, and for a national spread.
  Dynamic logic was just dead weight + an extra failure surface.

**Reviewer rule:** any `initialView` prop on `<MapView>` inside a report
component is a NACK — delete it and let the default `'auto'` handle
framing. The prop exists on `MapView` only for the live `stageviz/*`
panels, which sometimes want a fixed national overview for "we're
searching nationwide" framing during pipeline execution.

---

### Empty-state rule

Every report renders **all 3 winner cards unconditionally** — never zero, never
one, never two. When the underlying value is missing (a pipeline run that
produced no candidates / scenarios / projects), substitute `'—'` (em-dash) for
the `value` and a short explanatory string for the `sub`:

```tsx
{
  eyebrow: 'Best site overall',
  value: winner?.site.name ?? '—',
  sub: winner ? `${...}` : 'No candidates returned by this run',
}
```

The 3-card row is the report's visual signature — a missing-data run should
still render the row so the reader sees *why* (em-dashes + explanatory sub)
instead of looking at a confusing blank space.

The same rule applies to Pattern A: render the verdict card with the
neutral/critical color and an explanatory sub when the plan has no data
(e.g. `summary_verdict ?? 'UNKNOWN'`).

---

## 6. Executive summary — markdown with paragraph breaks

Every plan's `executive_summary` field is rendered through
[`renderMarkdown`](./reportMarkdown.tsx) by the shell, so the source string
should be **proper markdown with paragraph breaks (`\n\n`)**, not a single wall
of prose.

**Use Siting as the reference.** Its synthesis agent prompts Claude for a
"compelling 4-5 paragraph executive summary" and the result reads as 3-5 short
paragraphs that an exec can skim. Every other pipeline's synthesis agent should
follow the same prompt convention:

> *"Write a 4-5 paragraph executive summary. Paragraph 1: the headline finding
> (verdict + one-sentence why). Paragraph 2: the most important supporting
> evidence. Paragraph 3: caveats and limitations. Paragraph 4: recommended next
> action. Use blank lines between paragraphs."*

The frontend doesn't transform line breaks — what the agent returns is what
renders. If a report's exec summary looks like one long blob, fix the prompt
in the backend synthesis agent, not the frontend.

---

## 7. Sources — cite external data under the executive summary

Every report should render a **Sources** block directly below the exec summary,
styled identically to the `.fr-exec` block (same dark panel, same padding,
same eyebrow). The block sizes itself to however many sources the pipeline
used.

```tsx
<ReportShell
  ...
  execSummary={plan.executive_summary}
  sources={plan.sources}   // string[] — empty array = block hidden
/>
```

Each pipeline supplies its own `sources: string[]` — short citations like
*"IESO 2024 system status report"*, *"Cushman & Wakefield Q4 2024 datacenter
market overview"*, *"Statistics Canada 2021 census · FSA M5V"*. The shell
hides the block when the array is empty.

Sources signal trust: the operator can see which numbers came from real data
vs. modeled defaults. The block is required even when the pipeline used only
public/baked-in data — list those sources too.

---

## 7b. Data provenance chips — color-coded stage summary above Sources

Directly above the Sources block, the shell renders a **Data provenance**
row of chips (one per pipeline stage) plus a one-line legend decoding the
four colors. This is the operator's at-a-glance answer to "is any of this
real, or did the AI make it up?" — the textual citations in the Sources
block below are the long-form receipts.

```
DATA PROVENANCE
[● Geocoding] [● Demographics] [● Census base] [● Adoption] [● Summary]
● Live API  ·  ● Frozen snapshot  ·  ● Modeled  ·  ● LLM narrative
```

**The four statuses (matching the §0 traffic-light vocabulary):**

| Status | Color token | Meaning |
|---|---|---|
| **Live API** | `--energy-clean` | Live network call to upstream API on every run (ArcGIS, NRCan, IESO live carbon, arXiv) |
| **Frozen snapshot** | `--energy-mid` | Real data baked into the repo at a point in time (Census 2021, OEB Yearbook, OSM substations, ECCC Climate Normals) |
| **Modeled** | `--energy-dirty` | Calibrated heuristic, modeled topology, or hardcoded constants — no live source |
| **LLM narrative** | lavender (CATEGORICAL_COLORS[3]) | Claude prose, fact-reconciled against computed numbers before render. Off the severity axis on purpose — LLM is a category, not a quality verdict |

**Source of truth:** the per-pipeline chip set lives in
[`provenance.ts::provenanceFor()`](./provenance.ts). Each pipeline has a fixed
list of always-present chips (its 5 stages) plus optional chips that toggle
based on whether the corresponding citation appears in `plan.sources` —
e.g. the `City demographics: live` chip in Expansion only lights up when
"ArcGIS GeoEnrichment" actually answered this run. When the live overlay
doesn't fire, the chip either falls back to a frozen-snapshot chip
(Electrification's Demographics) or is omitted entirely (Expansion / Siting
city demographics).

**Where it renders:** inside the report panel, immediately above the Sources
block. Owned by `<ReportShell>`. Never anywhere else — not in the live
stage panel, not in the sidebar, not on the homepage. The chips are a
property of the *completed* report, not of an in-flight pipeline run.

**Reviewer rule:** chip-set drift across pipelines is a cohesion bug — fix
in `provenance.ts`, not in individual report wrappers. Adding a new chip
type (color) requires a token entry in `FinalReport.css` and a legend label
in `ProvenanceChips.tsx`; the four current statuses are the agreed
vocabulary and shouldn't be casually extended.

---

## 7c. Inline source citations — exec-summary highlights with hover detail

Where §7b chips summarize *the pipeline's stage-level provenance* in a
single row, **§7c chips operate inline within the executive summary
prose** — every quantitative number, named asset, named regulation, and
industry-pattern claim is wrapped in a colored highlight that opens a
source card on hover/click.

This is what gives a judge a defensible answer to the next-level question:
"yes the pipeline cites data — but for *this specific sentence*, what
source?"

### Marker syntax

Synthesis agents emit citations as inline markers in the
`executive_summary` string:

```
…delivers a lifetime return of [[s4|3.62 times invested capital]],
with avoided annual losses of [[s5|$2.8 million per year]].
```

Each `[[sN|cited text]]` references an id `sN` defined in a sibling
`citation_sources` dict on the same plan object:

```python
{
  "executive_summary": "...[[s4|3.62 times invested capital]]...",
  "citation_sources": {
    "s4": {
      "source_id": "s4",
      "label": "Lifetime ROI calculation (modeled)",
      "detail": "Sum of project NPVs / committed capital, 26y horizon, 5% discount",
      "status": "modeled"
    },
    ...
  }
}
```

The rendering layer ([`reportMarkdown.tsx`](./reportMarkdown.tsx)) parses
markers FIRST in its inline tokenizer, before bold/italic/code, so a `*`
inside cited text is safe. Unknown ids fall back to plain text — backward
compatible with pipelines that haven't been wired yet.

### Visual vocabulary — same 4 statuses as §7b

Colors mirror the chip palette exactly:

| Status | Color token | When to use |
|---|---|---|
| `live` | `--energy-clean` (green) | Cited value pulled from a live API on this run (ArcGIS GeoEnrichment, NREL utility-rates, IESO live carbon, arXiv) |
| `frozen` | `--energy-mid` (yellow) | Ingested dataset, hand-curated catalog, OR user-supplied scenario input |
| `modeled` | `--energy-dirty` (orange) | Computation over frozen/live sources by a pipeline stage |
| `llm` | lavender (`CATEGORICAL_COLORS[3]`) | General-knowledge claim Claude added on top of the data (industry patterns, regulatory framing, recommendations) |

Repeated mentions of the same fact reuse the same id (e.g. `$2.8M/yr`
appearing in Verdict and again in Limitations both reference `s5`). One
id, one popover card.

### Desktop interaction

- Hover over a highlight → portaled card appears above/below the anchor,
  styled as a peer of the Mapbox popup (same `--bg-1` / `--rule-2`
  tokens).
- Card shows: status eyebrow, label (one-line source title), optional
  detail (one-sentence "where the value came from"), and the matching
  provenance status badge from §7b.
- Click toggles persistently; click outside dismisses; focus opens (for
  keyboard users).

### Mobile interaction — highlights only, NO popover

Touch devices (`@media (pointer: coarse)`) render the highlights with
full color + dashed underline so the provenance signal still reads at a
glance, but tap does NOT open a card. Rationale: on a 390px viewport, a
popover blocks prose and forces a tap-outside dismissal before the user
can scroll past — strictly worse UX than leaving the source detail
unexposed. The Sources block below the exec summary already provides
long-form citations for the curious.

The detection lives in
[`reportMarkdown.tsx::CitationSpan`](./reportMarkdown.tsx); the touch
branch skips both the popover render and the click/hover handlers.

### Density target — applies uniformly across pipelines

**One marker per 250–350 characters of exec-summary prose.** No factual
paragraph (any quantitative claim, named asset, industry pattern, or
regulatory reference) should be uncited. Hand-curation in Phase 1 showed
that without this rule, descriptive pipelines (Siting, Winter, Expansion)
end up sparser than prescriptive ones (Investment, Electrification),
which judges read as inconsistent rigor.

After applying the target, expected per-pipeline density falls in a
3.0–5.5/k char window (varies with the report's natural prose length).

### Expected `llm`-status share by pipeline type

LLM share varies systematically and that's **expected**, not a bug:

| Pipeline | Output style | Expected `llm` share |
|---|---|---|
| Investment | Prescriptive (board recommendations) | 35–45% |
| Electrification | Prescriptive (council policy) | 35–45% |
| Siting | Descriptive (which site wins) | 20–30% |
| Expansion | Descriptive (target hit / miss) | 15–25% |
| Winter | Descriptive (do feeders survive) | 15–25% |

If a real run shows 0% `llm` on Investment, the prompt is letting
hallucinated industry-pattern claims slip through unmarked. If Siting
shows 40%+ `llm`, the prompt is fabricating reasoning instead of citing
measurements. Both are regressions.

### Guardrails for synthesis prompts (anti-fabrication)

The synthesis agent receives a **whitelist of allowed source labels**
(IESO, ECCC station IDs, OEB filings, NREL endpoints, StatsCan table
numbers, hand-curated catalog header strings). Citations must draw labels
from that list; free-form source names = automatic hallucination risk.

Specific tendencies the prompt must guard against, learned from Phase 1
audit of all 5 demo fixtures:

1. **Overstating which dataset a value came from.** Service-territory
   data ingested from OEB KMZ ≠ "Alectra Annual Report." Prompt must
   force the label to match the actual ingest source.
2. **Citing the regulator's name as a data source.** "OEB" without a
   quantitative claim attached is not a citation candidate.
3. **Mixing inputs with outputs.** A user-supplied $50M budget is
   `frozen` ("Scenario inputs"), not `modeled` ("knapsack output").
4. **Overstating a hand-curated catalog as a single filing.** Cite the
   catalog as `"Hand-curated catalog · {scope}"` with a detail naming the
   filings it calibrates against — never as a single filing name.
5. **Leaving industry-pattern claims unmarked.** "Vegetation contact is
   the leading cause of overhead outages" is `llm`, not unmarked prose.
   Unmarked + plausible = sleight of hand once the rest is cited.
6. **Synthesis copies internal field names into prose.** Parentheticals
   like `"(headroom_mw and peak_mw, scenario data)"` leak Python field
   names. The popover replaces this metadata; the inline parenthetical
   must go.
7. **Numerical sanity slips.** Past fixtures shipped `"$50000000 million"`
   (= 50 trillion), `"headroom = peak"` duplicates, and 67% × 30 ≠ 30
   parenthetical errors. The validation hook must catch:
   - Headroom ≥ 0
   - Headroom + peak ≈ baseline peak
   - Numbers repeated across the same exec summary must agree
   - Percentages must be consistent with the underlying numbers cited.

### Validation hook

Before returning a plan, the orchestrator runs a `_validate_citations`
pass that rejects (and retries) any synthesis output where:

- A `[[sN|...]]` marker has no matching `citation_sources[N]` entry, OR
- A `citation_sources` id is never referenced in `executive_summary` (an
  orphan source is a fabricated source the LLM never used), OR
- A `frozen` or `live` label is not in the backend's whitelist of real
  source names.

The error message includes the offending id and is appended to the prompt
on retry. One retry only; on second failure, fall back to the stub
exec_summary path.

**Reviewer rule:** if a synthesis prompt is changed in a way that drops
the citation marker contract, the validation hook will start rejecting
output and the stub fallback fires silently. Watch the `is_synthesized`
flag and the agent's retry log — both should remain green in CI fixtures.

---

## 8. Backend invariant — always render *something*

Every pipeline must guarantee its report always has data to plot, even when
upstream stages fail. The other 4 pipelines achieve this via a **persistent
domain layer** loaded in stage 02 from a baked-in catalog:

| Pipeline | Domain catalog (always loads) |
|---|---|
| Winter Stress | [`backend/grid/feeder_topology.py`](../../../backend/grid/feeder_topology.py) — known feeders per city |
| Electrification | [`backend/agents/neighborhood_profile.py`](../../../backend/agents/neighborhood_profile.py) — FSA defaults from StatsCan |
| Investment | [`backend/services/utility_assets.py`](../../../backend/services/utility_assets.py) — calibrated Hydro One / Toronto Hydro / EPCOR / Hydro-Québec asset catalog |
| Expansion | [`backend/services/operator_footprint.py`](../../../backend/services/operator_footprint.py) — eStruxture / Cologix / Hyperion / Q-Scale / Equinix sites |

Even when the scoring/optimization/synthesis stage produces nothing actionable,
the section-02 map still has the substations / FSAs / assets / sites to plot —
the report never goes blank.

**Siting** is candidate-centric (its output IS the candidates), so it has two
guarantees instead of one:

1. **Per-region seed catalog** — [`REGION_SEED_SITES`](../../../backend/grid/generator.py)
   covers every ISO and Canadian province the discovery agent can emit, so
   engine-based generation always finds seeds to expand.
2. **Last-resort fallback ring** — if every upstream path returns zero (no
   seeds, no POI, Claude failed, all filters rejected), the engine synthesizes
   a small ring of skeleton candidates around the region center marked
   `generation_method="fallback_ring"`. The synthesis stage flags this in
   `safety_flags` so the operator knows the candidates are illustrative.

**When adding a new pipeline:** wire up the equivalent of one of the patterns
above. The empty-state UI rule (§3 Empty-state) handles "no data at all", but
a pipeline that frequently hits that state has a backend bug, not a UI
problem. Fix it in the agent layer.

---

## 8b. Synthesis token budgets — don't cut blindly

Every pipeline's synthesis agent makes one Claude call that produces the JSON
the report renders from. The `max_tokens` cap on that call has to be large
enough for the **full** response. If Claude generates more than `max_tokens`,
the response is truncated mid-string, `json.loads` raises, and the agent falls
back to a stub (`"Narrative generation failed; see deterministic results
above."`). The fallback is fine as a safety net but it strips the executive
summary and the mitigations list, so reports look broken.

**Documented minimums** (verified against each pipeline's prompt shape):

| Pipeline | Synthesis agent | Min `max_tokens` | What fills the budget |
|---|---|---|---|
| Siting | [`plan_synthesis.py`](../../../backend/agents/plan_synthesis.py) | 1500 | 3-paragraph exec + top-5 recommendations |
| Winter Stress | [`winter_synthesis.py`](../../../backend/agents/winter_synthesis.py) | 3500 | 4–5 paragraph exec + 3–5 full mitigation objects with verbose rationale strings (observed: 2500 truncated mid-mitigation at ~2340 tokens) |
| Electrification | [`electrification_synthesis.py`](../../../backend/agents/electrification_synthesis.py) | 900 | 4–5 paragraph exec only |
| Investment | [`investment_synthesis.py`](../../../backend/agents/investment_synthesis.py) | 900 | 4–5 paragraph exec only |
| Expansion | [`expansion_synthesis.py`](../../../backend/agents/expansion_synthesis.py) | 900 | 4–5 paragraph exec only |

These are **minimum safe** values, not optimums. Below them risks truncation;
above them costs latency and tokens with no quality gain. Winter is the
outlier because its response shape includes the full mitigations array; the
others are exec-summary-only.

**Before lowering any of these:** inspect the prompt's JSON shape, estimate the
realistic response size, add ~20% safety margin, and test with the longest
plausible run (most regions / most scenarios) before committing. The first
symptom of an over-cut budget is `"Narrative generation failed"` in the
limitations block of a freshly-completed report.

### Non-synthesis JSON calls — same rule

Synthesis isn't the only place a truncated JSON breaks a pipeline. Any
`ask_claude_json` call has the same failure mode (truncation → `json.loads`
raises → fallback fires). Audited minimums for the other in-pipeline JSON
calls:

| Call | File | Min `max_tokens` | Response shape |
|---|---|---|---|
| Siting · Claude-designed sites | [`site_generation.py:103`](../../../backend/agents/site_generation.py) | 2500 | array of 12 site objects × 13 fields |
| Siting · per-site interactions | [`placement_scoring.py:291`](../../../backend/agents/placement_scoring.py) | 1024 | 3–5 interactions + 2-sentence explanation |
| Siting · region weights | [`plan_synthesis.py:283`](../../../backend/agents/plan_synthesis.py) | 512 | 6 floats + rationale |
| Siting · region insight | [`plan_synthesis.py:361`](../../../backend/agents/plan_synthesis.py) | 1024 | 3 short string fields |
| Grid · region list | [`grid_intelligence.py:241`](../../../backend/agents/grid_intelligence.py) | 2048 | array of 3–5 region objects |
| Winter · feeder rationales | [`feeder_risk.py:175`](../../../backend/agents/feeder_risk.py) | 2048 | `{ rationales: { feeder_id: sentence } }` for top-N |

`ask_claude` (text) calls don't have the same parse-failure mode — truncation
just gives a shorter string — but a 4–5 paragraph executive summary cut mid-
sentence still looks broken. The synthesis-text agents (Electrification /
Investment / Expansion at 900 tokens) sit at the tight end of the safe range;
if you ever see one of those exec summaries clipped, bump the cap.

---

## 8c. RNG determinism — `zlib.crc32`, not `hash()`

Any RNG that needs to be reproducible across runs must seed from a stable
key — and `hash()` is **not** a stable key.

Python 3.3+ randomizes the hash function for `str` / `bytes` per process
([PEP 456](https://peps.python.org/pep-0456/), defense against
hash-collision DoS). Every interpreter start picks a fresh salt, so
`hash("CA-ON")` returns a different integer in every container restart.
Code that writes `random.Random(hash(key) % 2**32)` *looks* deterministic
at the call site but produces different jitter per process — same prompt,
different result after `docker compose up --build`.

In Siting that meant the same workload could surface Kingston in one
container instance and a fallback skeleton ring in the next, depending on
which way the per-candidate capacity jitter fell. Bug class: silent,
test-flake, hard to reproduce because the symptom shifts with each rebuild.

**The rule:** when seeding a `random.Random` from a stable identifier
(`region.iso_code`, `site.name`, a file path, etc.), use `zlib.crc32`:

```python
import zlib
rng = random.Random(zlib.crc32(region.iso_code.encode()))
```

`zlib.crc32` is a built-in, deterministic across processes and machines,
returns a 32-bit unsigned int (no `% 2**32` dance), and is faster than
`hashlib.sha256`. We don't need crypto-strength uniqueness; we need
"this string maps to the same integer in every container."

**Hardcoded literal seeds** (`random.Random(42)`, `random.Random(77)`)
are fine — they're already stable.

**Where this currently applies:** Siting is the only pipeline with random
jitter today (per §0's audit table — "per-site economics … randomly
jittered around plausible ranges"). All four jitter sites use the CRC
pattern. Winter / Electrification / Investment / Expansion derive every
quantitative field from a real per-row catalog and have **zero**
`random.Random` instantiations; this rule applies preemptively to any
new pipeline that introduces stochastic substrate.

**Reviewer rule:** `random.Random(hash(...)` in a PR is a NACK. Either
swap to `zlib.crc32` or replace with a literal seed.

---

## 9. Completion message — `crud.complete_job(..., message=...)`

When a pipeline finishes, the orchestrator passes a pipeline-specific message
to [`complete_job`](../../../backend/db/crud.py) that surfaces in the live
header and progress log:

| Pipeline | Message |
|---|---|
| Siting | `"Siting plan ready"` |
| Winter Stress | `"Resilience plan ready"` |
| Electrification | `"Readiness plan ready"` |
| Investment | `"Investment plan ready"` |
| Expansion | `"Expansion plan ready"` |

---

## 10. Files to touch when adding a new pipeline

1. `backend/models/<pipeline>.py` — full Pydantic schema
2. `backend/models/report.py::PipelineStage` — add the 5 new stage enums
3. `backend/agents/<pipeline>_<stage>.py` — one agent file per stage
4. `backend/orchestrator.py::run_<pipeline>` — sequence the 5 agents, pass pipeline-specific `message=` to `complete_job`, and **follow the log-density contract in §11**
5. `backend/main.py` — `POST /api/<pipeline>` endpoint
6. `frontend/src/api/types.ts` — extend `PipelineStage` + Plan types
7. `frontend/src/api/client.ts` — submit + getResults helpers
8. `frontend/src/components/pipelineConfigs.ts` — 5 stage labels following §2
9. `frontend/src/components/stageviz/<Pipeline>StageViz.tsx` — 5 per-stage panels
10. `frontend/src/components/<Pipeline>Report.tsx` — wraps `<ReportShell>`, supplies
    `headerStats`, `winners` (with verdict-first per §3), `sections` (01/02/03 per §4),
    `execSummary`
11. `frontend/src/pipelines.ts` — add to `PIPELINES` catalog (id, label, short, accent)
12. `frontend/src/pages/HomePage.tsx` + `PipelinePage.tsx` — dispatch on `pipeline_id`

---

## 11. Progress-log density — substep updates inside parallel work

The live log panel in `PipelineLive` shows every `crud.update_progress` row
the orchestrator writes for the job. Across pipelines the operator should
see **roughly the same number of log lines per run** — otherwise one
pipeline (Siting was the original offender) looks "quiet" or "skipped"
while the others look healthy, and judges/operators wonder if the silent
one is broken.

**The contract:**

- Every pipeline emits **one progress line at the start of each of the 5
  stages**. That's the floor — 5 lines minimum.
- Pipelines that do **parallel fan-out work inside a stage** (Siting's
  per-region site generation + scoring; Winter Peak's per-scenario risk
  scoring; etc.) MUST emit a substep line on entry AND on completion for
  each parallel task. With N regions/scenarios that adds 2N lines, which is
  what closes the gap between Siting and the other 4.
- For pipelines built with agent objects (Winter Peak, Electrification,
  Investment, Expansion), this is wired via `progress_callback=progress`
  passed into each agent — the agent emits its own substep lines.
- For pipelines built with Langflow components (Siting), the orchestrator
  emits substep lines directly from inside the parallel task closures
  (`_gen_one`, `_score_one`). See `orchestrator.py::run_pipeline` for the
  pattern.

**Why this lives here:** the log panel is part of the shared `<PipelineLive>`
chrome (§6, "Live progress panel"). Inconsistent density is a cohesion bug,
not a backend implementation detail.

**Rule of thumb:** a 3-region siting run or a 3-scenario winter run should
produce **10–15 progress lines**. If a new pipeline ships with 5 or fewer,
it's under-emitting and needs substep callbacks.

---

## 11b. Chatbox follow-up — terse, plain text, no markdown

The sticky `<ReportChatBar>` at the bottom of every report streams Claude
responses grounded in the completed plan. The chat is **operator chat,
not a memo** — a follow-up question on a small bubble at the bottom of
the screen. The response style is enforced server-side by
`_CHAT_ANSWER_GUIDANCE` in [`backend/main.py`](../../../backend/main.py),
which is injected into the system prompt for every chat request across
every pipeline.

**Hard rules baked into the prompt:**

- **Plain text only.** No markdown — no tables, no headers, no bold
  (`**…**`), no italics (`*…*`), no bullet lists, no numbered lists, no
  horizontal rules (`---`), no code fences. The chat renderer
  *technically* supports markdown (`renderMarkdown` is the same one the
  executive summary uses) but it reads as visual noise on a two-sentence
  reply in a 80%-width bubble.
- **Exactly two sentences.** Sentence 1 carries the verdict / the
  number. Sentence 2 carries the one-clause reason. Em-dash connects a
  qualifier when natural. No third sentence; no preamble.
- **Implicit comparisons.** Name the alternative in one clause ("beats
  X on $/Y by ~10×"); never list both options in parallel structure.
- **Confident, numerical, no hedging.** Every sentence carries at least
  one figure. Drop "might / could / potentially". No trailing caveats.
- **Plain English, not power-systems jargon.** The audience is a planner
  or executive who understands grid investment but not engineering
  vocabulary. "N-1 failure" becomes "loses backup margin"; "feeder
  sectionalizing" becomes "automatic switching gear"; "POI headroom"
  becomes "spare grid-connection capacity." Numbers stay verbatim — only
  the connecting tissue translates.
- **No trailing offers** ("Want me to recompute…?", "Should I rerun…?").
- **No throat-clearing** ("Great question…", "Interesting result…").
- **No mode narration.** Claude internally picks between grounded /
  extrapolated / domain-knowledge modes; never name the mode in the
  output.

**Reference shape** — the right answer reads like a two-line verbal
reply from a colleague, not a Confluence page. Both shape (2 sentences,
verdict-first, em-dash connector, implicit comparison) and vocabulary
(plain English) matter equally:

| ✗ Don't | ✓ Do |
|---|---|
| Multi-paragraph response with a markdown table of options, bold headers, italicized aside, and a "Want me to recompute…?" close | "Fan cooling + automatic switching gear — ~$500K per substation restores backup margin without the 3-year wait for new transformers. Roughly 10× the resilience per dollar versus full transformer replacement." |
| "Under this polar vortex, 4–6 of 22 substations tip into N-1 failure territory at 50% HP. The 30% case is already the stress limit; 50% needs transformer capacity additions before 2030." (terse but jargon-heavy) | "Under this cold snap, 4–6 of the 22 substations lose backup margin — a single equipment trip would cause outages. 30% adoption is already the limit; 50% means new transformers installed before 2030." (terse AND plain-English) |
| "At 50%, four to six of the 22 substations lose their backup margin — meaning a single equipment trip would cause outages. 30% is already the limit; 50% needs new transformers installed before 2030, which would be a significant capital outlay." (3 sentences, trailing caveat) | "Under this cold snap, 4–6 of the 22 substations lose backup margin — a single equipment trip would cause outages. 30% adoption is already the limit; 50% means new transformers installed before 2030." (exactly 2, no caveat) |

**Visual contract on the frontend:**

- **Claude model picker pill is fixed-width (`width: 200px`)** in
  [`home.css`](../styles/home.css). The same `.model-pill` class
  drives the picker in both the New session composer (`HomePage.tsx`)
  and the sticky `<ReportChatBar>` on every report. Without a fixed
  width the pill resized between "Skorpio · Opus 4.7" and "Skorpio
  · Sonnet 4.6", which shifted the adjacent send button on every
  model switch and made the New session composer and the report
  chatbar look inconsistent at a glance. 200px (not 170 — that was
  too tight for "Skorpio · Sonnet 4.6" / "Skorpio · Haiku 4.5",
  which wrapped to two rows). `justify-content: space-between`
  keeps the label flush-left and the chevron flush-right inside the
  box; `white-space: nowrap` guarantees no wrap even if a future
  model name pushes the boundary. Changing the width is a
  cross-surface change — verify on both surfaces before merging.
- **User prompts render inside a rounded soft-fill bubble** (background
  `--bg-2`, border `--rule-2`, radius 14px, padding 10px×14px), right-
  aligned via flex. This matches Claude.ai / ChatGPT's pattern — the
  human input is the visually-weighted side of the conversation.
- **Assistant responses stay unboxed** — plain text on the page surface,
  left-aligned. Adding a bubble around the response makes a one-sentence
  answer look like UI chrome instead of speech.
- Both are wrapped in `.report-chatbar-msg` with an `EYEBROW` role label
  (`YOU` / `SKORPIO`) above. Don't change the role label vocabulary —
  it's the only signal to the user that "Skorpio" is the bot voice
  speaking, not a section header.

**Starter-prompt chips (inside the composer row):**

- **Source of truth: `pipelines.ts → PipelineMeta.chatStarters`.** Each
  pipeline defines exactly **2 chips**. Two — not three, not five — so the
  row never wraps and the visual weight matches the topic pill +
  model picker. Adding a third is a NACK; either it's worth replacing
  one of the existing chips or it isn't worth adding.
- **Placement:** inline in `.composer-row`, **right-aligned**
  immediately to the LEFT of the Claude model picker. The chip strip
  replaces the row's spacer (`flex: 1 1 auto`) so the topic pill
  stays pinned to the left edge, the model picker stays pinned to
  the right, and the chips sit flush against the model picker. Chips
  on the right rather than the left so they read as suggestions for
  the action (send) rather than a label on the topic pill.
- **Always visible.** Chips persist across the entire conversation —
  they don't disappear after the first message is sent or while the
  user is typing. Re-discoverability matters more than cold-start
  exclusivity; users come back to ask follow-ups and the chips need
  to be there.
- **Click behaviour: fill the composer + focus, never auto-send.**
  Auto-submit on click felt jarring because it skipped the
  "I'm in control of what gets sent" beat. The user can edit the
  filled text and press Enter (or the send button) when ready.
- **Sized to content with `max-width: 220px`** (`display: inline-block;
  max-width: 220px; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; text-align: right`). Short prompts produce
  short pills (no awkward blank space); anything longer than 220px
  truncates with `…` clipped at the right edge — the right-aligned
  text keeps the ellipsis flush against the model picker. Full text
  remains accessible via the `title` attribute on hover. Use
  `inline-block` (not `inline-flex`) on the button — flex containers
  silently break `text-overflow: ellipsis` on raw text nodes.
- **All composer-row controls share a 30px height** — the topic pill,
  the chip strip, and the `.model-pill` line up on the same baseline
  so the row reads as a single band of chrome instead of staggered
  pills. If you add a new control to `.composer-row`, match the 30px
  height or the row falls out of cohesion.
- **Voice:** chip labels follow the same plain-English rules as the
  answers (§11b above). Confident, jargon-translated, ≤55 characters
  so most labels render in full at 220px. If a label needs more
  characters than that to be clear, the question is too broad — split
  it or rewrite it.

**Reviewer rule:** if you see a chat reply with `|` table separators,
`**bold**`, `## headers`, or a "Want me to…?" tail, the system prompt
guidance has drifted. Fix `_CHAT_ANSWER_GUIDANCE`, not the rendered
output. The renderer is intentionally permissive; the discipline is the
prompt's job. Likewise, if a pipeline ships with 0, 1, 3, or more
chips — or chips that auto-submit — fix `pipelines.ts` /
`ReportChatBar.tsx`, don't carve a special case into the CSS.

---

## 12. Map scroll isolation — wheel locks the page when over the map

Every report embeds `<MapView>` for the "02 · map" section. The default
browser behaviour is that the scroll wheel pans the page even when the
cursor is over an inline map; for an operator trying to zoom the map (the
universal mental model for any embedded map), this feels broken.

**The contract:** when the cursor is inside `.skorpio-map`, the wheel
**must** zoom the map, never scroll the page. When the cursor leaves the
map, page scrolling resumes immediately.

**How it's wired:**

1. **`cooperativeGestures: false`** in the `mapboxgl.Map` constructor
   (`MapView.tsx`). Mapbox v3 turns this on by default on small viewports,
   which makes raw wheel-scroll pan the page and shows a "Use ctrl +
   scroll to zoom" hint. We always want raw wheel-zoom, so it's disabled
   explicitly.
2. **A capture-phase `wheel` listener on the map container** with
   `{ passive: false, capture: true }` (`MapView.tsx`). Calls
   `preventDefault()` BEFORE Mapbox's own handler runs. `passive: false`
   is what allows `preventDefault` to actually work on wheel events —
   Chrome ignores it without that since 2017. Mapbox still receives the
   event in the target/bubble phase and zooms normally.
3. **`overscroll-behavior: contain`** on `.skorpio-map` (`MapView.css`).
   Backstop in case any wheel event somehow leaks past the JS handler —
   it stops the scroll chain from reaching the page.
4. **SmoothStage hands-off zone** (`SmoothStage.tsx`). The workspace
   stage uses a custom wheel-lerp animation that calls `preventDefault`
   on every wheel event — *which swallows wheel before Mapbox can see it*.
   SmoothStage's `onWheel` is taught to early-return when the event
   target is inside `.skorpio-map` (or the generic opt-out class
   `skorpio-no-smooth-scroll`). Without this, none of the other three
   layers matter — SmoothStage runs first and steals the event.

**Why four layers:** in dev builds with HMR or in edge cases (cursor over
a marker DOM node sitting above the canvas, mid-style-load before Mapbox
has wired its own listener, etc.) any one layer can miss. The four
together make the contract robust without depending on any single one.

**When adding a new map embed:** use `<MapView>`. Don't instantiate
`mapboxgl.Map` directly elsewhere — that bypasses all four layers and
the page-scroll bug returns silently.

**When adding any other inner widget that owns its own wheel** (a custom
chart with wheel-to-pan, a code editor, etc.): add the class
`skorpio-no-smooth-scroll` to its outermost wrapper so SmoothStage hands
the wheel off cleanly.

---

## 13. Executive summary markdown — bold paragraph titles, no `---`, no tables

Every pipeline's final report ends with an executive-summary block
rendered through `<FinalReport>` → `.fr-md`. That block is the only place
the synthesis LLM emits free-form markdown, so the format has to be
locked down or it drifts pipeline-by-pipeline. The canonical shape (set
by `plan_synthesis.py` for Siting and now matched across the other four
synthesis agents) is:

```markdown
# Executive Summary: <one-line topic>

**<2-5 word bold title>**

<paragraph 1 prose — 2-4 sentences>

**<next bold title>**

<paragraph 2 prose>

(…4–5 paragraphs total, each opening with its own bold title)
```

**The hard rules** for the synthesis prompt (all five live in
`backend/agents/*_synthesis.py`):

- **Open with a single `# Executive Summary: <topic>` H1.** Establishes
  the dossier feel — the rest of the report's section headers are
  styled in the same family (`.fr-md h1` / `h2` / `h3` in
  `FinalReport.css`).
- **Each paragraph begins with `**<short bold title>**` on its own line.**
  2-5 words, sentence-case, descriptive (e.g. `**Headline Finding**`,
  `**Most Leveraged Intervention**`). The reader skimming the dossier
  uses these as landmarks; without them the wall of prose collapses
  into one undifferentiated block.
- **No `---` horizontal-rule dividers between paragraphs.** Bold titles
  already separate sections visually; an `hr` on top reads as a second
  redundant divider and creates the "random `---`" look the user
  flagged. The synthesis prompt now explicitly forbids them.
- **No markdown tables.** `.fr-md` doesn't enable GFM table parsing
  (`react-markdown` runs without `remark-gfm`), so `| col | col |`
  rows render as literal pipe characters and look broken. If the data
  belongs in a table, surface it in a structured section card
  upstream (e.g. mitigations, top feeders, region insights) rather
  than embedding it in the exec summary.
- **Paragraphs separated by blank lines (`\n\n`) only.** That's all
  the renderer needs to break them; nothing else.

**Why all five pipelines, not just the four:** Siting was the
reference, but its prompt didn't actually instruct any of this — the
LLM was choosing `**Bold Title**` *and* `---` autonomously. Locking
down all five gets us deterministic formatting across pipelines and
prevents Siting from drifting back to `---` on a future model rev.

**Reviewer rule:** if a synthesis-agent prompt diff loosens any of the
above (drops the `# Executive Summary:` directive, re-introduces "the
output is rendered as markdown" without the explicit `---` ban,
removes the table ban, etc.), NACK it — the four constraints are the
only thing standing between the dossier and free-form Claude output.

---

## 14. Chat-followup answers — grounded generation, templated numbers, LLM reasoning

Every report ends with a `<ReportChatBar>` that streams Claude's reply
to operator follow-ups, grounded in the persisted plan. The chat
endpoint ([`routers/chat.py`](../../../backend/routers/chat.py)) and tools
([`chat_tools.py`](../../../backend/chat_tools.py)) implement the
**grounded generation** pattern — the industry-standard approach for
domain assistants where wrong digits cause real harm (planners making
investment calls on hallucinated MW figures). This section is the
contract for that subsystem.

### Three-tier answer hierarchy

Pick the first tier that applies, silently — never narrate the choice.

1. **GROUNDED.** When the answer is already in the report JSON (existing
   peak, top candidates, funded set, methodology, definitions), read the
   exact value from the curated context block and use it. No tool call.

2. **TOOL-COMPUTED.** When the question is a counterfactual on a numeric
   parameter exposed by a tool — HP/EV adoption %, target MW, budget $,
   region/LCOE constraint — the model MUST call the matching
   `recompute_*` / `reoptimize_*` / `filter_*` tool BEFORE composing the
   reply. The tool's `narration` field is the authoritative sentence 1
   (copy verbatim, no paraphrase); sentence 2 is LLM-generated reasoning
   over the report context, ending with the parenthetical hedge
   `(first-order, linear-scaled from the X% anchor)`.

3. **EXTRAPOLATED / DOMAIN KNOWLEDGE.** When no tool covers the
   parameter, fall back to first-order extrapolation from report figures
   (with `~` hedge) or industry rule-of-thumb (with explicit hedge like
   "industry typical ~"). Never refuse — give an actionable answer.

### Why sentence 1 is templated, not LLM-generated

This is the part that feels counter-intuitive ("why is the chatbot
copying a string?") and is the most-questioned design choice in the
codebase, so the reasoning is preserved here:

**The failure mode.** Language models routinely confuse near-synonymous
numeric fields when reading structured tool output. Asked to narrate
`{"projected_peak_mw": 3779.8, "headroom_mw": 1425.4}`, the model has
a non-trivial chance of writing "peak climbs to 1,425.4 MW, leaving
3,779.8 MW of headroom" — both numbers from the tool, both labeled
wrong. Field-swap errors compound: planners reading the swapped output
make the opposite-of-correct call.

**The fix.** Each counterfactual tool emits a pre-formatted
`narration` field built from its own computed values:

> "At 50% HP / 30% EV the network peaks at 3,780 MW, leaving 1,425 MW
> of headroom (27.4% of nameplate) — still a pass"

The model is instructed (both in the tool description and in
`_CHAT_ANSWER_GUIDANCE`) to copy that narration verbatim as sentence 1.
The values are guaranteed correct because the Python f-string built
them; the model can't introduce drift because it doesn't re-read
individual fields. Sentence 2 is fully LLM-generated and reasons over
the report context — which feeders bear the load, how the result
compares to the anchor scenario, what to flag for follow-up.

**Why this is industry best practice.** Production LLM systems that
expose computed values (Wolfram Alpha integration in ChatGPT, financial
support bots, medical assistants) universally use this pattern: tools
return ground-truth strings, the LLM narrates *around* them. It's the
"augmented LLM" / "grounded generation" pattern formalized in
Anthropic's tool-use docs. The LLM's value-add is in language and
reasoning, not in transcribing numeric fields — the latter is a
known weakness, not a target capability.

**Where the LLM still earns its keep.** Sentence 2. Which feeders to
mention, how the result compares to the planner's mental model, what
to suggest as the next action. All qualitative; no field-swap risk;
genuine value-add.

### Adding a new counterfactual tool — the contract

Any new `recompute_*` / `reoptimize_*` / `filter_*` tool added to
`chat_tools.py` MUST:

1. **Emit a `narration` string** built from its own computed values.
   The narration is the headline finding in one sentence, structured
   so the operator can read it standalone — opens with the
   counterfactual parameters ("At 50% HP / 30% EV…"), states the
   computed result with its unit, ends with a verdict tag
   ("still a pass" / "tighter pass" / "overshoots safe capacity").

2. **Carry trigger-phrase guidance in the tool description.** Open
   with `ALWAYS call this for any counterfactual on <parameter>` and
   enumerate ≥5 trigger phrases the operator might use ("what if X
   hits Y%", "at Z% adoption", "if EV goes to N%", etc.). Bare
   "use this for counterfactuals" is too neutral for
   `tool_choice:"auto"` to fire reliably.

3. **Instruct the model to use `narration` verbatim.** The tool
   description includes a NARRATION RULE block:
   *"Use that `narration` string verbatim as sentence 1 of your
   reply. Do NOT re-extract individual fields and re-label them
   yourself — that has caused field-swap errors in the past."*

4. **Register in `tool_result_to_facts()` minimally — peak/headline
   only.** Keys with broad keyword hints (`load`, `headroom`) cause
   false-positive reconciliation rewrites of unrelated numbers
   (feeder IDs, deltas between scenarios). Register only the single
   most-important value, and only if reconciliation would actually
   help — see §14e below.

### Reconciliation: skip when a tool ran

`utils/reconciliation.py` exists as a defense against Claude
hallucinating digits in tier-1 (GROUNDED) answers — the model says
"3,800 MW" when the report says "3,387 MW", reconciler catches the
5%+ drift and rewrites. That's the right defense for ungrounded
generation.

It is the **wrong** defense for tier-2 (TOOL-COMPUTED) answers. The
reconciler matches numbers within a 50-char window of a keyword,
and when a sentence contains multiple numbers in close proximity
("peak X MW, leaving Y MW of headroom") the keyword window covers
both. The reconciler then rewrites the wrong one — turning a
correctly-templated answer into a broken one.

**The rule:** if a counterfactual tool fired this turn,
`stream_response()` SKIPS reconciliation entirely. The tool's
`narration` string is the authoritative answer; reconciler keyword
matching cannot improve on it and routinely makes it worse. The
`if tool_facts: skip reconcile()` branch in
[`routers/chat.py`](../../../backend/routers/chat.py) enforces this.

### The two-sentence + hedge format

Hard rules enforced via `_CHAT_ANSWER_GUIDANCE` in `chat.py`:

- **Plain text only.** No markdown — no tables, no headers, no bold,
  no italics, no bullets, no horizontal rules, no code fences. The
  `<ReportChatBar>` renders chat lines as plain text by design, so
  any markdown shows up as literal asterisks and pipes.
- **Exactly two sentences.** Sentence 1: the verdict / number.
  Sentence 2: the one-clause reason. Em-dash to connect a qualifier
  when natural. No third sentence. No preamble. No
  "Great question…" throat-clearing. No trailing "want me to…?"
  offers.
- **One parenthetical hedge allowed — but only when a tool was
  called.** Format:
  `(first-order, linear-scaled from the X% anchor)`. This is the
  only case where extra text after sentence 2 is permitted; it
  signals to the operator that the system computed rather than
  guessed, which is the trust-establishing move for a
  counterfactual.

### Plain English, not engineering jargon

The reader is a planner or executive who understands grid investment
but not power-systems vocabulary. Translate inline:

| Jargon | Plain-English replacement |
|---|---|
| "N-1 failure" | "loses backup margin" |
| "transformer procurement" | "new transformers (~3-year wait)" |
| "feeder sectionalizing" | "automatic switching gear" |
| "POI headroom" | "spare grid-connection capacity" |
| "HP COP" | "heat pump efficiency" |
| "polar vortex nadir" | "coldest hour of the cold snap" |
| "$/resilience" | "resilience per dollar" |

Numbers stay — "1,425 MW" or "$500K" reads fine to any audience.
Only the connecting tissue translates.

### Reviewer rules

- A new counterfactual tool without a `narration` field → NACK. The
  tool description and `_CHAT_ANSWER_GUIDANCE` both assume one
  exists; missing it reintroduces the field-swap failure mode.
- A diff that removes the `if tool_facts: skip reconcile()` branch in
  `routers/chat.py` → NACK. Reconciliation will rewrite the
  templated narration in confusing ways the moment two numbers
  share a keyword window.
- A diff that relaxes "exactly two sentences" or adds markdown
  permission to `_CHAT_ANSWER_GUIDANCE` → NACK. The chat surface
  is a terse sidebar, not a memo; markdown shows as literal
  characters and three-paragraph answers break the operator's
  skim.
- A `recompute_*` tool with a `narration` that doesn't open with
  the counterfactual parameters and end with a verdict tag → NACK.
  Standalone readability of sentence 1 is the contract.

---

## 14. Chat-followup answers — grounded generation, templated numbers, LLM reasoning

Every report ends with a `<ReportChatBar>` that streams Claude's reply
to operator follow-ups, grounded in the persisted plan. The chat
endpoint ([`routers/chat.py`](../../../backend/routers/chat.py)) and tools
([`chat_tools.py`](../../../backend/chat_tools.py)) implement the
**grounded generation** pattern — the industry-standard approach for
domain assistants where wrong digits cause real harm (planners making
investment calls on hallucinated MW figures). This section is the
contract for that subsystem.

### Three-tier answer hierarchy

Pick the first tier that applies, silently — never narrate the choice.

1. **GROUNDED.** When the answer is already in the report JSON (existing
   peak, top candidates, funded set, methodology, definitions), read the
   exact value from the curated context block and use it. No tool call.

2. **TOOL-COMPUTED.** When the question is a counterfactual on a numeric
   parameter exposed by a tool — HP/EV adoption %, target MW, budget $,
   region/LCOE constraint — the model MUST call the matching
   `recompute_*` / `reoptimize_*` / `filter_*` tool BEFORE composing the
   reply. The tool's `narration` field is the authoritative sentence 1
   (copy verbatim, no paraphrase); sentence 2 is LLM-generated reasoning
   over the report context, ending with the parenthetical hedge
   `(first-order, linear-scaled from the X% anchor)`.

3. **EXTRAPOLATED / DOMAIN KNOWLEDGE.** When no tool covers the
   parameter, fall back to first-order extrapolation from report figures
   (with `~` hedge) or industry rule-of-thumb (with explicit hedge like
   "industry typical ~"). Never refuse — give an actionable answer.

### Why sentence 1 is templated, not LLM-generated

This is the part that feels counter-intuitive ("why is the chatbot
copying a string?") and is the most-questioned design choice in the
codebase, so the reasoning is preserved here:

**The failure mode.** Language models routinely confuse near-synonymous
numeric fields when reading structured tool output. Asked to narrate
`{"projected_peak_mw": 3779.8, "headroom_mw": 1425.4}`, the model has
a non-trivial chance of writing "peak climbs to 1,425.4 MW, leaving
3,779.8 MW of headroom" — both numbers from the tool, both labeled
wrong. Field-swap errors compound: planners reading the swapped output
make the opposite-of-correct call.

**The fix.** Each counterfactual tool emits a pre-formatted
`narration` field built from its own computed values:

> "At 50% HP / 30% EV the network peaks at 3,780 MW, leaving 1,425 MW
> of headroom (27.4% of nameplate) — still a pass"

The model is instructed (both in the tool description and in
`_CHAT_ANSWER_GUIDANCE`) to copy that narration verbatim as sentence 1.
The values are guaranteed correct because the Python f-string built
them; the model can't introduce drift because it doesn't re-read
individual fields. Sentence 2 is fully LLM-generated and reasons over
the report context — which feeders bear the load, how the result
compares to the anchor scenario, what to flag for follow-up.

**Why this is industry best practice.** Production LLM systems that
expose computed values (Wolfram Alpha integration in ChatGPT, financial
support bots, medical assistants) universally use this pattern: tools
return ground-truth strings, the LLM narrates *around* them. It's the
"augmented LLM" / "grounded generation" pattern formalized in
Anthropic's tool-use docs. The LLM's value-add is in language and
reasoning, not in transcribing numeric fields — the latter is a
known weakness, not a target capability.

**Where the LLM still earns its keep.** Sentence 2. Which feeders to
mention, how the result compares to the planner's mental model, what
to suggest as the next action. All qualitative; no field-swap risk;
genuine value-add.

### Adding a new counterfactual tool — the contract

Any new `recompute_*` / `reoptimize_*` / `filter_*` tool added to
`chat_tools.py` MUST:

1. **Emit a `narration` string** built from its own computed values.
   The narration is the headline finding in one sentence, structured
   so the operator can read it standalone — opens with the
   counterfactual parameters ("At 50% HP / 30% EV…"), states the
   computed result with its unit, ends with a verdict tag
   ("still a pass" / "tighter pass" / "overshoots safe capacity").

2. **Carry trigger-phrase guidance in the tool description.** Open
   with `ALWAYS call this for any counterfactual on <parameter>` and
   enumerate ≥5 trigger phrases the operator might use ("what if X
   hits Y%", "at Z% adoption", "if EV goes to N%", etc.). Bare
   "use this for counterfactuals" is too neutral for
   `tool_choice:"auto"` to fire reliably.

3. **Instruct the model to use `narration` verbatim.** The tool
   description includes a NARRATION RULE block:
   *"Use that `narration` string verbatim as sentence 1 of your
   reply. Do NOT re-extract individual fields and re-label them
   yourself — that has caused field-swap errors in the past."*

4. **Register in `tool_result_to_facts()` minimally — peak/headline
   only.** Keys with broad keyword hints (`load`, `headroom`) cause
   false-positive reconciliation rewrites of unrelated numbers
   (feeder IDs, deltas between scenarios). Register only the single
   most-important value, and only if reconciliation would actually
   help — see §14e below.

### Reconciliation: skip when a tool ran

`utils/reconciliation.py` exists as a defense against Claude
hallucinating digits in tier-1 (GROUNDED) answers — the model says
"3,800 MW" when the report says "3,387 MW", reconciler catches the
5%+ drift and rewrites. That's the right defense for ungrounded
generation.

It is the **wrong** defense for tier-2 (TOOL-COMPUTED) answers. The
reconciler matches numbers within a 50-char window of a keyword,
and when a sentence contains multiple numbers in close proximity
("peak X MW, leaving Y MW of headroom") the keyword window covers
both. The reconciler then rewrites the wrong one — turning a
correctly-templated answer into a broken one.

**The rule:** if a counterfactual tool fired this turn,
`stream_response()` SKIPS reconciliation entirely. The tool's
`narration` string is the authoritative answer; reconciler keyword
matching cannot improve on it and routinely makes it worse. The
`if tool_facts: skip reconcile()` branch in
[`routers/chat.py`](../../../backend/routers/chat.py) enforces this.

### The two-sentence + hedge format

Hard rules enforced via `_CHAT_ANSWER_GUIDANCE` in `chat.py`:

- **Plain text only.** No markdown — no tables, no headers, no bold,
  no italics, no bullets, no horizontal rules, no code fences. The
  `<ReportChatBar>` renders chat lines as plain text by design, so
  any markdown shows up as literal asterisks and pipes.
- **Exactly two sentences.** Sentence 1: the verdict / number.
  Sentence 2: the one-clause reason. Em-dash to connect a qualifier
  when natural. No third sentence. No preamble. No
  "Great question…" throat-clearing. No trailing "want me to…?"
  offers.
- **One parenthetical hedge allowed — but only when a tool was
  called.** Format:
  `(first-order, linear-scaled from the X% anchor)`. This is the
  only case where extra text after sentence 2 is permitted; it
  signals to the operator that the system computed rather than
  guessed, which is the trust-establishing move for a
  counterfactual.

### Plain English, not engineering jargon

The reader is a planner or executive who understands grid investment
but not power-systems vocabulary. Translate inline:

| Jargon | Plain-English replacement |
|---|---|
| "N-1 failure" | "loses backup margin" |
| "transformer procurement" | "new transformers (~3-year wait)" |
| "feeder sectionalizing" | "automatic switching gear" |
| "POI headroom" | "spare grid-connection capacity" |
| "HP COP" | "heat pump efficiency" |
| "polar vortex nadir" | "coldest hour of the cold snap" |
| "$/resilience" | "resilience per dollar" |

Numbers stay — "1,425 MW" or "$500K" reads fine to any audience.
Only the connecting tissue translates.

### Reviewer rules

- A new counterfactual tool without a `narration` field → NACK. The
  tool description and `_CHAT_ANSWER_GUIDANCE` both assume one
  exists; missing it reintroduces the field-swap failure mode.
- A diff that removes the `if tool_facts: skip reconcile()` branch in
  `routers/chat.py` → NACK. Reconciliation will rewrite the
  templated narration in confusing ways the moment two numbers
  share a keyword window.
- A diff that relaxes "exactly two sentences" or adds markdown
  permission to `_CHAT_ANSWER_GUIDANCE` → NACK. The chat surface
  is a terse sidebar, not a memo; markdown shows as literal
  characters and three-paragraph answers break the operator's
  skim.
- A `recompute_*` tool with a `narration` that doesn't open with
  the counterfactual parameters and end with a verdict tag → NACK.
  Standalone readability of sentence 1 is the contract.
