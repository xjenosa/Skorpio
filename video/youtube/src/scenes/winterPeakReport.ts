// Real data extracted from report 57b8f39f-cd3e-4b4f-9618-d54d8ab36621
// Pipeline: winter-peak-stress · Mississauga · polar_vortex_2014 · Custom 30% HP / 30% EV

export const REPORT = {
  jobIdShort: "57b8f39f",
  query: "Will Mississauga's grid hold a -25°C polar vortex with 30% heat pump adoption?",
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
    baselineWinterPeakMw: 1650,
    baselineYear: 2024,
    customers: 230384,
  },
  scenario: {
    label: "Custom 30% HP · 30% EV",
    heatPumpPct: 30,
    evPct: 30,
  },
  verdict: {
    summary: "FAIL",
    peakLoadMw: 2527.2,
    peakHourOffset: 43,
    peakTempC: -28,
    safeCapacityMw: 2115.1,
    shortfallMw: -412.1,
    shortfallPct: -19.5,
    atRiskFeeders: 22,
    headline: "Network fails — peaks at 2527 MW, 20% over capacity.",
  },
  topFeeders: [
    { id: "MIS-01-F05", capPct: 106.6, ttfHr: 20.8, risk: 0.67, why: "Aged residential, dense heat pumps, no recent upgrade" },
    { id: "MIS-02-F05", capPct: 106.6, ttfHr: 20.8, risk: 0.67, why: "Same residential template as MIS-01-F05" },
    { id: "MIS-03-F05", capPct: 106.6, ttfHr: 20.8, risk: 0.67, why: "Battery storage targeted in plan" },
    { id: "MIS-01-F04", capPct: 98.8, ttfHr: null, risk: 0.47, why: "Sustained voltage sag under cold load" },
    { id: "MIS-09-F04", capPct: 98.8, ttfHr: null, risk: 0.47, why: "Long laterals · approaching limit" },
  ],
  mitigations: [
    { title: "Winter demand-response on 22 feeders", reliefMw: 45, costMillionsCad: 1.8, riskDropPct: 11, months: 6 },
    { title: "Reconductor MIS-01/02/03 F05", reliefMw: 12, costMillionsCad: 4.5, riskDropPct: 8, months: 18 },
    { title: "Substation transformer upgrade", reliefMw: 80, costMillionsCad: 10.0, riskDropPct: 19, months: 30 },
    { title: "Managed EV charging shift", reliefMw: 55, costMillionsCad: 2.2, riskDropPct: 13, months: 9 },
    { title: "Battery storage · MIS-01/02/03", reliefMw: 30, costMillionsCad: 9.0, riskDropPct: 7, months: 24 },
  ],
};

// 22 Mississauga substations with real lat/lon and aggregate risk score
// from network.substations[] + scenarios[0].substation_risks[]. All 22 sit
// in the "warning" band (>= 0.5, < 0.75) per the report's risk thresholds.
export const SUBSTATIONS: {
  id: string;
  name: string;
  lat: number;
  lon: number;
  risk: number;
  utilizationPct: number;
  atRiskFeederCount: number;
  feederCount: number;
}[] = [
  { id: "MIS-01", name: "Mississauga TS 01", lat: 43.494, lon: -79.7941, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-02", name: "Mississauga TS 02", lat: 43.49352, lon: -79.77981, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-03", name: "Mississauga TS 03", lat: 43.51305, lon: -79.76553, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-04", name: "Mississauga TS 04", lat: 43.51257, lon: -79.75124, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-05", name: "Mississauga TS 05", lat: 43.5321, lon: -79.73696, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-06", name: "Mississauga TS 06", lat: 43.53162, lon: -79.72267, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-07", name: "Mississauga TS 07", lat: 43.55114, lon: -79.70839, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-08", name: "Mississauga TS 08", lat: 43.55067, lon: -79.6941, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-09", name: "Mississauga TS 09", lat: 43.57019, lon: -79.67981, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-10", name: "Mississauga TS 10", lat: 43.56971, lon: -79.66553, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-11", name: "Mississauga TS 11", lat: 43.58924, lon: -79.65124, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-12", name: "Mississauga TS 12", lat: 43.58876, lon: -79.63696, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-13", name: "Mississauga TS 13", lat: 43.60829, lon: -79.62267, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-14", name: "Mississauga TS 14", lat: 43.60781, lon: -79.60839, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-15", name: "Mississauga TS 15", lat: 43.62733, lon: -79.5941, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-16", name: "Mississauga TS 16", lat: 43.62686, lon: -79.57981, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-17", name: "Mississauga TS 17", lat: 43.64638, lon: -79.56553, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-18", name: "Mississauga TS 18", lat: 43.6459, lon: -79.55124, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-19", name: "Mississauga TS 19", lat: 43.66543, lon: -79.53696, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-20", name: "Mississauga TS 20", lat: 43.66495, lon: -79.52267, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-21", name: "Mississauga TS 21", lat: 43.68448, lon: -79.50839, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
  { id: "MIS-22", name: "Mississauga TS 22", lat: 43.684, lon: -79.4941, risk: 0.666, utilizationPct: 89.1, atRiskFeederCount: 1, feederCount: 8 },
];

// Verdict color palette mirrored from frontend/src/components/reportStyle.ts
export const VERDICT_COLOR = {
  good: "#6fcf8e",
  warning: "#e0a44a",
  critical: "#f38764",
  neutral: "#b3b1a8",
} as const;

// 120-hour total-load curve in MW from scenario load_profile.hours[].total_load_mw
export const LOAD_CURVE_MW: number[] = [
  1459, 1573.3, 1575.8, 1581, 1605.5, 1659.1, 1597.8, 1707.9, 1745.4, 1634.3,
  1608, 1610.9, 1634.9, 1647.4, 1659.9, 1686.9, 1749.6, 1834.8, 2355.8, 2384.6,
  2367.5, 2335.8, 2279.9, 2226.5, 2005.4, 1981.1, 1966.6, 1956.9, 1966.6, 2005.4,
  1893.2, 1990, 1920.2, 1784.4, 1745.7, 1736, 1745.7, 1745.7, 1745.7, 1760.2,
  1897.7, 1970.3, 2517.5, 2527.2, 2493.3, 2444.9, 2372.3, 2299.7, 2005.4, 1981.1,
  1966.6, 1956.9, 1966.6, 2005.4, 1893.2, 1990, 1920.2, 1784.4, 1745.7, 1736,
  1745.7, 1745.7, 1745.7, 1760.2, 1897.7, 1970.3, 2517.5, 2527.2, 2493.3, 2444.9,
  2372.3, 2299.7, 2005.4, 1981.1, 1966.6, 1956.9, 1966.6, 2005.4, 1893.2, 1990,
  1920.2, 1784.4, 1745.7, 1736, 1745.7, 1745.7, 1745.7, 1760.2, 1897.7, 1970.3,
  2517.5, 2527.2, 2493.3, 2444.9, 2372.3, 2299.7, 1962.3, 1911, 1879.4, 1850.7,
  1843.3, 1863, 1749.7, 1829.5, 1838.5, 1691.5, 1638.4, 1612.7, 1606.3, 1591.9,
  1575.9, 1576.1, 1608.4, 1666.7, 2092.6, 2083.2, 2027.8, 1831, 1726.8, 1628.3,
];

// 120-hour temperature curve in °C from cold_event.hourly_curve[].temp_c
export const TEMP_CURVE_C: number[] = [
  -8, -8.7, -9.5, -10.2, -10.9, -11.6, -12.4, -13.1, -13.8, -14.6,
  -15.3, -16, -16.8, -17.5, -18.2, -18.9, -19.7, -20.4, -21.1, -21.9,
  -22.6, -23.3, -24, -24.8, -28, -28, -28, -28, -28, -28,
  -28, -28, -23, -23, -23, -23, -23, -23, -23, -23,
  -28, -28, -28, -28, -28, -28, -28, -28, -28, -28,
  -28, -28, -28, -28, -28, -28, -23, -23, -23, -23,
  -23, -23, -23, -23, -28, -28, -28, -28, -28, -28,
  -28, -28, -28, -28, -28, -28, -28, -28, -28, -28,
  -23, -23, -23, -23, -23, -23, -23, -23, -28, -28,
  -28, -28, -28, -28, -28, -28, -25.5, -24.6, -23.8, -22.9,
  -22.1, -21.2, -20.4, -19.5, -18.7, -17.8, -17, -16.1, -15.2, -14.4,
  -13.5, -12.7, -11.8, -11, -10.1, -9.3, -8.4, -7.6, -6.7, -5.9,
];
