import { useEffect, useRef } from 'react'

// Ported from uiux/login.html — interactive 2D-canvas globe with capital
// cities and glowing arcs. Self-contained: rotates on idle, drag to spin,
// hover for a city tooltip. Palette is hardcoded to "ember" and density to
// "standard" (the original tweaks panel is not ported).
//
// Tuple: [name, lat, lon]
type City = [string, number, number]

const PALETTE = {
  r: 243,
  g: 135,
  b: 100,
  hot: [255, 200, 170] as const,
  body: ['#2d2c2a', '#232220', '#1a1918'] as const,
  glowAlpha: 0.85,
  ringAlpha: 0.08,
}

const CAPITALS: City[] = [
  ['Washington', 38.9072, -77.0369],
  ['Ottawa', 45.4215, -75.6972],
  ['Mexico City', 19.4326, -99.1332],
  ['Brasília', -15.7975, -47.8919],
  ['Buenos Aires', -34.6037, -58.3816],
  ['Lima', -12.0464, -77.0428],
  ['Bogotá', 4.711, -74.0721],
  ['Santiago', -33.4489, -70.6693],
  ['Reykjavík', 64.1466, -21.9426],
  ['London', 51.5074, -0.1278],
  ['Dublin', 53.3498, -6.2603],
  ['Paris', 48.8566, 2.3522],
  ['Madrid', 40.4168, -3.7038],
  ['Lisbon', 38.7223, -9.1393],
  ['Berlin', 52.52, 13.405],
  ['Rome', 41.9028, 12.4964],
  ['Vienna', 48.2082, 16.3738],
  ['Warsaw', 52.2297, 21.0122],
  ['Stockholm', 59.3293, 18.0686],
  ['Oslo', 59.9139, 10.7522],
  ['Helsinki', 60.1699, 24.9384],
  ['Moscow', 55.7558, 37.6173],
  ['Athens', 37.9838, 23.7275],
  ['Ankara', 39.9334, 32.8597],
  ['Cairo', 30.0444, 31.2357],
  ['Riyadh', 24.7136, 46.6753],
  ['Tehran', 35.6892, 51.389],
  ['Nairobi', -1.2921, 36.8219],
  ['Pretoria', -25.7479, 28.2293],
  ['Lagos', 6.5244, 3.3792],
  ['Addis Ababa', 9.03, 38.74],
  ['New Delhi', 28.6139, 77.209],
  ['Islamabad', 33.6844, 73.0479],
  ['Beijing', 39.9042, 116.4074],
  ['Tokyo', 35.6762, 139.6503],
  ['Seoul', 37.5665, 126.978],
  ['Bangkok', 13.7563, 100.5018],
  ['Hanoi', 21.0285, 105.8542],
  ['Jakarta', -6.2088, 106.8456],
  ['Manila', 14.5995, 120.9842],
  ['Canberra', -35.2809, 149.13],
  ['Wellington', -41.2865, 174.7762],
]

const LONG_HAUL: Array<[string, string]> = [
  ['Washington', 'London'],
  ['London', 'Tokyo'],
  ['Washington', 'Tokyo'],
  ['Paris', 'New Delhi'],
  ['Beijing', 'Moscow'],
  ['London', 'New Delhi'],
  ['Cairo', 'Paris'],
  ['Seoul', 'Washington'],
  ['Berlin', 'Beijing'],
  ['Brasília', 'Lisbon'],
  ['Buenos Aires', 'Madrid'],
  ['Jakarta', 'Tokyo'],
  ['Lagos', 'London'],
  ['Pretoria', 'Paris'],
  ['Mexico City', 'Madrid'],
  ['Canberra', 'Tokyo'],
  ['New Delhi', 'Beijing'],
]

const aRgba = (a: number) => `rgba(${PALETTE.r},${PALETTE.g},${PALETTE.b},${a})`
const hotRgba = (a: number) => `rgba(${PALETTE.hot[0]},${PALETTE.hot[1]},${PALETTE.hot[2]},${a})`

export function GlobeCanvas() {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const tipRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    const tip = tipRef.current
    if (!canvas || !wrap || !tip) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // ── Build link network (k-nearest + long-haul) ──────────────
    type Link = { a: number; b: number; weight: number; longHaul?: boolean }
    const deg = (a: City, b: City) => {
      const dlat = a[1] - b[1]
      const dlon = a[2] - b[2]
      return Math.sqrt(dlat * dlat + dlon * dlon)
    }
    const links: Link[] = []
    // density = "dense": 5 nearest neighbours + the full long-haul list below.
    const k = 5
    for (let i = 0; i < CAPITALS.length; i++) {
      const dists: Array<[number, number]> = []
      for (let j = 0; j < CAPITALS.length; j++) {
        if (i === j) continue
        dists.push([j, deg(CAPITALS[i], CAPITALS[j])])
      }
      dists.sort((p, q) => p[1] - q[1])
      for (let n = 0; n < k && n < dists.length; n++) {
        const j = dists[n][0]
        const key = i < j ? `${i}-${j}` : `${j}-${i}`
        if (!links.some((l) => `${Math.min(l.a, l.b)}-${Math.max(l.a, l.b)}` === key)) {
          links.push({ a: i, b: j, weight: 1 - n * 0.2 })
        }
      }
    }
    const nameIdx = (n: string) => CAPITALS.findIndex((c) => c[0] === n)
    LONG_HAUL.forEach(([a, b]) => {
      const i = nameIdx(a)
      const j = nameIdx(b)
      if (i < 0 || j < 0) return
      const key = i < j ? `${i}-${j}` : `${j}-${i}`
      if (!links.some((l) => `${Math.min(l.a, l.b)}-${Math.max(l.a, l.b)}` === key)) {
        links.push({ a: i, b: j, weight: 1, longHaul: true })
      }
    })
    const pulses = links.map(() => ({ t: Math.random(), speed: 0.0015 + Math.random() * 0.0025 }))

    // ── Sizing / DPR ────────────────────────────────────────────
    let W = 0
    let H = 0
    let R = 0
    let CX = 0
    let CY = 0
    const resize = () => {
      const DPR = Math.min(window.devicePixelRatio || 1, 2)
      const rect = wrap.getBoundingClientRect()
      W = rect.width
      H = rect.height
      canvas.width = Math.floor(W * DPR)
      canvas.height = Math.floor(H * DPR)
      canvas.style.width = `${W}px`
      canvas.style.height = `${H}px`
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0)
      CX = W / 2
      CY = H / 2
      R = Math.min(W, H) * 0.4
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(wrap)

    // ── Rotation state ──────────────────────────────────────────
    let yaw = 0.7
    let pitch = 0.32
    let yawTarget = yaw
    let pitchTarget = pitch
    let dragging = false
    let lastX = 0
    let lastY = 0
    let lastInteract = 0
    let hoverIdx = -1

    const onPointerDown = (e: PointerEvent) => {
      dragging = true
      canvas.setPointerCapture(e.pointerId)
      lastX = e.clientX
      lastY = e.clientY
      lastInteract = performance.now()
      canvas.style.cursor = 'grabbing'
    }
    const onPointerMove = (e: PointerEvent) => {
      if (dragging) {
        const dx = e.clientX - lastX
        const dy = e.clientY - lastY
        lastX = e.clientX
        lastY = e.clientY
        // Yaw inverted so horizontal drag follows the cursor; vertical kept
        // in the original direction (drag down tilts the globe down).
        yawTarget -= dx * 0.005
        pitchTarget = Math.max(-1.1, Math.min(1.1, pitchTarget + dy * 0.005))
        lastInteract = performance.now()
      }
      handleHover(e)
    }
    const onPointerUp = () => {
      dragging = false
      canvas.style.cursor = 'grab'
    }
    const onPointerLeave = () => {
      dragging = false
      tip.classList.remove('show')
    }
    canvas.addEventListener('pointerdown', onPointerDown)
    canvas.addEventListener('pointermove', onPointerMove)
    canvas.addEventListener('pointerup', onPointerUp)
    canvas.addEventListener('pointerleave', onPointerLeave)
    canvas.style.cursor = 'grab'

    // ── Math helpers ────────────────────────────────────────────
    const project = (lat: number, lon: number) => {
      const phi = (lat * Math.PI) / 180
      const theta = (lon * Math.PI) / 180 + yaw
      const x = Math.cos(phi) * Math.cos(theta)
      const y = Math.sin(phi)
      const z = Math.cos(phi) * Math.sin(theta)
      const cp = Math.cos(pitch)
      const sp = Math.sin(pitch)
      const y2 = y * cp - z * sp
      const z2 = y * sp + z * cp
      return { sx: CX + x * R, sy: CY - y2 * R, depth: z2 }
    }
    const slerp = (
      latA: number,
      lonA: number,
      latB: number,
      lonB: number,
      t: number,
    ): [number, number] => {
      const phi1 = (latA * Math.PI) / 180
      const lam1 = (lonA * Math.PI) / 180
      const phi2 = (latB * Math.PI) / 180
      const lam2 = (lonB * Math.PI) / 180
      const x1 = Math.cos(phi1) * Math.cos(lam1)
      const y1 = Math.cos(phi1) * Math.sin(lam1)
      const z1 = Math.sin(phi1)
      const x2 = Math.cos(phi2) * Math.cos(lam2)
      const y2 = Math.cos(phi2) * Math.sin(lam2)
      const z2 = Math.sin(phi2)
      const dot = Math.max(-1, Math.min(1, x1 * x2 + y1 * y2 + z1 * z2))
      const omega = Math.acos(dot)
      if (omega < 1e-6) return [latA, lonA]
      const so = Math.sin(omega)
      const a = Math.sin((1 - t) * omega) / so
      const b = Math.sin(t * omega) / so
      const x = a * x1 + b * x2
      const y = a * y1 + b * y2
      const z = a * z1 + b * z2
      return [
        (Math.atan2(z, Math.sqrt(x * x + y * y)) * 180) / Math.PI,
        (Math.atan2(y, x) * 180) / Math.PI,
      ]
    }
    const intensity = (idx: number) => {
      const c = CAPITALS[idx]
      let h = 0
      for (const ch of c[0]) h = (h * 31 + ch.charCodeAt(0)) % 1000
      return (h % 1000) / 1000
    }

    // ── Hover handling ──────────────────────────────────────────
    const handleHover = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect()
      const mx = e.clientX - rect.left
      const my = e.clientY - rect.top
      let best = -1
      let bestD = 12 * 12
      for (let i = 0; i < CAPITALS.length; i++) {
        const c = CAPITALS[i]
        const p = project(c[1], c[2])
        if (p.depth < -0.05) continue
        const dx = p.sx - mx
        const dy = p.sy - my
        const d2 = dx * dx + dy * dy
        if (d2 < bestD) {
          bestD = d2
          best = i
        }
      }
      hoverIdx = best
      if (best >= 0) {
        const c = CAPITALS[best]
        const p = project(c[1], c[2])
        tip.style.left = `${p.sx}px`
        tip.style.top = `${p.sy}px`
        let h = 0
        for (const ch of c[0]) h = (h * 31 + ch.charCodeAt(0)) % 1000
        const co2 = 80 + (h % 480)
        const mw = (8 + (h % 60)).toFixed(1)
        tip.innerHTML =
          `<div class="row"><span class="city">${c[0]}</span></div>` +
          `<div class="row"><span class="meta">${co2} gCO₂ · ${mw} MW</span></div>`
        tip.classList.add('show')
      } else {
        tip.classList.remove('show')
      }
    }

    // ── Render passes ───────────────────────────────────────────
    const drawSphereBg = () => {
      const grd = ctx.createRadialGradient(CX, CY, R * 0.85, CX, CY, R * 1.18)
      grd.addColorStop(0, aRgba(PALETTE.ringAlpha))
      grd.addColorStop(1, aRgba(0))
      ctx.fillStyle = grd
      ctx.beginPath()
      ctx.arc(CX, CY, R * 1.18, 0, Math.PI * 2)
      ctx.fill()

      const body = ctx.createRadialGradient(CX - R * 0.35, CY - R * 0.35, R * 0.05, CX, CY, R)
      body.addColorStop(0, PALETTE.body[0])
      body.addColorStop(0.6, PALETTE.body[1])
      body.addColorStop(1, PALETTE.body[2])
      ctx.fillStyle = body
      ctx.beginPath()
      ctx.arc(CX, CY, R, 0, Math.PI * 2)
      ctx.fill()

      ctx.strokeStyle = 'rgba(250,249,245,0.10)'
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.arc(CX, CY, R, 0, Math.PI * 2)
      ctx.stroke()
    }

    const drawGraticule = () => {
      ctx.strokeStyle = 'rgba(250,249,245,0.045)'
      ctx.lineWidth = 1
      for (let lat = -60; lat <= 60; lat += 30) {
        ctx.beginPath()
        let started = false
        for (let lon = -180; lon <= 180; lon += 4) {
          const p = project(lat, lon)
          if (p.depth > -0.02) {
            if (!started) {
              ctx.moveTo(p.sx, p.sy)
              started = true
            } else ctx.lineTo(p.sx, p.sy)
          } else started = false
        }
        ctx.stroke()
      }
      for (let lon = -180; lon < 180; lon += 30) {
        ctx.beginPath()
        let started = false
        for (let lat = -90; lat <= 90; lat += 4) {
          const p = project(lat, lon)
          if (p.depth > -0.02) {
            if (!started) {
              ctx.moveTo(p.sx, p.sy)
              started = true
            } else ctx.lineTo(p.sx, p.sy)
          } else started = false
        }
        ctx.stroke()
      }
    }

    const drawArc = (a: City, b: City, alphaScale: number, glow: boolean, t = 1) => {
      const segs = 36
      const pts: ReturnType<typeof project>[] = []
      for (let s = 0; s <= segs; s++) {
        const [lat, lon] = slerp(a[1], a[2], b[1], b[2], s / segs)
        pts.push(project(lat, lon))
      }
      if (!pts.some((p) => p.depth > -0.05)) return
      ctx.beginPath()
      let started = false
      for (const p of pts) {
        const visible = p.depth > -0.05
        if (!visible) {
          started = false
          continue
        }
        if (!started) {
          ctx.moveTo(p.sx, p.sy)
          started = true
        } else ctx.lineTo(p.sx, p.sy)
      }
      ctx.strokeStyle = aRgba(0.12 * alphaScale)
      ctx.lineWidth = 1
      ctx.stroke()

      if (glow) {
        const seg = Math.floor(t * segs)
        const segT = t * segs - seg
        const pA = pts[Math.max(0, Math.min(segs, seg))]
        const pB = pts[Math.max(0, Math.min(segs, seg + 1))]
        if (pA && pB && pA.depth > -0.05 && pB.depth > -0.05) {
          const px = pA.sx + (pB.sx - pA.sx) * segT
          const py = pA.sy + (pB.sy - pA.sy) * segT
          const grd = ctx.createRadialGradient(px, py, 0, px, py, 14)
          grd.addColorStop(0, aRgba(PALETTE.glowAlpha))
          grd.addColorStop(1, aRgba(0))
          ctx.fillStyle = grd
          ctx.beginPath()
          ctx.arc(px, py, 14, 0, Math.PI * 2)
          ctx.fill()
          ctx.fillStyle = hotRgba(1)
          ctx.beginPath()
          ctx.arc(px, py, 1.6, 0, Math.PI * 2)
          ctx.fill()
        }
      }
    }

    const drawNodes = () => {
      for (let i = 0; i < CAPITALS.length; i++) {
        const c = CAPITALS[i]
        const p = project(c[1], c[2])
        if (p.depth < -0.05) continue
        const front = (p.depth + 1) / 2
        const inten = intensity(i)
        const isHot = inten > 0.55
        const r = (isHot ? 2.4 : 1.8) * (0.6 + front * 0.6)
        if (isHot) {
          const grd = ctx.createRadialGradient(p.sx, p.sy, 0, p.sx, p.sy, 9)
          grd.addColorStop(0, aRgba(0.55 * front))
          grd.addColorStop(1, aRgba(0))
          ctx.fillStyle = grd
          ctx.beginPath()
          ctx.arc(p.sx, p.sy, 9, 0, Math.PI * 2)
          ctx.fill()
        }
        ctx.fillStyle = isHot
          ? hotRgba(0.85 * front + 0.15)
          : `rgba(250,249,245,${0.55 * front + 0.2})`
        ctx.beginPath()
        ctx.arc(p.sx, p.sy, r, 0, Math.PI * 2)
        ctx.fill()
        if (i === hoverIdx) {
          ctx.strokeStyle = aRgba(0.85)
          ctx.lineWidth = 1
          ctx.beginPath()
          ctx.arc(p.sx, p.sy, r + 4, 0, Math.PI * 2)
          ctx.stroke()
        }
      }
    }

    // ── Animation loop ──────────────────────────────────────────
    let raf = 0
    const tick = (now: number) => {
      const idle = now - lastInteract > 1500
      if (idle && !dragging) yawTarget += 0.0012
      yaw += (yawTarget - yaw) * 0.1
      pitch += (pitchTarget - pitch) * 0.1

      ctx.clearRect(0, 0, W, H)
      drawSphereBg()
      drawGraticule()

      const sortedLinks = links
        .map((l, idx) => {
          const a = CAPITALS[l.a]
          const b = CAPITALS[l.b]
          const [mlat, mlon] = slerp(a[1], a[2], b[1], b[2], 0.5)
          const m = project(mlat, mlon)
          return { l, idx, depth: m.depth }
        })
        .sort((p, q) => p.depth - q.depth)
      for (const { l, idx } of sortedLinks) {
        const a = CAPITALS[l.a]
        const b = CAPITALS[l.b]
        const alpha = l.longHaul ? 1.0 : 0.7
        const pulse = pulses[idx]
        pulse.t += pulse.speed
        if (pulse.t > 1) pulse.t -= 1
        drawArc(a, b, alpha, !!l.longHaul, pulse.t)
      }
      drawNodes()

      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      canvas.removeEventListener('pointerdown', onPointerDown)
      canvas.removeEventListener('pointermove', onPointerMove)
      canvas.removeEventListener('pointerup', onPointerUp)
      canvas.removeEventListener('pointerleave', onPointerLeave)
    }
  }, [])

  return (
    <div ref={wrapRef} className="globe-wrap">
      <canvas ref={canvasRef} className="globe-canvas" />
      <div ref={tipRef} className="tip" role="tooltip" />
    </div>
  )
}
