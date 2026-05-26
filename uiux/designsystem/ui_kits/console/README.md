# Skorpio Console — UI Kit

The Console is Skorpio's operator surface: where you launch siting runs, watch the agentic pipeline execute, and read the resulting plan.

## Components

| File | Purpose |
|---|---|
| `index.html` | Interactive demo. Click through Sites → Run siting → Pipeline → Report. |
| `Shell.jsx` | Top bar + left rail + page region. Layout primitives. |
| `Sidebar.jsx` | Left rail with nav, region picker, run history. |
| `Topbar.jsx` | Workspace switcher + global search + status pill. |
| `SitingComposer.jsx` | The "new run" composer — workload, region, constraints, kickoff button. |
| `PipelinePanel.jsx` | Live agentic pipeline view: stages, live log lines, telemetry HUD. |
| `SiteCard.jsx` | A single candidate site — capacity, carbon, spot, energy state. |
| `MetricsRail.jsx` | Stat tiles row used on the dashboard. |
| `data.js` | Fake data for sites, runs, pipeline events. |

## Screens demonstrated

1. **Dashboard** — metrics rail + recent runs + 4 candidate site cards.
2. **Composer** — siting input form with chip filters and constraints.
3. **Pipeline (running)** — live log + stage progress + telemetry HUD; this is the "dark zone" view.
4. **Report** — the resulting siting plan, ranked.

## Notes

- The kit is hi-fi cosmetic, not production. State is in-memory; no real API calls.
- All copy follows the voice in the root README.
- Icons via Lucide CDN.
