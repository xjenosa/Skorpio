// Real data extracted from job 476a2f1a-d426-4ec2-b434-2e3fc581bbfe
// Pipeline: winter-peak-stress · Mississauga · polar_vortex_2014 · Custom 30% HP / 30% EV
// Verdict: PASS — peaks at 3387 MW with 32% headroom.
//
// (Network, scenario inputs, load curve, top feeders, and verdict are
// identical to the earlier 4b62134b run because the pipeline's hourly
// load decomposition is deterministic for the same (city × cold-event ×
// adoption %) tuple. Only the LLM-generated mitigation set differs
// between runs — those numbers come from a new Claude call each time
// and are what drives the chat-followup transcript shown in scene 11.)

type Feeder = {
  id: string;
  capPct: number;
  ttfHr: number | null;
  risk: number;
  why: string;
};

type Mitigation = {
  title: string;
  reliefMw: number;
  costMillionsCad: number;
  riskDropPct: number;
  months: number;
};

const TOP_FEEDERS: Feeder[] = [
  {
    id: "MIS-01-F01",
    capPct: 30.7,
    ttfHr: null,
    risk: 0.08,
    why: "18yr · 15% baseboard share · 1,088 customers · EV coincident load",
  },
  {
    id: "MIS-01-F02",
    capPct: 34.2,
    ttfHr: null,
    risk: 0.13,
    why: "21yr · never upgraded · 5% existing HP share grows under scenario",
  },
  {
    id: "MIS-01-F03",
    capPct: 38.1,
    ttfHr: null,
    risk: 0.14,
    why: "24yr · never upgraded · 1,360 customers · 6% existing HP",
  },
  {
    id: "MIS-01-F04",
    capPct: 42.3,
    ttfHr: null,
    risk: 0.16,
    why: "27yr · 15% baseboard · sustained voltage sag under cold load",
  },
  {
    id: "MIS-01-F05",
    capPct: 45.6,
    ttfHr: null,
    risk: 0.18,
    why: "30yr · highest-loaded in group · candidate for reconductor",
  },
];

const MITIGATIONS: Mitigation[] = [
  {
    title: "Residential demand response · MIS-01-F01/F02/F03",
    reliefMw: 4.2,
    costMillionsCad: 0.18,
    riskDropPct: 12,
    months: 6,
  },
  {
    title: "Reconductor MIS-01-F03",
    reliefMw: 6.0,
    costMillionsCad: 1.2,
    riskDropPct: 18,
    months: 18,
  },
  {
    title: "Reconductor MIS-01-F02",
    reliefMw: 5.0,
    costMillionsCad: 1.0,
    riskDropPct: 14,
    months: 18,
  },
  {
    title: "Time-of-use EV charging shift",
    reliefMw: 3.8,
    costMillionsCad: 0.095,
    riskDropPct: 10,
    months: 9,
  },
  {
    title: "Substation transformer capacity upgrade",
    reliefMw: 12.0,
    costMillionsCad: 3.5,
    riskDropPct: 22,
    months: 30,
  },
];

export const REPORT = {
  jobIdShort: "476a2f1",
  query:
    "Will Mississauga's grid hold a -25°C polar vortex with 30% heat pump adoption?",
  city: "Mississauga",
  utility: "Alectra Utilities",
  province: "ON",
  isoZone: "IESO-Toronto",
  horizonYear: 2030,
  coldEvent: {
    id: "polar_vortex_2014",
    name: "Jan 2014 Polar Vortex",
    minTempC: -25.5,
    modeledFloorC: -28,
    durationHours: 120,
  },
  network: {
    substationCount: 22,
    feederCount: 176,
    baselineWinterPeakMw: 3855.4,
    baselineYear: 2024,
    customers: 230384,
  },
  scenario: {
    label: "Custom 30% HP · 30% EV",
    heatPumpPct: 30,
    evPct: 30,
  },
  // For a PASS verdict, shortfallMw is *negative* (i.e. surplus / headroom)
  // and atRiskFeeders is 0 — the scene renderer keys off summary === "PASS"
  // to flip color + framing from red shortfall to green headroom.
  verdict: {
    summary: "PASS",
    peakLoadMw: 3387.1,
    peakHourOffset: 43,
    peakTempC: -28,
    safeCapacityMw: 4944.9, // peak + headroom
    shortfallMw: -1557.8, // negative = headroom
    shortfallPct: -31.5,
    atRiskFeeders: 0,
    headline: "Network holds — peaks at 3387 MW with 32% headroom.",
  },
  topFeeders: TOP_FEEDERS,
  mitigations: MITIGATIONS,
};

// Verdict color palette mirrored from frontend/src/components/reportStyle.ts
export const VERDICT_COLOR = {
  good: "#6fcf8e",
  warning: "#e0a44a",
  critical: "#f38764",
  neutral: "#b3b1a8",
} as const;

// 120-hour total-load curve in MW from scenarios[0].load_profile.hours[].total_load_mw
// Peaks at 3387.1 MW at hour 43 (-28°C peak temp). Safe capacity = 4945 MW.
export const LOAD_CURVE_MW: number[] = [
  2223.1, 2329.8, 2327.6, 2329.7, 2357.3, 2423.3, 2385.1, 2526.1, 2571.3,
  2444.7, 2406.2, 2405.9, 2433.0, 2445.5, 2458.0, 2489.7, 2567.8, 2676.1,
  3212.6, 3244.5, 3216.6, 3169.5, 3090.4, 3013.8, 2769.5, 2737.6, 2718.4,
  2705.7, 2718.4, 2769.5, 2680.6, 2808.3, 2746.1, 2594.9, 2543.8, 2531.1,
  2543.8, 2543.8, 2543.8, 2563.0, 2715.9, 2811.7, 3374.3, 3387.1, 3342.4,
  3278.5, 3182.8, 3087.0, 2769.5, 2737.6, 2718.4, 2705.7, 2718.4, 2769.5,
  2680.6, 2808.3, 2746.1, 2594.9, 2543.8, 2531.1, 2543.8, 2543.8, 2543.8,
  2563.0, 2715.9, 2811.7, 3374.3, 3387.1, 3342.4, 3278.5, 3182.8, 3087.0,
  2769.5, 2737.6, 2718.4, 2705.7, 2718.4, 2769.5, 2680.6, 2808.3, 2746.1,
  2594.9, 2543.8, 2531.1, 2543.8, 2543.8, 2543.8, 2563.0, 2715.9, 2811.7,
  3374.3, 3387.1, 3342.4, 3278.5, 3182.8, 3087.0, 2726.5, 2667.4, 2631.3,
  2599.4, 2595.2, 2627.1, 2537.1, 2647.7, 2664.4, 2501.9, 2436.6, 2407.7,
  2404.4, 2390.1, 2374.0, 2378.8, 2426.6, 2508.1, 2949.4, 2943.1, 2876.9,
  2664.7, 2537.3, 2415.7,
];

// 120-hour temperature curve in °C — same polar_vortex_2014 event as winterPeakReport.ts
export const TEMP_CURVE_C: number[] = [
  -8, -8.7, -9.5, -10.2, -10.9, -11.6, -12.4, -13.1, -13.8, -14.6, -15.3, -16,
  -16.8, -17.5, -18.2, -18.9, -19.7, -20.4, -21.1, -21.9, -22.6, -23.3, -24,
  -24.8, -28, -28, -28, -28, -28, -28, -28, -28, -23, -23, -23, -23, -23, -23,
  -23, -23, -28, -28, -28, -28, -28, -28, -28, -28, -28, -28, -28, -28, -28,
  -28, -28, -28, -23, -23, -23, -23, -23, -23, -23, -23, -28, -28, -28, -28,
  -28, -28, -28, -28, -28, -28, -28, -28, -28, -28, -28, -28, -23, -23, -23,
  -23, -23, -23, -23, -23, -28, -28, -28, -28, -28, -28, -28, -28, -25.5,
  -24.6, -23.8, -22.9, -22.1, -21.2, -20.4, -19.5, -18.7, -17.8, -17, -16.1,
  -15.2, -14.4, -13.5, -12.7, -11.8, -11, -10.1, -9.3, -8.4, -7.6, -6.7, -5.9,
];
