// Skorpio Console — fake data
window.SkorpioData = {
  user: { name: "Mara Vasquez", role: "Siting Lead", avatar: "MV" },
  workspace: { name: "NorthStar AI · Production", id: "ws_northstar" },
  regions: [
    { id: "PJM-W",  label: "PJM-WEST", state: "clean", available: 84.2, carbon: 187 },
    { id: "ERCOT", label: "ERCOT",    state: "mid",   available: 42.0, carbon: 412 },
    { id: "CAISO", label: "CAISO",    state: "clean", available: 31.8, carbon: 138 },
    { id: "MISO",  label: "MISO",     state: "dirty", available: 12.4, carbon: 590 },
    { id: "SPP",   label: "SPP",      state: "mid",   available: 28.6, carbon: 365 },
  ],
  sites: [
    { id: "ALPHA-04", name: "Sterling, OH",   region: "PJM-W",  capacityMW: 38.4, carbon: 187, spot: 48.40, state: "clean", pue: 1.18, score: 0.92 },
    { id: "BETA-11",  name: "Abilene, TX",    region: "ERCOT", capacityMW: 64.0, carbon: 412, spot: 31.10, state: "mid",   pue: 1.32, score: 0.81 },
    { id: "GAMMA-02", name: "Bend, OR",       region: "CAISO", capacityMW: 22.6, carbon: 138, spot: 56.80, state: "clean", pue: 1.14, score: 0.88 },
    { id: "DELTA-07", name: "Dubuque, IA",    region: "MISO",  capacityMW: 18.0, carbon: 590, spot: 28.20, state: "dirty", pue: 1.42, score: 0.54 },
    { id: "EPSILON-01", name: "Tulsa, OK",    region: "SPP",   capacityMW: 30.2, carbon: 365, spot: 33.40, state: "mid",   pue: 1.28, score: 0.71 },
    { id: "ZETA-09",  name: "Carlisle, PA",   region: "PJM-W", capacityMW: 51.0, carbon: 210, spot: 47.10, state: "clean", pue: 1.20, score: 0.86 },
  ],
  recentRuns: [
    { id: "run_2810", label: "Training cluster · Q3 expansion", at: "14:02", status: "complete", best: "ALPHA-04" },
    { id: "run_2809", label: "Inference fleet · West Coast",     at: "11:48", status: "complete", best: "GAMMA-02" },
    { id: "run_2808", label: "Edge POPs · Texas triangle",       at: "09:12", status: "complete", best: "BETA-11" },
    { id: "run_2807", label: "DR · Colocation candidate scan",   at: "yesterday", status: "complete", best: "ZETA-09" },
  ],
  pipelineStages: [
    { id: "ingest",  label: "Ingest grid telemetry",   detail: "PJM-W · ERCOT · CAISO · MISO · SPP" },
    { id: "filter",  label: "Filter by constraints",   detail: "Capacity ≥ 12 MW · latency ≤ 35ms" },
    { id: "score",   label: "Score by carbon · cost",  detail: "Pareto front · 18-month horizon" },
    { id: "verify",  label: "Verify transmission",     detail: "Cross-check ISO interconnection queue" },
    { id: "rank",    label: "Rank candidates",         detail: "Top-K = 12" },
    { id: "report",  label: "Compose siting plan",     detail: "Markdown + JSON · sign-off ready" },
  ],
  pipelineLog: [
    { t: "14:01:58.221", level: "info", msg: "Run 2810 received · workload=training-cluster · target=42 MW" },
    { t: "14:01:58.412", level: "info", msg: "Connecting to PJM-W telemetry stream …" },
    { t: "14:01:58.804", level: "info", msg: "PJM-W stream established · lag 188ms" },
    { t: "14:01:59.110", level: "info", msg: "ERCOT, CAISO, MISO, SPP joined" },
    { t: "14:02:01.500", level: "warn", msg: "MISO transmission constraint flagged · derating 23%" },
    { t: "14:02:03.220", level: "info", msg: "Pareto front computed · 47 candidates → top 12" },
    { t: "14:02:04.020", level: "ok",   msg: "Verification passed · siting plan ready" },
  ],
};
