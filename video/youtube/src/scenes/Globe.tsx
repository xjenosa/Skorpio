import { useCurrentFrame } from "remotion";

// SVG port of frontend/src/components/GlobeCanvas.tsx — deterministic,
// frame-driven, no requestAnimationFrame or pointer interaction. Same
// projection, same palette, same 42-capital network with 5-NN base
// links + long-haul pulses.

type City = [string, number, number];

const PALETTE = {
  r: 243,
  g: 135,
  b: 100,
  hot: [255, 200, 170] as const,
  body: ["#2d2c2a", "#232220", "#1a1918"] as const,
  ringAlpha: 0.08,
};

const aRgba = (a: number) =>
  `rgba(${PALETTE.r},${PALETTE.g},${PALETTE.b},${a})`;
const hotRgba = (a: number) =>
  `rgba(${PALETTE.hot[0]},${PALETTE.hot[1]},${PALETTE.hot[2]},${a})`;

const CAPITALS: City[] = [
  ["Washington", 38.9072, -77.0369],
  ["Ottawa", 45.4215, -75.6972],
  ["Mexico City", 19.4326, -99.1332],
  ["Brasília", -15.7975, -47.8919],
  ["Buenos Aires", -34.6037, -58.3816],
  ["Lima", -12.0464, -77.0428],
  ["Bogotá", 4.711, -74.0721],
  ["Santiago", -33.4489, -70.6693],
  ["Reykjavík", 64.1466, -21.9426],
  ["London", 51.5074, -0.1278],
  ["Dublin", 53.3498, -6.2603],
  ["Paris", 48.8566, 2.3522],
  ["Madrid", 40.4168, -3.7038],
  ["Lisbon", 38.7223, -9.1393],
  ["Berlin", 52.52, 13.405],
  ["Rome", 41.9028, 12.4964],
  ["Vienna", 48.2082, 16.3738],
  ["Warsaw", 52.2297, 21.0122],
  ["Stockholm", 59.3293, 18.0686],
  ["Oslo", 59.9139, 10.7522],
  ["Helsinki", 60.1699, 24.9384],
  ["Moscow", 55.7558, 37.6173],
  ["Athens", 37.9838, 23.7275],
  ["Ankara", 39.9334, 32.8597],
  ["Cairo", 30.0444, 31.2357],
  ["Riyadh", 24.7136, 46.6753],
  ["Tehran", 35.6892, 51.389],
  ["Nairobi", -1.2921, 36.8219],
  ["Pretoria", -25.7479, 28.2293],
  ["Lagos", 6.5244, 3.3792],
  ["Addis Ababa", 9.03, 38.74],
  ["New Delhi", 28.6139, 77.209],
  ["Islamabad", 33.6844, 73.0479],
  ["Beijing", 39.9042, 116.4074],
  ["Tokyo", 35.6762, 139.6503],
  ["Seoul", 37.5665, 126.978],
  ["Bangkok", 13.7563, 100.5018],
  ["Hanoi", 21.0285, 105.8542],
  ["Jakarta", -6.2088, 106.8456],
  ["Manila", 14.5995, 120.9842],
  ["Canberra", -35.2809, 149.13],
  ["Wellington", -41.2865, 174.7762],
];

const LONG_HAUL: Array<[string, string]> = [
  ["Washington", "London"],
  ["London", "Tokyo"],
  ["Washington", "Tokyo"],
  ["Paris", "New Delhi"],
  ["Beijing", "Moscow"],
  ["London", "New Delhi"],
  ["Cairo", "Paris"],
  ["Seoul", "Washington"],
  ["Berlin", "Beijing"],
  ["Brasília", "Lisbon"],
  ["Buenos Aires", "Madrid"],
  ["Jakarta", "Tokyo"],
  ["Lagos", "London"],
  ["Pretoria", "Paris"],
  ["Mexico City", "Madrid"],
  ["Canberra", "Tokyo"],
  ["New Delhi", "Beijing"],
];

// ── Build link list (module-level, deterministic) ─────────────────────
type Link = { a: number; b: number; longHaul?: boolean };
const LINKS: Link[] = (() => {
  const ls: Link[] = [];
  const has = (i: number, j: number) => {
    const lo = Math.min(i, j);
    const hi = Math.max(i, j);
    return ls.some((l) => Math.min(l.a, l.b) === lo && Math.max(l.a, l.b) === hi);
  };
  const deg = (a: City, b: City) => {
    const dlat = a[1] - b[1];
    const dlon = a[2] - b[2];
    return Math.sqrt(dlat * dlat + dlon * dlon);
  };
  const k = 5;
  for (let i = 0; i < CAPITALS.length; i++) {
    const dists: Array<[number, number]> = [];
    for (let j = 0; j < CAPITALS.length; j++) {
      if (i === j) continue;
      dists.push([j, deg(CAPITALS[i], CAPITALS[j])]);
    }
    dists.sort((p, q) => p[1] - q[1]);
    for (let n = 0; n < k && n < dists.length; n++) {
      const j = dists[n][0];
      if (!has(i, j)) ls.push({ a: i, b: j });
    }
  }
  const nameIdx = (n: string) => CAPITALS.findIndex((c) => c[0] === n);
  LONG_HAUL.forEach(([a, b]) => {
    const i = nameIdx(a);
    const j = nameIdx(b);
    if (i < 0 || j < 0) return;
    if (!has(i, j)) ls.push({ a: i, b: j, longHaul: true });
  });
  return ls;
})();

// Per-capital "heat" value used to pick which dots glow ember.
const HEAT: number[] = CAPITALS.map((c) => {
  let h = 0;
  for (const ch of c[0]) h = (h * 31 + ch.charCodeAt(0)) % 1000;
  return (h % 1000) / 1000;
});

// Per-arc deterministic pulse offset + speed (matches the canvas version's
// `Math.random` initialization, but stable across frames).
const PULSE_OFFSETS = LINKS.map((_, i) => ((i * 73) % 100) / 100);
const PULSE_SPEEDS = LINKS.map(
  (_, i) => 0.0015 * 2 + ((i * 37) % 100) * 0.000025,
);

// ── Math helpers ──────────────────────────────────────────────────────
const slerp = (
  latA: number,
  lonA: number,
  latB: number,
  lonB: number,
  t: number,
): [number, number] => {
  const phi1 = (latA * Math.PI) / 180;
  const lam1 = (lonA * Math.PI) / 180;
  const phi2 = (latB * Math.PI) / 180;
  const lam2 = (lonB * Math.PI) / 180;
  const x1 = Math.cos(phi1) * Math.cos(lam1);
  const y1 = Math.cos(phi1) * Math.sin(lam1);
  const z1 = Math.sin(phi1);
  const x2 = Math.cos(phi2) * Math.cos(lam2);
  const y2 = Math.cos(phi2) * Math.sin(lam2);
  const z2 = Math.sin(phi2);
  const dot = Math.max(-1, Math.min(1, x1 * x2 + y1 * y2 + z1 * z2));
  const omega = Math.acos(dot);
  if (omega < 1e-6) return [latA, lonA];
  const so = Math.sin(omega);
  const a = Math.sin((1 - t) * omega) / so;
  const b = Math.sin(t * omega) / so;
  const x = a * x1 + b * x2;
  const y = a * y1 + b * y2;
  const z = a * z1 + b * z2;
  return [
    (Math.atan2(z, Math.sqrt(x * x + y * y)) * 180) / Math.PI,
    (Math.atan2(y, x) * 180) / Math.PI,
  ];
};

export const Globe: React.FC<{
  size: number;
  rotateSpeedPerFrame?: number;
}> = ({ size, rotateSpeedPerFrame = 0.0028 }) => {
  const frame = useCurrentFrame();
  const yaw = 0.7 + frame * rotateSpeedPerFrame;
  const pitch = 0.32;
  const cp = Math.cos(pitch);
  const sp = Math.sin(pitch);

  const CX = size / 2;
  const CY = size / 2;
  const R = size * 0.4;

  const project = (lat: number, lon: number) => {
    const phi = (lat * Math.PI) / 180;
    const theta = (lon * Math.PI) / 180 + yaw;
    const x = Math.cos(phi) * Math.cos(theta);
    const y = Math.sin(phi);
    const z = Math.cos(phi) * Math.sin(theta);
    const y2 = y * cp - z * sp;
    const z2 = y * sp + z * cp;
    return { sx: CX + x * R, sy: CY - y2 * R, depth: z2 };
  };

  // ── Graticule ───────────────────────────────────────────────
  const grats: string[] = [];
  for (let lat = -60; lat <= 60; lat += 30) {
    let d = "";
    let started = false;
    for (let lon = -180; lon <= 180; lon += 4) {
      const p = project(lat, lon);
      if (p.depth > -0.02) {
        d += `${started ? "L" : "M"}${p.sx.toFixed(2)} ${p.sy.toFixed(2)} `;
        started = true;
      } else started = false;
    }
    if (d) grats.push(d);
  }
  for (let lon = -180; lon < 180; lon += 30) {
    let d = "";
    let started = false;
    for (let lat = -90; lat <= 90; lat += 4) {
      const p = project(lat, lon);
      if (p.depth > -0.02) {
        d += `${started ? "L" : "M"}${p.sx.toFixed(2)} ${p.sy.toFixed(2)} `;
        started = true;
      } else started = false;
    }
    if (d) grats.push(d);
  }

  // ── Arcs (project once, reused for pulse positions) ─────────
  const segs = 36;
  const arcPaths: Array<{
    pts: ReturnType<typeof project>[];
    d: string;
    longHaul: boolean;
    avgDepth: number;
  }> = LINKS.map((l) => {
    const a = CAPITALS[l.a];
    const b = CAPITALS[l.b];
    const pts: ReturnType<typeof project>[] = [];
    for (let s = 0; s <= segs; s++) {
      const [lat, lon] = slerp(a[1], a[2], b[1], b[2], s / segs);
      pts.push(project(lat, lon));
    }
    let d = "";
    let started = false;
    for (const p of pts) {
      if (p.depth > -0.05) {
        d += `${started ? "L" : "M"}${p.sx.toFixed(2)} ${p.sy.toFixed(2)} `;
        started = true;
      } else started = false;
    }
    const mid = pts[Math.floor(pts.length / 2)];
    return {
      pts,
      d,
      longHaul: !!l.longHaul,
      avgDepth: mid?.depth ?? 0,
    };
  });
  // back-to-front so closer arcs paint on top of farther ones
  const arcOrder = arcPaths
    .map((a, i) => ({ a, i }))
    .sort((p, q) => p.a.avgDepth - q.a.avgDepth);

  // ── Long-haul pulses ────────────────────────────────────────
  const pulses = LINKS.map((l, i) => {
    if (!l.longHaul) return null;
    const t =
      (PULSE_OFFSETS[i] + frame * PULSE_SPEEDS[i]) % 1;
    const seg = Math.floor(t * segs);
    const segT = t * segs - seg;
    const arc = arcPaths[i];
    const pA = arc.pts[Math.min(segs, seg)];
    const pB = arc.pts[Math.min(segs, seg + 1)];
    if (!pA || !pB) return null;
    if (pA.depth < -0.05 || pB.depth < -0.05) return null;
    return {
      px: pA.sx + (pB.sx - pA.sx) * segT,
      py: pA.sy + (pB.sy - pA.sy) * segT,
    };
  });

  // ── Nodes ───────────────────────────────────────────────────
  const projected = CAPITALS.map((c, i) => ({
    p: project(c[1], c[2]),
    i,
    name: c[0],
  }));

  const ringR = R * 1.18;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      style={{ display: "block" }}
    >
      <defs>
        <radialGradient id="globe-ring" cx="50%" cy="50%" r="50%">
          <stop offset={`${(R / ringR) * 100 * 0.92}%`} stopColor={aRgba(0)} />
          <stop offset={`${(R / ringR) * 100}%`} stopColor={aRgba(PALETTE.ringAlpha)} />
          <stop offset="100%" stopColor={aRgba(0)} />
        </radialGradient>
        <radialGradient id="globe-body" cx="32%" cy="32%" r="65%">
          <stop offset="0%" stopColor={PALETTE.body[0]} />
          <stop offset="60%" stopColor={PALETTE.body[1]} />
          <stop offset="100%" stopColor={PALETTE.body[2]} />
        </radialGradient>
      </defs>

      {/* outer ember halo */}
      <circle cx={CX} cy={CY} r={ringR} fill="url(#globe-ring)" />

      {/* sphere body */}
      <circle
        cx={CX}
        cy={CY}
        r={R}
        fill="url(#globe-body)"
        stroke="rgba(250,249,245,0.10)"
        strokeWidth={1}
      />

      {/* graticule */}
      <g
        stroke="rgba(250,249,245,0.045)"
        strokeWidth={1}
        fill="none"
        strokeLinejoin="round"
        strokeLinecap="round"
      >
        {grats.map((d, i) => (
          <path key={`g${i}`} d={d} />
        ))}
      </g>

      {/* arcs */}
      <g fill="none" strokeLinecap="round" strokeLinejoin="round">
        {arcOrder.map(({ a, i }) => (
          <path
            key={`a${i}`}
            d={a.d}
            stroke={aRgba(a.longHaul ? 0.22 : 0.12)}
            strokeWidth={a.longHaul ? 1.1 : 0.8}
          />
        ))}
      </g>

      {/* long-haul pulse glows */}
      {pulses.map((pl, i) =>
        pl ? (
          <g key={`p${i}`}>
            <circle cx={pl.px} cy={pl.py} r={14} fill={aRgba(0.32)} />
            <circle cx={pl.px} cy={pl.py} r={6} fill={aRgba(0.55)} />
            <circle cx={pl.px} cy={pl.py} r={1.6} fill={hotRgba(1)} />
          </g>
        ) : null,
      )}

      {/* nodes */}
      {projected.map(({ p, i }) => {
        if (p.depth < -0.05) return null;
        const front = (p.depth + 1) / 2;
        const inten = HEAT[i];
        const isHot = inten > 0.55;
        const r = (isHot ? 2.4 : 1.8) * (0.6 + front * 0.6);
        return (
          <g key={`n${i}`}>
            {isHot ? (
              <circle
                cx={p.sx}
                cy={p.sy}
                r={9}
                fill={aRgba(0.45 * front)}
              />
            ) : null}
            <circle
              cx={p.sx}
              cy={p.sy}
              r={r}
              fill={
                isHot
                  ? hotRgba(0.85 * front + 0.15)
                  : `rgba(250,249,245,${0.55 * front + 0.2})`
              }
            />
          </g>
        );
      })}
    </svg>
  );
};
