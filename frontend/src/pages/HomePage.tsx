import { FormEvent, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError, clearToken, type MeResponse } from '../api/client'
import { PipelineLive } from '../components/PipelineLive'
import { isTourSampleSuppressed, markTourSampleSuppressed, markUserHasRunPipeline } from '../components/GuidedTour'
import { WinterPeakReport } from '../components/WinterPeakReport'
import { ElectrificationReport } from '../components/ElectrificationReport'
import { InvestmentReport } from '../components/InvestmentReport'
import { ExpansionReport } from '../components/ExpansionReport'
import { PipelineTagPicker } from '../components/PipelineTagPicker'
import { SmoothStage } from '../components/SmoothStage'
import type {
  ClaudeModel,
  ImportConflict,
  ImportResult,
  ImportStrategy,
  JobListItem,
  PipelineStage,
} from '../api/types'
import {
  PIPELINES,
  pipelineById,
  randomExample,
  type PipelineId,
} from '../pipelines'
import {
  useDemoMode,
  useFixturePlayed,
  markFixturePlayed,
  isFixturePlayed,
  markFixtureSubmitted,
  isFixtureSubmitted,
  unmarkFixtureSubmitted,
  unmarkFixturePlayed,
  useDemoFixtureTick,
  isDemoModeActive,
} from '../hooks/useDemoMode'
import { DEMO_PROMPTS } from '../demo/prompts'
import { getDemoJobId, resolveDemoJobIds, isDemoJobId, pipelineForDemoJobId } from '../demo/jobs'
import { buildDemoMetrics } from '../demo/metrics'
import { startTheater, subscribeAnyTheater, getTheaterState, stopTheater } from '../demo/theaterManager'
// Sample-run fixture used as the Agent Pipeline tab's empty-state landing
// view (no past runs yet, in any mode). Picked because winter-peak has the
// richest stage data and most visualizations of the 5 fixtures.
import sampleRunFixture from '../demo/fixtures/476a2f1a.json'

const USER_EMAIL_KEY = 'skorpio.user.email'

function loadUserEmail(): string {
  if (typeof window === 'undefined') return 'me@skorpio.local'
  return window.localStorage.getItem(USER_EMAIL_KEY) || 'me@skorpio.local'
}

// Reports sort options.
type SortKey = 'newest' | 'oldest' | 'pipeline' | 'progress' | 'stage'
const SORT_LABELS: Record<SortKey, string> = {
  newest: 'Newest first',
  oldest: 'Oldest first',
  pipeline: 'By pipeline',
  progress: 'By progress',
  stage: 'By stage',
}

// Dashboard timeframe options. Used as a label + scaling factor on the
// random-walk amplitudes so a wider window visibly damps the noise.
type Timeframe = '24h' | '7d' | '30d'
const TIMEFRAME_LABELS: Record<Timeframe, string> = {
  '24h': 'Last 24h',
  '7d': 'Last 7 days',
  '30d': 'Last 30 days',
}

const MODEL_OPTIONS: Array<{ id: ClaudeModel; label: string; sub: string }> = [
  { id: 'claude-sonnet-4-6', label: 'Sonnet 4.6', sub: 'Balanced · default' },
  { id: 'claude-opus-4-7', label: 'Opus 4.7', sub: 'Highest reasoning · slower' },
  { id: 'claude-haiku-4-5-20251001', label: 'Haiku 4.5', sub: 'Fastest · cheapest' },
]
const DEFAULT_MODEL: ClaudeModel = 'claude-sonnet-4-6'
const MODEL_STORAGE_KEY = 'skorpio.model'

function loadStoredModel(): ClaudeModel {
  if (typeof window === 'undefined') return DEFAULT_MODEL
  const stored = window.localStorage.getItem(MODEL_STORAGE_KEY)
  if (stored && MODEL_OPTIONS.some((m) => m.id === stored)) {
    return stored as ClaudeModel
  }
  return DEFAULT_MODEL
}

type Route = 'new-session' | 'agent-pipeline' | 'reports' | 'dashboard' | 'settings'

const ROUTE_LABELS: Record<Route, string> = {
  'new-session': 'New session',
  'agent-pipeline': 'Agent pipeline',
  reports: 'Reports',
  dashboard: 'Dashboard',
  settings: 'Settings',
}

const TERMINAL_STAGES = new Set(['completed', 'failed'])

// Stub router: keyword-based pipeline inference until the backend router lands.
// Used only when the user types a fully custom prompt. When they click a
// suggestion chip, we use the chip's pipeline directly.
function inferPipelineFromPrompt(prompt: string): PipelineId {
  const p = prompt.toLowerCase()
  if (/(polar vortex|cold snap|winter peak|stress[- ]?test|cold weather|-\s?\d{2}\s?°?c)/.test(p)) {
    return 'winter-peak-stress'
  }
  if (/(neighborhood|electrification|fsa|postal|heat pump|ev (adoption|growth)|score (the|a) [a-z])/.test(p)) {
    return 'electrification-readiness'
  }
  if (/(invest|budget|allocate|spend|\$\d|grid upgrade)/.test(p)) {
    return 'grid-investment-optimizer'
  }
  if (/(expansion|expand|grow capacity|add capacity|next phase)/.test(p)) {
    return 'datacenter-expansion'
  }
  return 'datacenter-siting'
}

// Helpers — convert between Route values and URL search params so each tab
// has a stable, right-clickable URL. New session is the default and uses
// the bare "/" path; everything else gets ?tab=<id>.
const ALL_ROUTES: Route[] = ['new-session', 'agent-pipeline', 'reports', 'dashboard', 'settings']

function routeHref(r: Route, jobId?: string | null): string {
  if (r === 'new-session') return '/'
  const params = new URLSearchParams({ tab: r })
  if (r === 'agent-pipeline' && jobId) params.set('job', jobId)
  return `/?${params.toString()}`
}

export function HomePage() {
  // Auth gating lives in <AuthGate> at the router level (App.tsx). By the
  // time HomePage renders, the backend has already validated the token via
  // /api/auth/me, so we don't need a fast-path or 401-bounce here.
  const [searchParams, setSearchParams] = useSearchParams()
  const tabParam = searchParams.get('tab') as Route | null
  const route: Route = tabParam && ALL_ROUTES.includes(tabParam) ? tabParam : 'new-session'
  const selectedJobId = searchParams.get('job')

  const [routedPipeline, setRoutedPipeline] = useState<PipelineId>('datacenter-siting')
  const [jobs, setJobs] = useState<JobListItem[] | null>(null)
  const [pendingCompletions, setPendingCompletions] = useState(0)
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem('skorpio.sidebar.collapsed') === '1'
  })
  const prevStages = useRef<Map<string, string>>(new Map())
  const [demoMode] = useDemoMode()
  // When the user explicitly flips non-demo → demo, the Agent Pipeline
  // tab should land on its TRUE empty state (no report displayed), not
  // the Sample run fixture fallback that normally fills the empty slot
  // for first-time visitors. We track this in component state (not
  // localStorage) so it's transient: cleared the moment the user opens
  // a run via openRun (Reports row click, New session submit, etc.).
  // The reverse direction (demo → non-demo) is unchanged.
  const [suppressSampleAfterDemoToggle, setSuppressSampleAfterDemoToggle] = useState(false)
  const prevDemoMode = useRef(demoMode)
  useEffect(() => {
    if (!prevDemoMode.current && demoMode) {
      setSuppressSampleAfterDemoToggle(true)
    }
    prevDemoMode.current = demoMode
  }, [demoMode])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('skorpio.sidebar.collapsed', sidebarCollapsed ? '1' : '0')
  }, [sidebarCollapsed])

  // Auto-clear the sidebar's "completion" pill whenever the user actually
  // lands on the Agent pipeline tab (regardless of how they got there —
  // sidebar Link, "All runs" link, or programmatic openRun).
  useEffect(() => {
    if (route === 'agent-pipeline') setPendingCompletions(0)
  }, [route])

  // Persist the last explicitly-opened job so switching tabs and coming back
  // to Agent pipeline restores it. URL `?job=` is still the source of truth
  // when present; localStorage is the fallback for cross-tab navigation.
  //
  // Demo and live each get their own key so demo opens don't pollute the
  // operator's actual recent work: flipping demo off restores whatever live
  // had last; flipping demo on starts with a clean Agent pipeline slate.
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (selectedJobId) {
      const key = demoMode ? 'skorpio.demo.lastOpenedJob' : 'skorpio.lastOpenedJob'
      window.localStorage.setItem(key, selectedJobId)
    }
  }, [selectedJobId, demoMode])

  // Hydrate the URL with the last-opened jobId when the user navigates to
  // agent-pipeline without one (e.g. clicked the sidebar link instead of a
  // report row). Uses replace so it doesn't add a history entry.
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (route !== 'agent-pipeline' || selectedJobId) return
    const key = demoMode ? 'skorpio.demo.lastOpenedJob' : 'skorpio.lastOpenedJob'
    const last = window.localStorage.getItem(key)
    if (last) {
      setSearchParams({ tab: 'agent-pipeline', job: last }, { replace: true })
    }
  }, [route, selectedJobId, setSearchParams, demoMode])

  // URL `?job=` clearing on demo toggle lives in DemoToggle's onClick so
  // it batches with the demoMode flip in a single render cycle (no useEffect
  // re-fire race with router's unstable setSearchParams identity).

  // Centralized polling so the sidebar pill and all views share the same job list.
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const next = await api.listJobs()
        if (cancelled) return

        // Detect transitions running → completed/failed.
        let newlyFinished = 0
        let lastJustFinished: string | null = null
        for (const job of next) {
          const before = prevStages.current.get(job.job_id)
          if (before && !TERMINAL_STAGES.has(before) && TERMINAL_STAGES.has(job.stage)) {
            const isWatching =
              route === 'agent-pipeline' && selectedJobId === job.job_id
            if (!isWatching) newlyFinished += 1
            // Track the most recently flipped-to-terminal job so we can
            // bump it into Agent Pipeline. Loop order = backend ordering,
            // so the last write wins — typically the newest finish.
            lastJustFinished = job.job_id
          }
          prevStages.current.set(job.job_id, job.stage)
        }
        if (newlyFinished > 0) {
          setPendingCompletions((c) => c + newlyFinished)
        }
        // When a pipeline completes, prefer it as the Agent Pipeline tab's
        // featured run — beats whatever stale report the user last opened.
        // Gated on route !== 'agent-pipeline' so the user isn't yanked off a
        // report they're actively reading; the new value lands the moment
        // they navigate (away and) back to Agent Pipeline (localStorage
        // sync at line 144 mirrors so it survives the round-trip).
        // Skipped in demo mode so a real job finishing in the background
        // doesn't sneak into the demo Agent pipeline tab.
        if (lastJustFinished && route !== 'agent-pipeline' && !demoMode) {
          setSearchParams(
            (prev) => {
              const params = new URLSearchParams(prev)
              params.set('job', lastJustFinished!)
              return params
            },
            { replace: true },
          )
        }
        setJobs(next)
      } catch {
        if (!cancelled) setJobs([])
      }
    }
    poll()
    const id = setInterval(poll, 4000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [route, selectedJobId, setSearchParams, demoMode])

  const openRun = (jobId: string, pipeline: PipelineId = 'datacenter-siting') => {
    setRoutedPipeline(pipeline)
    // Flag the user as having submitted a real pipeline. The guided
    // tour reads this flag on finish to decide whether to auto-hide
    // the seeded winter-peak fixture: returning users who already
    // have their own runs keep the fixture row in Reports.
    markUserHasRunPipeline()
    // The user is actively opening a run, so the post-toggle empty-
    // state suppression is no longer wanted: from here on the Agent
    // Pipeline tab's empty-state behavior reverts to the normal Sample
    // fallback if this run later goes away.
    setSuppressSampleAfterDemoToggle(false)
    setSearchParams({ tab: 'agent-pipeline', job: jobId })
  }

  const onRoute = (next: Route) => {
    if (next === 'new-session') {
      setSearchParams({})
    } else {
      setSearchParams({ tab: next })
    }
  }

  return (
    <div className={`app${sidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
      <Sidebar
        route={route}
        pendingCompletions={pendingCompletions}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((c) => !c)}
      />
      <main className="workspace">
        <TopBar here={ROUTE_LABELS[route]} />
        <SmoothStage
          style={{ justifyContent: route === 'new-session' ? 'center' : 'flex-start' }}
          resetKey={`${route}|${selectedJobId ?? ''}`}
        >
          {route === 'new-session' && <NewSessionView onStarted={openRun} />}
          {route === 'agent-pipeline' && (
            // Key on demoMode so flipping the toggle force-remounts the
            // whole subtree (PipelineLive's SSE, each report's fetch
            // effects, the pause/cancel state in AgentPipelineView
            // itself). Without this, switching from a live run to demo
            // — or vice versa — just hands the existing instances a new
            // `featured` prop, and the previous job's child state can
            // bleed through. Remounting drops cleanly to the demo empty
            // state (Sample run) or the live empty state.
            <AgentPipelineView
              key={demoMode ? 'agent-demo' : 'agent-live'}
              selectedJobId={selectedJobId}
              jobs={jobs}
              routedPipeline={routedPipeline}
              onJobsChanged={setJobs}
              suppressSample={suppressSampleAfterDemoToggle}
            />
          )}
          {route === 'reports' && (
            <ReportsView jobs={jobs} onOpen={openRun} onJobsChanged={setJobs} />
          )}
          {route === 'dashboard' && <DashboardView />}
          {route === 'settings' && <SettingsView />}
        </SmoothStage>
      </main>
    </div>
  )
}

// ── Sidebar ─────────────────────────────────────────────────────────────── //

function Sidebar({
  route,
  pendingCompletions,
  collapsed,
  onToggleCollapsed,
}: {
  route: Route
  pendingCompletions: number
  collapsed: boolean
  onToggleCollapsed: () => void
}) {
  // Demo-aware sidebar: when demo mode is on, the bottom-left profile slot
  // swaps from the real AccountPopup (which would impersonate a fake user
  // and try to call /me) to a Log In button. The button advertises the
  // demo state honestly and gives the user a one-click path to a real
  // session.
  const [demo] = useDemoMode()
  const items: Array<{ id: Route; label: string; primary?: boolean; icon: JSX.Element }> = [
    {
      id: 'new-session',
      label: 'New session',
      primary: true,
      icon: (
        <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v10M7 12h10" />
        </svg>
      ),
    },
    {
      id: 'agent-pipeline',
      label: 'Agent pipeline',
      icon: (
        <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 7h6M14 7h6M4 12h16M4 17h6M14 17h6" />
          <circle cx="12" cy="7" r="2" /><circle cx="12" cy="17" r="2" />
        </svg>
      ),
    },
    {
      id: 'reports',
      label: 'Reports',
      icon: (
        <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
          <path d="M14 3v5h5" />
          <path d="M9 13h6M9 17h4" />
        </svg>
      ),
    },
    {
      id: 'dashboard',
      label: 'Dashboard',
      icon: (
        <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="8" height="10" rx="1.5" />
          <rect x="13" y="3" width="8" height="6" rx="1.5" />
          <rect x="13" y="11" width="8" height="10" rx="1.5" />
          <rect x="3" y="15" width="8" height="6" rx="1.5" />
        </svg>
      ),
    },
  ]

  return (
    <aside className="sidebar" aria-label="Primary">
      <div className="sidebar-head">
        <Link className="brand" to="/" aria-label="Skorpio">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#1f1e1d"/><g transform="translate(6.25, 3) scale(0.8125)"><path d="M12 0 C 12 8, 22 14, 22 22 A 10 10 0 1 1 2 22 C 2 14, 12 8, 12 0 Z" fill="#F38764"/></g></svg>
          <span className="wordmark">SKORPIO</span>
        </Link>
        <button
          className="icon-btn"
          type="button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand' : 'Collapse'}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <path d="M9 4v16" />
          </svg>
        </button>
      </div>

      {items.map((item) => {
        const showPill = item.id === 'agent-pipeline' && pendingCompletions > 0 && route !== 'agent-pipeline'
        return (
          <Link
            key={item.id}
            to={routeHref(item.id)}
            className={`nav-item${item.primary ? ' primary' : ''}${route === item.id ? ' active' : ''}`}
            data-tour-anchor={item.id === 'reports' ? 'nav-reports' : undefined}
          >
            {item.icon}
            <span className="nav-label">{item.label}</span>
            {showPill && (
              <span className="nav-pill" title={`${pendingCompletions} run${pendingCompletions === 1 ? '' : 's'} finished`}>
                <svg viewBox="0 0 12 12" width="9" height="9" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M2.5 6.5l2.5 2.5 4.5-5" />
                </svg>
                {pendingCompletions > 1 ? `${pendingCompletions} done` : 'done'}
              </span>
            )}
          </Link>
        )
      })}

      <div className="sidebar-foot">
        {demo ? <DemoLoginButton /> : <AccountPopup />}
      </div>
    </aside>
  )
}

// ── Account popup (anchored to the profile button at the bottom of the
//    sidebar; opens upward like Claude.ai's account menu) ───────────────── //

// Sidebar widget shown at the bottom-left when demo mode is on. Replaces
// the real AccountPopup so the UI doesn't impersonate a signed-in user
// (no fake "Demo viewer" name, no /me round-trip). The button routes to
// /login so a curious judge can convert the demo preview into a real
// signed-in session at any time.
function DemoLoginButton() {
  const nav = useNavigate()
  return (
    <button
      type="button"
      className="profile"
      aria-label="Log in"
      onClick={() => nav('/login')}
    >
      <span className="avatar" aria-hidden="true">
        {/* Lucide `log-in` (lucide.dev/icons/log-in) — inlined so we
            don't pull lucide-react in for one icon. Stroke-only path
            inherits ``color`` from .avatar (bg-0 on the orange
            gradient) so contrast tracks the avatar treatment. */}
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
          <polyline points="10 17 15 12 10 7" />
          <line x1="15" x2="3" y1="12" y2="12" />
        </svg>
      </span>
      <span className="who">
        <span className="name">Log in</span>
        <span className="plan">Demo preview</span>
      </span>
    </button>
  )
}

function AccountPopup() {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [showUpgrade, setShowUpgrade] = useState(false)
  const [user, setUser] = useState<MeResponse | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  // Real session info from the backend. If /me 401s the user has no valid
  // token — bounce them to the login page. Also re-sync localStorage so
  // loadUserEmail()-callers (CSV export, etc.) see the canonical email.
  useEffect(() => {
    let cancelled = false
    api.getMe()
      .then((u) => {
        if (cancelled) return
        setUser(u)
        if (typeof window !== 'undefined') {
          window.localStorage.setItem(USER_EMAIL_KEY, u.email)
        }
      })
      .catch(() => {
        if (cancelled) return
        clearToken()
        if (typeof window !== 'undefined') {
          window.localStorage.removeItem(USER_EMAIL_KEY)
        }
        nav('/login')
      })
    return () => {
      cancelled = true
    }
  }, [nav])

  const userEmail = user?.email || loadUserEmail()
  const userName = user?.name || userEmail.split('@')[0]
  const initial = (userName || 'U').charAt(0).toUpperCase()

  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open])

  const onUpgrade = () => {
    setOpen(false)
    setShowUpgrade(true)
  }
  const onLogout = () => {
    setOpen(false)
    // Best-effort server notify; the real "logout" is dropping the token client-side.
    api.logout().catch(() => {})
    clearToken()
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(USER_EMAIL_KEY)
    }
    nav('/login')
  }

  return (
    <div className="account-wrap" ref={ref}>
      <button
        className={`profile${open ? ' open' : ''}`}
        type="button"
        aria-label="Account menu"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="avatar">{initial}</span>
        <span className="who">
          <span className="name">{userName}</span>
          <span className="plan">Pro plan</span>
        </span>
        <svg className="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M8 9l4-4 4 4" />
          <path d="M8 15l4 4 4-4" />
        </svg>
      </button>

      {open && (
        <div className="account-menu" role="menu">
          <div className="account-menu-head">
            <span className="account-menu-email">{userEmail}</span>
            <span className="account-menu-plan">PRO PLAN</span>
          </div>
          <Link
            to={routeHref('settings')}
            role="menuitem"
            className="account-menu-item"
            onClick={() => setOpen(false)}
          >
            <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.4.9a7 7 0 0 0-2.1-1.2L14 3h-4l-.4 2.6a7 7 0 0 0-2.1 1.2L5.1 5.9l-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.4-.9a7 7 0 0 0 2.1 1.2L10 21h4l.4-2.6a7 7 0 0 0 2.1-1.2l2.4.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z" />
            </svg>
            Settings
          </Link>
          <button type="button" role="menuitem" className="account-menu-item" onClick={onUpgrade}>
            <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 3l3 6 6 .9-4.5 4.4 1 6.2L12 17.8 6.5 20.5l1-6.2L3 9.9 9 9z" />
            </svg>
            Upgrade plan
            <span className="account-menu-pill">PRO</span>
          </button>
          <div className="account-menu-rule" />
          <button type="button" role="menuitem" className="account-menu-item danger" onClick={onLogout}>
            <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <path d="M16 17l5-5-5-5" />
              <path d="M21 12H9" />
            </svg>
            Log out
          </button>
        </div>
      )}

      {showUpgrade && <UpgradePlanModal onClose={() => setShowUpgrade(false)} />}
    </div>
  )
}

function UpgradePlanModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-label="Upgrade plan" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>Upgrade your plan</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <p className="modal-sub">You're on Skorpio Pro. Talk to us about Enterprise for SSO, audit logs, and dedicated support.</p>

        <div className="plan-grid">
          <div className="plan-card">
            <div className="plan-eyebrow">PRO</div>
            <div className="plan-price">$49<small>/seat/mo</small></div>
            <ul className="plan-features">
              <li>All 5 pipelines</li>
              <li>Per-user run history + JSON import/export of reports</li>
              <li>Email support</li>
            </ul>
            <button type="button" className="plan-cta" disabled>Current plan</button>
          </div>
          <div className="plan-card highlight">
            <div className="plan-eyebrow accent">ENTERPRISE</div>
            <div className="plan-price">Talk to us</div>
            <ul className="plan-features">
              <li>SSO + SAML, audit logs</li>
              <li>Custom pipelines + private data sources</li>
              <li>Dedicated success manager</li>
              <li>SLA-backed uptime</li>
            </ul>
            <button type="button" className="plan-cta primary">Contact sales</button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Top bar ─────────────────────────────────────────────────────────────── //

// Live telemetry header. Pulls real data where we have a free source:
//   - Weather     → OpenWeather (Toronto). Renders "—" if no key.
//   - Active runs → our own /api/jobs, counting non-terminal stages.
//   - Grid carbon → static IESO 2024 annual average. Labeled with the year
//                   and source so it reads as a citation, not as "live".
//                   ElectricityMaps would give a live number but it's a
//                   paid/non-commercial-only API — out of scope for the
//                   demo; the /api/grid-carbon endpoint stays in case it
//                   gets wired in later.
function TopBar({ here }: { here: string }) {
  const [weather, setWeather] = useState<{ temp_c: number; condition: string } | null>(null)
  const [activeRuns, setActiveRuns] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      const [w, jobs] = await Promise.all([
        api.weather('toronto').catch(() => null),
        api.listJobs().catch(() => [] as JobListItem[]),
      ])
      if (cancelled) return
      setWeather(w ? { temp_c: w.temp_c, condition: w.condition } : null)
      setActiveRuns(jobs.filter((j) => !TERMINAL_STAGES.has(j.stage)).length)
    }
    load()
    // Weather and active-run counts both change slowly enough that a 5-min
    // poll keeps the bar fresh without spamming OpenWeather's free tier.
    const id = setInterval(load, 5 * 60 * 1000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  return (
    <header className="topbar">
      <div className="crumbs">
        <span className="live">
          <span className="dot" /> Grid · Live
        </span>
        <span className="sep">·</span>
        <span>Console</span>
        <span className="sep">/</span>
        <span className="here">{here}</span>
      </div>
      <div className="telemetry">
        <span className="tcell">
          Region <strong>Ontario · IESO</strong>
        </span>
        <span
          className="tcell ok"
          title="Annual average emissions intensity reported by Ontario IESO for 2024. Not live."
        >
          Ontario avg <strong>30 gCO₂/kWh (IESO 2024)</strong>
        </span>
        <span className="tcell">
          Active runs <strong>{activeRuns ?? '—'}</strong>
        </span>
        <span className="tcell">
          Toronto <strong>
            {weather
              ? `${Math.round(weather.temp_c)}°C · ${weather.condition}`
              : '—'}
          </strong>
        </span>
      </div>
    </header>
  )
}

// ── New session ─────────────────────────────────────────────────────────── //

function NewSessionView({
  onStarted,
}: {
  onStarted: (jobId: string, pipeline: PipelineId) => void
}) {
  const [prompt, setPrompt] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [model, setModel] = useState<ClaudeModel>(loadStoredModel)
  const [modelOpen, setModelOpen] = useState(false)
  const modelRef = useRef<HTMLDivElement>(null)
  // Two layers of pipeline routing:
  //   chipLock   — set by clicking a suggestion card; auto-clears on edit so
  //                a fresh prompt falls back to inference.
  //   userOverride — explicit pick from the override pill; sticky until the
  //                  user changes it back to "Auto-route".
  // The override always wins.
  const [chipLock, setChipLock] = useState<PipelineId | null>(null)
  const [userOverride, setUserOverride] = useState<PipelineId | null>(null)
  const [pipelineOpen, setPipelineOpen] = useState(false)
  const pipelineRef = useRef<HTMLDivElement>(null)
  // Demo mode is controlled by the global bottom-right toggle. The composer
  // reads from the shared hook to gate placeholder text + suggestion cards;
  // flips happen elsewhere (DemoToggle), so we only need the value here.
  const [demoMode] = useDemoMode()
  // One random placeholder per mount of the view.
  const placeholder = useMemo(() => randomExample(), [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(MODEL_STORAGE_KEY, model)
  }, [model])

  // Clear any leftover prompt text whenever the guided tour opens
  // (auto-launch on first visit, or via the (?) replay button). A
  // populated composer hides the demo notice overlay and would
  // break step 4's anchor measurement.
  useEffect(() => {
    if (typeof window === 'undefined') return
    const handler = () => setPrompt('')
    window.addEventListener('skorpio-tour-open', handler)
    return () => window.removeEventListener('skorpio-tour-open', handler)
  }, [])

  // Toggling demo mode ON should also reset the composer so the
  // "Free-form prompts are disabled in demo mode" overlay can show
  // (it's gated on `demoMode && !prompt`). Ref-tracked so we only
  // fire on the actual off→on transition, not on initial mount
  // when demoMode happens to be true.
  const prevDemoModeRef = useRef(demoMode)
  useEffect(() => {
    if (!prevDemoModeRef.current && demoMode) setPrompt('')
    prevDemoModeRef.current = demoMode
  }, [demoMode])

  useEffect(() => {
    if (!modelOpen) return
    const onDocClick = (e: MouseEvent) => {
      if (modelRef.current && !modelRef.current.contains(e.target as Node)) {
        setModelOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [modelOpen])

  useEffect(() => {
    if (!pipelineOpen) return
    const onDocClick = (e: MouseEvent) => {
      if (pipelineRef.current && !pipelineRef.current.contains(e.target as Node)) {
        setPipelineOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [pipelineOpen])

  const greeting = (() => {
    const h = new Date().getHours()
    if (h < 5) return 'Up late'
    if (h < 12) return 'Morning'
    if (h < 17) return 'Afternoon'
    if (h < 21) return 'Evening'
    return 'Tonight'
  })()

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const workload = prompt.trim()
    // Stricter input validation — defends against gibberish ("???", "ab", "lol")
    // and accidental general-LLM use. Backend still does its own off-topic
    // check via RouterAgent; this is just to fail fast on obvious junk.
    if (workload.length < 10 || !/[a-z]{3,}/i.test(workload)) {
      setError('Describe your scenario in a sentence. Try one of the example prompts.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      // Demo mode short-circuit: skip the routing API call AND the submit
      // API call. Pick the pipeline locally (override > chip > regex) and
      // hand the matching pre-loaded historical job_id to the in-tab view.
      // The report viewer renders the real DB row; theater is layered on
      // by PipelineLive's FakeProgress overlay.
      if (demoMode) {
        const pipeline = (userOverride ?? chipLock ?? inferPipelineFromPrompt(workload)) as PipelineId
        let demoJobId = getDemoJobId(pipeline)
        if (!demoJobId) {
          // Cache miss — resolver hasn't run yet or this prefix didn't match
          // anything. Try resolving once, then surface a clear error.
          try {
            const map = await resolveDemoJobIds()
            demoJobId = map[pipeline] ?? null
          } catch {
            /* fall through to error below */
          }
        }
        if (!demoJobId) {
          setError(
            `Demo job for ${pipeline} could not be found in the database. The historical run may have been deleted.`,
          )
          setSubmitting(false)
          return
        }
        // Reveal this pipeline's entry in the demo Reports table. Until the
        // operator submits something, demo Reports stays empty so judges see
        // a fresh-run feel.
        markFixtureSubmitted(pipeline)
        // Kick off the theater immediately — even if the operator never
        // opens this report's view (e.g. they bounce back to New session
        // and submit four more), the timer runs in the background and the
        // Reports row reflects live progress.
        startTheater(pipeline)
        onStarted(demoJobId, pipeline)
        return
      }
      // Decide pipeline first so we know which API to hit. Each pipeline has
      // its own submit endpoint; all flows hand the job_id to the in-tab
      // agent-pipeline view.
      //
      // Routing order:
      //   1. Explicit dropdown override (userOverride)            — most specific
      //   2. Chip lock from a clicked suggestion (chipLock)
      //   3. Backend RouterAgent (Claude Haiku, ~1s)              — accurate
      //   4. Frontend regex (inferPipelineFromPrompt) — offline fallback
      //
      // The backend returns HTTP 400 when the prompt is off-topic or names
      // multiple locations. We surface that reason directly to the user and
      // stop — never silently default into a pipeline.
      let pipeline: PipelineId
      if (userOverride) {
        pipeline = userOverride
      } else if (chipLock) {
        pipeline = chipLock
      } else {
        try {
          const route = await api.routePrompt(workload)
          pipeline = (PIPELINES.some((p) => p.id === route.pipeline_id)
            ? route.pipeline_id
            : inferPipelineFromPrompt(workload)) as PipelineId
        } catch (routeErr) {
          if (routeErr instanceof ApiError && routeErr.status === 400) {
            const detail = (routeErr.body as { detail?: { error?: string; reason?: string } } | null)?.detail
            if (detail?.error === 'prompt_rejected' && detail.reason) {
              setError(detail.reason)
              setSubmitting(false)
              return
            }
          }
          // Network error or other non-rejection failure → fall back to regex.
          pipeline = inferPipelineFromPrompt(workload)
        }
      }
      if (pipeline === 'winter-peak-stress') {
        const res = await api.submitWinterPeak({ query: workload, model })
        onStarted(res.job_id, pipeline)
        return
      }
      if (pipeline === 'electrification-readiness') {
        const res = await api.submitElectrification({ query: workload, model })
        onStarted(res.job_id, pipeline)
        return
      }
      if (pipeline === 'grid-investment-optimizer') {
        const res = await api.submitInvestment({ query: workload, model })
        onStarted(res.job_id, pipeline)
        return
      }
      if (pipeline === 'datacenter-expansion') {
        const res = await api.submitExpansion({ query: workload, model })
        onStarted(res.job_id, pipeline)
        return
      }
      const res = await api.submitSiting({ workload, model })
      onStarted(res.job_id, pipeline)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setSubmitting(false)
    }
  }

  const onChipPick = (text: string, pipeline: PipelineId) => {
    setPrompt(text)
    setChipLock(pipeline)
  }

  // What's shown in the override pill. The explicit override wins; otherwise
  // mirror the chip lock; otherwise null = "Auto-route".
  const displayedPipeline: PipelineId | null = userOverride ?? chipLock
  const displayedMeta = displayedPipeline ? pipelineById(displayedPipeline) : null

  const activeModel = MODEL_OPTIONS.find((m) => m.id === model) ?? MODEL_OPTIONS[0]

  return (
    <div className="view active" id="view-new-session">
      <div className="greeting">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#1f1e1d"/><g transform="translate(6.25, 3) scale(0.8125)"><path d="M12 0 C 12 8, 22 14, 22 22 A 10 10 0 1 1 2 22 C 2 14, 12 8, 12 0 Z" fill="#F38764"/></g></svg>
        <h1>
          {demoMode ? <em>{greeting}</em> : <><em>{greeting},</em> Max</>}
        </h1>
      </div>

      <form
        className={`composer${demoMode ? ' composer-demo' : ''}`}
        onSubmit={onSubmit}
        noValidate
        data-tour-anchor="composer"
      >
        <div
          style={{ position: 'relative' }}
          // Tour anchor used by step 4 (both demo and non-demo
          // variants) so the spotlight covers the same input area
          // regardless of mode. The 'composer' anchor on the form
          // includes the pickers + submit row below; this inner
          // wrapper is just the textarea (and its demo-mode notice
          // overlay), which is the part that step 4 is talking about.
          data-tour-anchor="composer-input"
        >
          <textarea
            rows={2}
            placeholder={demoMode ? '' : placeholder}
            value={prompt}
            onChange={(e) => {
              setPrompt(e.target.value)
              // Once the user edits, drop the chip lock; inference kicks in on
              // submit. The explicit user override is sticky and stays.
              if (chipLock) setChipLock(null)
            }}
            // Enter submits, Shift+Enter inserts a newline — matches the
            // follow-up chatbar and standard chat UX. Without this handler
            // a plain Enter would just newline (default textarea behavior)
            // and the only way to run was the orange arrow button.
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                const form = (e.currentTarget.form as HTMLFormElement | null) ?? null
                form?.requestSubmit()
              }
            }}
            // Demo mode: cards auto-fill, user can't edit. readOnly (not
            // disabled) so the box keeps its full styling and remains
            // selectable for cards to populate.
            readOnly={demoMode}
            disabled={submitting}
          />
          {demoMode && !prompt && (
            <div className="composer-demo-overlay" aria-hidden="true" data-tour-anchor="demo-notice">
              Pick a card below, or see this feature live during the in-person demo.
            </div>
          )}
        </div>
        <div className="composer-row">
          <div className="pipeline-picker" ref={pipelineRef}>
            <button
              className="pipeline-pill"
              type="button"
              aria-haspopup="listbox"
              aria-expanded={pipelineOpen}
              onClick={() => setPipelineOpen((o) => !o)}
              disabled={submitting || demoMode}
              title={
                demoMode
                  ? 'Pipeline routing is locked to the selected suggestion card in demo mode'
                  : displayedMeta
                  ? `Routing locked to ${displayedMeta.label}`
                  : 'Agent picks the pipeline based on your prompt'
              }
            >
              {displayedMeta ? (
                <>
                  <span
                    className="pipeline-pill-dot"
                    style={{ background: displayedMeta.accent }}
                  />
                  <span style={{ color: displayedMeta.accent }}>{displayedMeta.short}</span>
                </>
              ) : (
                <>
                  <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M4 7h6M14 7h6M4 12h16M4 17h6M14 17h6" />
                    <circle cx="12" cy="7" r="2" />
                    <circle cx="12" cy="17" r="2" />
                  </svg>
                  Auto-route
                </>
              )}
              <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            {pipelineOpen && (
              <ul className="pipeline-menu" role="listbox" aria-label="Pipeline routing">
                <li>
                  <button
                    type="button"
                    role="option"
                    aria-selected={!userOverride}
                    className={`pipeline-menu-item${!userOverride ? ' active' : ''}`}
                    onClick={() => {
                      setUserOverride(null)
                      setPipelineOpen(false)
                    }}
                  >
                    <span className="pipeline-menu-row">
                      <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M4 7h6M14 7h6M4 12h16M4 17h6M14 17h6" />
                        <circle cx="12" cy="7" r="2" />
                        <circle cx="12" cy="17" r="2" />
                      </svg>
                      <span className="pipeline-menu-label">Auto-route</span>
                    </span>
                    <span className="pipeline-menu-sub">Agent picks based on prompt</span>
                  </button>
                </li>
                {PIPELINES.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={userOverride === p.id}
                      className={`pipeline-menu-item${userOverride === p.id ? ' active' : ''}`}
                      onClick={() => {
                        setUserOverride(p.id)
                        setPipelineOpen(false)
                      }}
                    >
                      <span className="pipeline-menu-row">
                        <span
                          className="pipeline-menu-dot"
                          style={{ background: p.accent }}
                        />
                        <span className="pipeline-menu-label" style={{ color: p.accent }}>
                          {p.label}
                        </span>
                      </span>
                      <span className="pipeline-menu-sub">{p.blurb}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <span className="spacer" />

          <div className="model-picker" ref={modelRef}>
            <button
              className="model-pill"
              type="button"
              aria-haspopup="listbox"
              aria-expanded={modelOpen}
              onClick={() => setModelOpen((o) => !o)}
              disabled={submitting || demoMode}
              title={demoMode ? 'Model is locked to Sonnet in demo mode' : undefined}
            >
              Skorpio · {demoMode ? 'Sonnet' : activeModel.label}
              <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            {modelOpen && (
              <ul className="model-menu" role="listbox" aria-label="Claude model">
                {MODEL_OPTIONS.map((opt) => (
                  <li key={opt.id}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={opt.id === model}
                      className={`model-menu-item${opt.id === model ? ' active' : ''}`}
                      onClick={() => {
                        setModel(opt.id)
                        setModelOpen(false)
                      }}
                    >
                      <span className="model-menu-label">{opt.label}</span>
                      <span className="model-menu-sub">{opt.sub}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button
            className="send accent"
            type="submit"
            aria-label="Run"
            title="Run"
            disabled={submitting}
            data-tour-anchor="submit-button"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14" />
              <path d="M13 6l6 6-6 6" />
            </svg>
          </button>
        </div>
      </form>

      {/* Below-composer notice slot. Errors win when present; in demo
          mode without an active error a permanent demo notice fills
          the slot so the user always sees the explanation for why
          typing is locked, even once a card has populated the prompt
          and the in-textarea overlay has stepped aside. Uses the same
          red error-banner palette as the validation error so the slot
          reads as one consistent UI element regardless of which
          message it carries; the leading dot echoes the ReportChatBar
          follow-up notice. */}
      {error ? (
        <div className="error-banner new-session-error">{error}</div>
      ) : demoMode ? (
        <div className="error-banner demo-notice new-session-error">
          <span className="banner-dot" aria-hidden="true" />
          <span>
            <strong>Demo preview</strong> · Free-form prompts are disabled in demo mode.
          </span>
        </div>
      ) : null}

      <SuggestionGrid onPick={onChipPick} demoMode={demoMode} />

      <div className="stage-foot">
        <span className="item">
          <strong>v0.1.0</strong> Operator console
        </span>
        <span className="sep" />
        <span className="item">
          Pipelines · <strong>{PIPELINES.length}</strong>
        </span>
        <span className="sep" />
        <span className="item">
          Status · <strong>{submitting ? 'Routing…' : 'Idle'}</strong>
        </span>
      </div>
    </div>
  )
}

// Suggestion cards under the composer.
//   Live mode: one random example per pipeline, refreshed each mount.
//   Demo mode: the 5 captured prompts from `demo/prompts.ts`, in fixed order
//   so the operator can rehearse a predictable walkthrough.
function SuggestionGrid({
  onPick,
  demoMode,
}: {
  onPick: (text: string, pipeline: PipelineId) => void
  demoMode: boolean
}) {
  const picks = useMemo(() => {
    if (demoMode) {
      // Resolved from the demo prompt index. We import lazily inside useMemo
      // to keep the live-mode bundle path free of demo data references.
      return DEMO_PROMPTS.map((dp) => ({
        pipeline: pipelineById(dp.pipelineId)!,
        text: dp.prompt,
      })).filter((p) => p.pipeline)
    }
    return PIPELINES.map((p) => ({
      pipeline: p,
      text: p.examples[Math.floor(Math.random() * p.examples.length)],
    }))
  }, [demoMode])
  return (
    <div className="suggestions">
      <div className="suggestions-label">{demoMode ? 'DEMO · PICK ONE' : 'TRY'}</div>
      <div className="suggestions-grid" data-tour-anchor="cards">
        {picks.map(({ pipeline, text }) => (
          <button
            key={pipeline.id}
            type="button"
            className="suggestion-card"
            onClick={() => onPick(text, pipeline.id)}
          >
            <span className="suggestion-prompt">"{text}"</span>
            <span
              className="suggestion-pipeline"
              style={{ color: pipeline.accent }}
            >
              <span
                className="suggestion-dot"
                style={{ background: pipeline.accent }}
              />
              {pipeline.label}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Agent pipeline (in-tab) ─────────────────────────────────────────────── //

function AgentPipelineView({
  selectedJobId,
  jobs,
  routedPipeline,
  onJobsChanged,
  suppressSample,
}: {
  selectedJobId: string | null
  jobs: JobListItem[] | null
  routedPipeline: PipelineId
  onJobsChanged: (next: JobListItem[]) => void
  // Transient flag set by HomePage on a non-demo → demo toggle so the
  // Sample run fallback doesn't fill the empty slot. Cleared the
  // moment the user opens a run (openRun in HomePage).
  suppressSample: boolean
}) {
  // Demo mode skips the "first non-terminal / first job" fallback so a stale
  // pre-demo job doesn't sneak into the Agent pipeline tab. Demo only ever
  // shows the job the operator explicitly opened (via composer submit or a
  // Reports row click — both of which set selectedJobId).
  const [demoMode] = useDemoMode()
  // Subscribing to the demo-fixture tick (without reading it) forces this
  // view to re-render the moment any fixture's submitted/played flag
  // changes. Critical for the isFixtureSubmitted check in isFeaturable
  // below: hiding a fixture from Reports must immediately drop it from
  // Agent pipeline too, not on the next unrelated re-render.
  useDemoFixtureTick()
  const SAMPLE_FEATURED = sampleRunFixture.job_list_item as JobListItem
  // Demo fixtures only count as features once the user has submitted them
  // (i.e. the row is visible in Reports). Hiding a fixture from Reports
  // must also hide it here, otherwise a stale selectedJobId / URL ?job=
  // keeps the previously-opened report rendered on Agent pipeline. Non-
  // demo jobs short-circuit the submitted check.
  const isFeaturable = (j: JobListItem): boolean => {
    if (!demoMode) return true
    const pid = pipelineForDemoJobId(j.job_id)
    return pid === null || isFixtureSubmitted(pid)
  }
  const realFeatured =
    (selectedJobId && jobs?.find((j) => j.job_id === selectedJobId && isFeaturable(j))) ||
    (demoMode
      ? undefined
      : jobs?.find((j) => !TERMINAL_STAGES.has(j.stage)) || jobs?.[0])
  // Empty-state fallback: no real selected/recent run, AND the jobs list
  // has finished loading (jobs !== null), so we know the empty state is
  // settled. Render the winter-peak fixture as a Sample run to give judges
  // a finished-pipeline view to land on. Skipped while jobs is still null
  // (initial load) so we don't flash the sample for a tick.
  //
  // Suppressed when the first-time guided tour has just auto-hidden the
  // same fixture from Reports — otherwise the user would dismiss the
  // tour and find the winter-peak run sitting right where Reports
  // claims to have wiped it. The suppression flag is cleared once the
  // user submits a real pipeline (see markUserHasRunPipeline) so the
  // sample fallback can re-appear if they later empty their reports.
  const showSample = !realFeatured && jobs !== null && !isTourSampleSuppressed() && !suppressSample
  const featured = realFeatured ?? (showSample ? SAMPLE_FEATURED : undefined)
  const isSample = showSample
  // Sample is always a completed, non-live run. Lock pause/stop buttons.
  const isLive = !isSample && !!featured && !TERMINAL_STAGES.has(featured.stage)
  // Optimistic local mirror of the orchestrator's paused state. Reset when
  // the featured job changes (different run = different paused state).
  const [isPaused, setIsPaused] = useState(false)
  const [pauseError, setPauseError] = useState<string | null>(null)
  useEffect(() => {
    setIsPaused(false)
    setPauseError(null)
  }, [featured?.job_id])

  const togglePause = async () => {
    if (!featured) return
    const next = !isPaused
    setIsPaused(next)
    setPauseError(null)
    try {
      if (next) {
        await api.pauseJob(featured.job_id)
      } else {
        await api.resumeJob(featured.job_id)
      }
    } catch (err) {
      setIsPaused(!next)  // revert on failure
      setPauseError(err instanceof Error ? err.message : String(err))
    }
  }

  const stopJob = async () => {
    if (!featured) return
    setPauseError(null)
    try {
      await api.cancelJob(featured.job_id)
      // Cancellation lands at the next stage boundary; the 4s job poll will
      // surface the "failed / Cancelled by user" state once the orchestrator
      // crosses it. No optimistic UI update — the poll is fast enough.
    } catch (err) {
      setPauseError(err instanceof Error ? err.message : String(err))
    }
  }

  // Re-tag the featured job's pipeline. Wired into each report's chatbar
  // (the old "Routed to ... · change" pill that used to live in the header
  // moved into the composer's topic slot). Optimistic update first; the
  // 4s poll reconciles if the server disagrees.
  const handlePipelineChange = async (pid: PipelineId) => {
    // No-op for the empty-state Sample run — it's a fixture, not a DB row,
    // so there's nothing to re-tag. Hitting api.updateJobPipeline against
    // the fixture UUID would 404 in non-demo mode.
    if (isSample) return
    if (!featured || jobs === null) return
    if (pid === pipelineForJob(featured)) return
    const prev = jobs
    onJobsChanged(
      jobs.map((j) =>
        j.job_id === featured.job_id ? { ...j, pipeline_id: pid } : j,
      ),
    )
    try {
      await api.updateJobPipeline(featured.job_id, pid)
    } catch (e) {
      onJobsChanged(prev)
      console.error('Failed to re-tag pipeline:', e)
    }
  }

  // Demo theater gate. Mirror of PipelinePage's logic so the in-tab view
  // animates fake progression for the 5 hand-picked historical jobs. Sample
  // empty-state never theaters — it's always a finished pipeline.
  const demoPipelineId = featured && !isSample ? pipelineForDemoJobId(featured.job_id) : null
  const demoPlayed = useFixturePlayed(demoPipelineId)
  const isDemoTheater = !isSample && demoMode && !!featured && isDemoJobId(featured.job_id) && !demoPlayed
  const onTheaterDone = () => {
    if (demoPipelineId) markFixturePlayed(demoPipelineId)
  }

  return (
    <div className="view active" id="view-agent-pipeline">
      <div className="page-head">
        <div>
          <h1 className="title">
            <em>Agent</em> pipeline
          </h1>
          <div className="sub">
            {featured
              ? `${isSample ? 'Sample run' : isLive ? (isPaused ? 'Paused' : 'Live') : 'Run'} · ${featured.job_id.slice(0, 8)} · ${featured.workload_spec}`
              : jobs === null
                ? 'Loading…'
                : 'No runs yet. Submit a prompt from New session.'}
          </div>
        </div>
        <div className="actions">
          {isLive && (
            <>
              <button
                type="button"
                className="run-control"
                onClick={togglePause}
                aria-label={isPaused ? 'Resume the agent' : 'Pause the agent'}
                title={pauseError ?? (isPaused ? 'Resume the agent' : 'Pause the agent')}
              >
                {isPaused ? (
                  <svg className="ico" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden>
                    <path d="M7 4.5v15l13-7.5z" />
                  </svg>
                ) : (
                  <svg className="ico" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden>
                    <rect x="6.5" y="5" width="4" height="14" rx="0.75" />
                    <rect x="13.5" y="5" width="4" height="14" rx="0.75" />
                  </svg>
                )}
              </button>
              <button
                type="button"
                className="run-control run-control--stop"
                onClick={stopJob}
                aria-label="Stop the agent"
                title="Stop the agent"
              >
                <svg className="ico" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden>
                  <rect x="6" y="6" width="12" height="12" rx="1" />
                </svg>
              </button>
            </>
          )}
          <Link
            to="/?tab=reports"
            className="primary link-button"
            title="See all runs in Reports"
          >
            Reports ›
          </Link>
        </div>
      </div>

      {featured && (
        <PipelineLive
          jobId={featured.job_id}
          pipelineId={pipelineForJob(featured)}
          onPipelineChange={handlePipelineChange}
          fakeStream={isDemoTheater}
          onTheaterDone={onTheaterDone}
        />
      )}
      {!isDemoTheater && featured && pipelineForJob(featured) === 'winter-peak-stress' && (
        <WinterPeakReport
          jobId={featured.job_id}
          hasResults={featured.stage === 'completed'}
          onPipelineChange={handlePipelineChange}
        />
      )}
      {!isDemoTheater && featured && pipelineForJob(featured) === 'electrification-readiness' && (
        <ElectrificationReport
          jobId={featured.job_id}
          hasResults={featured.stage === 'completed'}
          onPipelineChange={handlePipelineChange}
        />
      )}
      {!isDemoTheater && featured && pipelineForJob(featured) === 'grid-investment-optimizer' && (
        <InvestmentReport
          jobId={featured.job_id}
          hasResults={featured.stage === 'completed'}
          onPipelineChange={handlePipelineChange}
        />
      )}
      {!isDemoTheater && featured && pipelineForJob(featured) === 'datacenter-expansion' && (
        <ExpansionReport
          jobId={featured.job_id}
          hasResults={featured.stage === 'completed'}
          onPipelineChange={handlePipelineChange}
        />
      )}
    </div>
  )
}

// ── Reports — table backed by /api/jobs ─────────────────────────────────── //

// Until the backend includes a pipeline_id on each job, we infer it from the
// stored prompt text. Existing siting runs end up tagged 'datacenter-siting',
// which is what they were.
function pipelineForJob(job: JobListItem): PipelineId {
  const tagged = (job as { pipeline_id?: PipelineId }).pipeline_id
  if (tagged) return tagged
  return inferPipelineFromPrompt(job.workload_spec || '')
}

// Backend writes naive UTC datetimes (datetime.utcnow), then Pydantic
// serializes without a "Z" suffix. JS's new Date() reads timezone-less ISO
// strings as LOCAL time, which would shift everything by the user's UTC
// offset. Force-parse as UTC so toLocaleString renders correctly.
function parseBackendTs(iso: string): Date {
  if (!iso) return new Date(NaN)
  // Already has timezone info — trust it.
  if (/[Zz]$|[+-]\d{2}:?\d{2}$/.test(iso)) return new Date(iso)
  return new Date(iso + 'Z')
}

function sortJobs(jobs: JobListItem[], key: SortKey): JobListItem[] {
  const out = [...jobs]
  const ts = (j: JobListItem) => parseBackendTs(j.created_at).getTime()
  switch (key) {
    case 'newest':   return out.sort((a, b) => ts(b) - ts(a))
    case 'oldest':   return out.sort((a, b) => ts(a) - ts(b))
    case 'pipeline': return out.sort((a, b) => pipelineForJob(a).localeCompare(pipelineForJob(b)))
    case 'progress': return out.sort((a, b) => (b.progress || 0) - (a.progress || 0))
    case 'stage':    return out.sort((a, b) => a.stage.localeCompare(b.stage))
  }
}

function ReportsView({
  jobs,
  onOpen,
  onJobsChanged,
}: {
  jobs: JobListItem[] | null
  onOpen: (jobId: string, pipeline: PipelineId) => void
  onJobsChanged: (next: JobListItem[]) => void
}) {
  const [demoMode] = useDemoMode()
  // Tick changes whenever a demo fixture is submitted/played or the toggle
  // flips. Forces the filter memo to recompute so the "fresh demo" effect
  // lands immediately — without it, an entry submitted on the New session
  // tab wouldn't appear in Reports until the 4s job-poll fired.
  const demoTick = useDemoFixtureTick()
  // Separate tick bumped on every theater progress event (every 250ms while
  // any pipeline is running) so each Reports row's stage + progress
  // reflects what the background timer is currently at.
  const [theaterTick, setTheaterTick] = useState(0)
  useEffect(() => {
    if (!demoMode) return
    return subscribeAnyTheater(() => setTheaterTick((t) => t + 1))
  }, [demoMode])

  // In demo mode the Reports table is curated for a fresh-run feel:
  // - The 5 hand-picked historical jobs are the ONLY candidates.
  // - A candidate only appears once the operator submits its prompt
  //   (markFixtureSubmitted). Until then, demo Reports is empty.
  // - A submitted-but-unplayed entry is displayed live from the theater
  //   manager (current stage + progress %), so all in-flight runs tick
  //   forward in parallel even when the operator isn't watching them.
  // - Once theater finishes (markFixturePlayed), the entry shows the real
  //   DB row's completed state.
  // The underlying global `jobs` state is left untouched so non-demo views
  // (Agent Pipeline featured-job lookup, sidebar counts) keep their normal
  // behavior.
  const displayJobs = useMemo(() => {
    if (!demoMode || !jobs) return jobs
    return jobs
      .filter((j) => {
        const pid = pipelineForDemoJobId(j.job_id)
        return pid !== null && isFixtureSubmitted(pid)
      })
      .map((j) => {
        const pid = pipelineForDemoJobId(j.job_id)
        if (pid && !isFixturePlayed(pid)) {
          const t = getTheaterState(pid)
          return { ...j, stage: t.stage as PipelineStage, progress: t.progress }
        }
        return j
      })
    // demoTick + theaterTick are intentional deps — they bump on
    // submit/played/toggle and on each timer tick respectively.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demoMode, jobs, demoTick, theaterTick])
  const [sortKey, setSortKey] = useState<SortKey>('newest')
  const [sortOpen, setSortOpen] = useState(false)
  const sortRef = useRef<HTMLDivElement>(null)

  const fileRef = useRef<HTMLInputElement>(null)
  // Batch import — picker is `multiple` now, so the resolution path
  // has to keep the entire set of dropped files around to retry with
  // strategies, not just one. Empty unless a 409 is currently open.
  const [pendingFiles, setPendingFiles] = useState<File[]>([])
  const [conflicts, setConflicts] = useState<ImportConflict[] | null>(null)
  const [importing, setImporting] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<JobListItem | null>(null)
  const [deleting, setDeleting] = useState(false)
  // Set of job_ids the user has ticked in the Reports table. The Export
  // button stays clickable even when empty so a 0-selection click fires
  // the validation banner below; the select-all checkbox in the table
  // head toggles every visible row at once.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  // Click-driven validation error for the Export action — mirrors the
  // New session composer pattern (`setError('Describe your scenario in
  // a sentence...')` → `.error-banner` below the form). Cleared
  // automatically the moment the user ticks any row so the banner
  // doesn't outlive the condition it's complaining about.
  const [exportError, setExportError] = useState<string | null>(null)

  useEffect(() => {
    if (!sortOpen) return
    const onDocClick = (e: MouseEvent) => {
      if (sortRef.current && !sortRef.current.contains(e.target as Node)) setSortOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [sortOpen])

  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(id)
  }, [toast])

  const sortedJobs = useMemo(
    () => (displayJobs ? sortJobs(displayJobs, sortKey) : null),
    [displayJobs, sortKey],
  )

  const onExport = async () => {
    const ids = Array.from(selectedIds)
    if (!ids.length) {
      // Same shape as the New session composer's empty-prompt validation
      // (HomePage.tsx onSubmit) — set a message string, render it in
      // an `.error-banner` below the action row.
      setExportError('Pick reports to export. Try ticking one or more rows below.')
      return
    }
    setExportError(null)
    setExporting(true)
    try {
      // Non-demo: bundle entirely in the browser using JobListItem rows
      // already in state + per-job /api/results/<id> reads. Drops the
      // dependency on the backend's `/api/jobs/export-bundle` endpoint
      // (useful on offline-ish deploys and as a thinner backend
      // contract). Demo mode still goes through `api.exportJobsBundle`
      // because demo doesn't reach this branch in production anyway.
      const selectedJobs = (jobs ?? []).filter((j) => selectedIds.has(j.job_id))
      const { blob, filename } = demoMode
        ? await api.exportJobsBundle({
            jobIds: ids,
            fromEmail: loadUserEmail() || undefined,
          })
        : await api.exportJobsBundleLocal({
            jobs: selectedJobs,
            fromEmail: loadUserEmail() || undefined,
          })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      setToast(`Exported ${ids.length} report${ids.length === 1 ? '' : 's'} to ${filename}`)
      setSelectedIds(new Set())
    } catch (err) {
      setToast(`Export failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setExporting(false)
    }
  }

  const onImportClick = () => fileRef.current?.click()

  const onFilePicked = async (e: React.ChangeEvent<HTMLInputElement>) => {
    // ORDER MATTERS. `FileList` is a live collection tied to the input
    // element — setting `value = ''` clears the input AND empties the
    // collection. Capture the files into a plain array (a static
    // snapshot) FIRST, then clear the input so the user can re-pick
    // the same file later. The previous order silently discarded every
    // pick and made the import flow look broken.
    const fileList = e.target.files
    if (!fileList || !fileList.length) return
    const files = Array.from(fileList)
    e.target.value = ''
    setPendingFiles(files)
    setImporting(true)
    try {
      const res = await api.importReports(files)
      if (res.ok) {
        finishImport(res.data)
      } else {
        setConflicts(res.conflicts)
      }
    } catch (err) {
      setToast(`Import failed: ${err instanceof Error ? err.message : String(err)}`)
      setPendingFiles([])
    } finally {
      setImporting(false)
    }
  }

  const onResolveConflicts = async (strategies: Record<string, ImportStrategy>) => {
    if (!pendingFiles.length) return
    setImporting(true)
    try {
      const res = await api.importReports(pendingFiles, strategies)
      if (res.ok) {
        finishImport(res.data)
      } else {
        setToast('Some collisions still unresolved. Try again.')
      }
    } catch (err) {
      setToast(`Import failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setImporting(false)
    }
  }

  const finishImport = (data: ImportResult) => {
    setConflicts(null)
    setPendingFiles([])
    const parts = []
    if (data.imported)    parts.push(`${data.imported} imported`)
    if (data.overwritten) parts.push(`${data.overwritten} overwritten`)
    if (data.renamed)     parts.push(`${data.renamed} renamed`)
    if (data.skipped)     parts.push(`${data.skipped} skipped`)
    setToast(parts.length ? parts.join(' · ') : 'Nothing to import.')
  }

  // Selection helpers — kept here next to the Reports table that uses
  // them. `toggleOne` flips a single row; `toggleAll` reads the current
  // visible-jobs list and either selects every visible id or clears
  // them all, depending on whether ALL visible rows are already
  // selected (partial selection still flips to "all selected"). Both
  // clear the export-error banner because any selection change makes
  // the "select something first" complaint stale.
  const toggleOne = (jobId: string) => {
    setExportError(null)
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(jobId)) next.delete(jobId)
      else next.add(jobId)
      return next
    })
  }
  const visibleJobIds = sortedJobs?.map((j) => j.job_id) ?? []
  const allSelected = visibleJobIds.length > 0 && visibleJobIds.every((id) => selectedIds.has(id))
  // Partial selection — at least one row checked but not all of them.
  // Used to render the select-all checkbox in `indeterminate` state
  // (orange fill with a horizontal dash) so the user can see "some are
  // selected" without having to count.
  const someSelected = selectedIds.size > 0 && !allSelected
  const selectAllRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    // `indeterminate` isn't a real HTML attribute — has to be assigned
    // imperatively on the DOM node, hence the ref + effect dance.
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someSelected
    }
  }, [someSelected])
  const toggleAll = () => {
    setExportError(null)
    if (allSelected) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(visibleJobIds))
    }
  }

  return (
    <div className="view active" id="view-reports">
      <div className="page-head">
        <div>
          <h1 className="title">
            <em>Reports</em>
          </h1>
          <div className="sub">
            {displayJobs ? `${displayJobs.length} run${displayJobs.length === 1 ? '' : 's'} · ${SORT_LABELS[sortKey]}` : 'Loading…'}
          </div>
        </div>
        <div className="actions">
          <div className="sort-picker" ref={sortRef}>
            <button
              type="button"
              aria-haspopup="listbox"
              aria-expanded={sortOpen}
              onClick={() => setSortOpen((o) => !o)}
            >
              Sort: {SORT_LABELS[sortKey]}
              <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ width: 12, height: 12, marginLeft: 6, verticalAlign: '-1px' }}>
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            {sortOpen && (
              <ul className="sort-menu" role="listbox">
                {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
                  <li key={k}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={k === sortKey}
                      className={`sort-menu-item${k === sortKey ? ' active' : ''}`}
                      onClick={() => {
                        setSortKey(k)
                        setSortOpen(false)
                      }}
                    >
                      {SORT_LABELS[k]}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button
            type="button"
            onClick={onImportClick}
            disabled={importing}
            data-tour-anchor="report-import"
          >
            {importing ? 'Importing…' : 'Import'}
          </button>
          {/* Stays clickable when 0 selected so the click fires the
              empty-selection validation (matches the New session
              composer pattern, where the send button is enabled even
              on empty input and the form validates on submit). Only
              the in-flight `exporting` state disables it. */}
          <button
            type="button"
            className="primary"
            onClick={onExport}
            disabled={exporting}
            title={
              selectedIds.size === 0
                ? 'Tick one or more rows to select reports to export'
                : `Export ${selectedIds.size} selected`
            }
            data-tour-anchor="report-export"
          >
            {exporting
              ? 'Exporting…'
              : selectedIds.size > 0
                ? `Export (${selectedIds.size})`
                : 'Export'}
          </button>
          <input
            ref={fileRef}
            type="file"
            // Accept both raw JSON envelopes and the .zip the exporter
            // produces for N>1 selections — backend transparently expands
            // any uploaded zip into its inner .json members, so the
            // round-trip "export 5 → email zip → coworker imports zip"
            // works without manual unpacking.
            accept=".json,application/json,.zip,application/zip"
            multiple
            style={{ display: 'none' }}
            onChange={onFilePicked}
          />
        </div>
      </div>

      {/* Click-driven validation banner — reuses `.error-banner` from
          app.css so the look (terracotta `--err` border + 8%-alpha
          fill + small mono text) matches the same banner the New
          session composer renders when a prompt is too short. The
          `.reports-export-error` modifier tightens the top margin and
          adds room below so the banner reads as anchored to the
          Export button above rather than as a header on the table. */}
      {exportError && (
        <div className="error-banner reports-export-error">{exportError}</div>
      )}

      <div className="reports">
        <table>
          <thead>
            <tr>
              <th className="reports-select-col">
                <input
                  ref={selectAllRef}
                  type="checkbox"
                  className="reports-select-all"
                  aria-label={allSelected ? 'Deselect all reports' : 'Select all reports'}
                  checked={allSelected}
                  onChange={toggleAll}
                  disabled={visibleJobIds.length === 0}
                />
              </th>
              <th>Run</th>
              <th>Prompt</th>
              <th>Pipeline</th>
              <th>Stage</th>
              <th>Progress</th>
              <th>Created</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {sortedJobs?.map((j, rowIdx) => {
              const pid = pipelineForJob(j)
              const meta = pipelineById(pid)
              const href = routeHref('agent-pipeline', j.job_id)
              const isFirstRow = rowIdx === 0
              // Plain left-click keeps in-tab navigation via onOpen; any
              // modified click (middle, ctrl/cmd, shift) or right-click falls
              // through to the browser, so "Open in new tab" works because the
              // <Link>s render real anchors with an href.
              //
              // If the user has just dragged to select text inside the row
              // (job_id, prompt, timestamp, etc.), suppress navigation — they
              // wanted to copy, not navigate. Browsers still fire a `click`
              // on mouseup after a drag-select on the same element, so this
              // check is what makes drag-to-highlight feel native.
              const handleClick = (e: ReactMouseEvent) => {
                if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
                  return
                }
                const sel = typeof window !== 'undefined' ? window.getSelection() : null
                if (sel && sel.toString().length > 0) {
                  e.preventDefault()
                  return
                }
                e.preventDefault()
                onOpen(j.job_id, pid)
              }
              return (
                <tr key={j.job_id} data-tour-anchor={isFirstRow ? 'reports-row' : undefined}>
                  <td className="reports-select-col">
                    <input
                      type="checkbox"
                      aria-label={`Select report ${j.job_id.slice(0, 8)}`}
                      checked={selectedIds.has(j.job_id)}
                      onChange={() => toggleOne(j.job_id)}
                      // Stop propagation so the click doesn't bubble into the
                      // row-link navigation in adjacent cells.
                      onClick={(e) => e.stopPropagation()}
                    />
                  </td>
                  <td className="id">
                    <Link to={href} className="row-link" onClick={handleClick}>
                      {j.job_id.slice(0, 8)}
                    </Link>
                    {j.imported && (
                      <span
                        className="imported-badge"
                        title={
                          j.imported_from_email
                            ? `Imported from ${j.imported_from_email}`
                            : 'Imported from a report file'
                        }
                      >
                        IMPORTED
                      </span>
                    )}
                  </td>
                  <td className="label">
                    <Link
                      to={href}
                      className="row-cell-link"
                      onClick={handleClick}
                      draggable={false}
                      tabIndex={-1}
                    >
                      {j.workload_spec}
                    </Link>
                  </td>
                  <td>
                    {meta && (
                      <PipelineTagPicker
                        current={pid}
                        wrapperClassName="badge-pipeline-picker"
                        onSelect={async (newPid) => {
                          if (newPid === pid) return
                          // Optimistic update + rollback on failure.
                          const prevJobs = jobs ?? []
                          if (jobs) {
                            onJobsChanged(
                              jobs.map((row) =>
                                row.job_id === j.job_id ? { ...row, pipeline_id: newPid } : row,
                              ),
                            )
                          }
                          try {
                            await api.updateJobPipeline(j.job_id, newPid)
                          } catch (err) {
                            onJobsChanged(prevJobs)
                            console.error('Failed to re-tag pipeline:', err)
                          }
                        }}
                        renderTrigger={({ open, toggle, triggerRef }) => (
                          <button
                            ref={triggerRef}
                            type="button"
                            className="pipeline-badge"
                            title={`Re-tag from ${meta.label}`}
                            aria-haspopup="listbox"
                            aria-expanded={open}
                            onClick={(e) => {
                              // Block the row-overlay-link from navigating.
                              e.stopPropagation()
                              e.preventDefault()
                              toggle()
                            }}
                            style={{
                              color: meta.accent,
                              borderColor: meta.accent + '55',
                              background: meta.accent + '12',
                            }}
                          >
                            <span className="pipeline-dot" style={{ background: meta.accent }} />
                            {meta.short}
                          </button>
                        )}
                      />
                    )}
                  </td>
                  <td>
                    <Link
                      to={href}
                      className="row-cell-link"
                      onClick={handleClick}
                      draggable={false}
                      tabIndex={-1}
                    >
                      {j.stage}
                    </Link>
                  </td>
                  <td className="num">
                    <Link
                      to={href}
                      className="row-cell-link"
                      onClick={handleClick}
                      draggable={false}
                      tabIndex={-1}
                    >
                      {j.progress}%
                    </Link>
                  </td>
                  <td>
                    <Link
                      to={href}
                      className="row-cell-link"
                      onClick={handleClick}
                      draggable={false}
                      tabIndex={-1}
                    >
                      {parseBackendTs(j.created_at).toLocaleString()}
                    </Link>
                  </td>
                  <td className="action">
                    <button
                      type="button"
                      className="row-delete"
                      title="Delete report"
                      aria-label={`Delete report ${j.job_id.slice(0, 8)}`}
                      onClick={(e) => {
                        // Stop the surrounding cell-link from navigating
                        // when the user just wants to delete the row.
                        e.stopPropagation()
                        e.preventDefault()
                        setPendingDelete(j)
                      }}
                      data-tour-anchor={isFirstRow ? 'reports-row-delete' : undefined}
                    >
                      <svg
                        width="15"
                        height="15"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.7"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <path d="M3 6h18" />
                        <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        <path d="M19 6l-1.2 14a2 2 0 0 1-2 1.8H8.2a2 2 0 0 1-2-1.8L5 6" />
                        <path d="M10 11v6" />
                        <path d="M14 11v6" />
                      </svg>
                    </button>
                  </td>
                </tr>
              )
            })}
            {sortedJobs && sortedJobs.length === 0 && (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '24px', color: 'var(--fg-3)' }}>
                  No runs yet. Submit a prompt from New session, or import a CSV from a teammate.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {toast && <div className="toast">{toast}</div>}

      {conflicts && (
        <CollisionDialog
          conflicts={conflicts}
          onCancel={() => {
            setConflicts(null)
            setPendingFiles([])
          }}
          onResolve={onResolveConflicts}
        />
      )}

      {pendingDelete && (
        <ConfirmDeleteDialog
          job={pendingDelete}
          busy={deleting}
          onCancel={() => setPendingDelete(null)}
          onConfirm={async () => {
            if (!jobs) return
            setDeleting(true)
            const id = pendingDelete.job_id

            // Demo mode: never hit the backend (we don't want to mutate the
            // shared historical record, and on Vercel there's no backend at
            // all). Instead clear the submitted/played flags and tear down
            // any in-flight theater so the row vanishes and a re-submit from
            // the New session tab replays from scratch.
            if (isDemoModeActive() && isDemoJobId(id)) {
              const pid = pipelineForDemoJobId(id)
              if (pid) {
                unmarkFixtureSubmitted(pid)
                unmarkFixturePlayed(pid)
                stopTheater(pid)
                // winter-peak is also the Agent pipeline tab's
                // "Sample run" fallback. Without this the sample would
                // re-render the same fixture the user just hid the
                // moment realFeatured drops to undefined, making the
                // delete look broken. The flag is cleared by
                // markUserHasRunPipeline on the next real submission.
                if (pid === 'winter-peak-stress') markTourSampleSuppressed()
              }
              setPendingDelete(null)
              setDeleting(false)
              setToast('Report hidden. Re-submit from New session to bring it back.')
              return
            }

            const prev = jobs
            // Optimistic remove so the row disappears instantly.
            onJobsChanged(jobs.filter((row) => row.job_id !== id))
            setPendingDelete(null)
            try {
              await api.deleteJob(id)
              setToast('Report deleted')
            } catch (err) {
              onJobsChanged(prev)
              setToast(`Delete failed: ${err instanceof Error ? err.message : String(err)}`)
            } finally {
              setDeleting(false)
            }
          }}
        />
      )}
    </div>
  )
}

// Per-row collision resolver. Defaults every row to "skip" so the user can
// just click Apply to do the safest thing.
function CollisionDialog({
  conflicts,
  onCancel,
  onResolve,
}: {
  conflicts: ImportConflict[]
  onCancel: () => void
  onResolve: (strategies: Record<string, ImportStrategy>) => void
}) {
  const [strategies, setStrategies] = useState<Record<string, ImportStrategy>>(
    () => Object.fromEntries(conflicts.map((c) => [c.job_id, 'skip' as ImportStrategy])),
  )

  const setAll = (s: ImportStrategy) =>
    setStrategies(Object.fromEntries(conflicts.map((c) => [c.job_id, s])))

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal collision-modal" role="dialog" aria-label="Resolve import conflicts" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>{conflicts.length} job ID{conflicts.length === 1 ? '' : 's'} already exist</h2>
          <button type="button" className="modal-close" onClick={onCancel} aria-label="Close">×</button>
        </div>
        <p className="modal-sub">Pick what to do for each conflicting row, then apply.</p>

        <div className="collision-bulk">
          <span>Apply to all:</span>
          <button type="button" onClick={() => setAll('skip')}>Skip</button>
          <button type="button" onClick={() => setAll('overwrite')}>Overwrite</button>
          <button type="button" onClick={() => setAll('new')}>Save as new</button>
        </div>

        <div className="collision-list">
          {conflicts.map((c) => (
            <div key={c.job_id} className="collision-row">
              <div className="collision-info">
                <code className="collision-id">{c.job_id.slice(0, 8)}</code>
                <span className="collision-label">{c.workload_spec || '(no prompt)'}</span>
              </div>
              <div className="collision-choices">
                {(['skip', 'overwrite', 'new'] as ImportStrategy[]).map((opt) => (
                  <label key={opt} className={`collision-choice${strategies[c.job_id] === opt ? ' active' : ''}`}>
                    <input
                      type="radio"
                      name={`strategy-${c.job_id}`}
                      checked={strategies[c.job_id] === opt}
                      onChange={() => setStrategies((s) => ({ ...s, [c.job_id]: opt }))}
                    />
                    {opt === 'skip' ? 'Skip' : opt === 'overwrite' ? 'Overwrite' : 'Save as new'}
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="modal-actions">
          <button type="button" onClick={onCancel}>Cancel</button>
          <button type="button" className="primary" onClick={() => onResolve(strategies)}>
            Apply
          </button>
        </div>
      </div>
    </div>
  )
}

// Destructive confirm for the Reports tab's trash button. Mirrors Claude's
// "Are you sure?" affordance: a short title, the item being acted on, and a
// red primary button so the user can't miss the consequence. Escape and the
// backdrop both cancel; Enter confirms.
function ConfirmDeleteDialog({
  job,
  busy,
  onCancel,
  onConfirm,
}: {
  job: JobListItem
  busy: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (busy) return
      if (e.key === 'Escape') onCancel()
      if (e.key === 'Enter') onConfirm()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [busy, onCancel, onConfirm])

  return (
    <div className="modal-backdrop" onClick={busy ? undefined : onCancel}>
      <div
        className="modal confirm-modal"
        role="alertdialog"
        aria-modal="true"
        aria-label="Delete report"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2>Delete this report?</h2>
          <button
            type="button"
            className="modal-close"
            onClick={onCancel}
            disabled={busy}
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <p className="modal-sub">
          <code className="confirm-id">{job.job_id.slice(0, 8)}</code>{' '}
          · {job.workload_spec || '(no prompt)'}
        </p>
        <p className="modal-sub">
          This will permanently remove the run and its saved results. This action can't be undone.
        </p>
        <div className="modal-actions">
          <button type="button" onClick={onCancel} disabled={busy} autoFocus>
            Cancel
          </button>
          <button type="button" className="danger" onClick={onConfirm} disabled={busy}>
            {busy ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Dashboard — real Skorpio operator metrics ───────────────────────────── //
//
// Numbers are pulled from the jobs table via /api/metrics. The Dashboard is
// no longer a pretend grid-weather report — it's a live console showing how
// the platform itself is doing: throughput, success rate, mix, failures.

type DashboardMetrics = Awaited<ReturnType<typeof api.operatorMetrics>>

function DashboardView() {
  const [timeframe, setTimeframe] = useState<Timeframe>('24h')
  const [tfOpen, setTfOpen] = useState(false)
  const tfRef = useRef<HTMLDivElement>(null)
  const [refreshTick, setRefreshTick] = useState(0)
  const [demoMode] = useDemoMode()
  // Bumps on submit/played/toggle so demo metrics refresh immediately —
  // without it the operator wouldn't see counters update until the next
  // 30s poll tick.
  const demoTick = useDemoFixtureTick()

  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const hoursFor = (tf: Timeframe) => (tf === '24h' ? 24 : tf === '7d' ? 24 * 7 : 24 * 30)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        setLoading(true)
        // Demo mode synthesizes the metrics shape from the in-browser
        // submitted/played state — no network call, no leakage of real
        // operator stats. Flipping demo off lets the next run re-fetch
        // the live numbers, restoring the pre-demo view automatically.
        const m: DashboardMetrics = demoMode
          ? buildDemoMetrics(hoursFor(timeframe))
          : await api.operatorMetrics(hoursFor(timeframe))
        if (!cancelled) {
          setMetrics(m)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    // Cheap server-side aggregate; poll every 30s so the dashboard stays
    // responsive without hammering the DB. In demo mode the poll is a
    // no-op (deterministic from state) but harmless.
    const id = setInterval(load, 30_000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [timeframe, refreshTick, demoMode, demoTick])

  useEffect(() => {
    if (!tfOpen) return
    const onDocClick = (e: MouseEvent) => {
      if (tfRef.current && !tfRef.current.contains(e.target as Node)) setTfOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [tfOpen])

  const fmtDuration = (s: number | null) => {
    if (s == null) return '—'
    if (s < 60) return `${Math.round(s)}s`
    return `${(s / 60).toFixed(1)}m`
  }
  const fmtPct = (r: number | null) => (r == null ? '—' : `${Math.round(r * 100)}%`)
  const fmtCount = (n: number | null | undefined) => (n == null ? '—' : n.toLocaleString())
  const topPipeline = metrics?.pipeline_mix?.[0]

  return (
    <div className="view active" id="view-dashboard">
      <div className="page-head">
        <div>
          <h1 className="title">
            <em>Dashboard</em>
          </h1>
          <div className="sub">
            SKORPIO OPERATIONS · {TIMEFRAME_LABELS[timeframe].toUpperCase()}
            {error && <> · <span style={{ color: '#f38764' }}>{error}</span></>}
          </div>
        </div>
        <div className="actions">
          <div className="sort-picker" ref={tfRef}>
            <button
              type="button"
              aria-haspopup="listbox"
              aria-expanded={tfOpen}
              onClick={() => setTfOpen((o) => !o)}
            >
              {TIMEFRAME_LABELS[timeframe]}
              <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ width: 12, height: 12, marginLeft: 6, verticalAlign: '-1px' }}>
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            {tfOpen && (
              <ul className="sort-menu" role="listbox">
                {(Object.keys(TIMEFRAME_LABELS) as Timeframe[]).map((k) => (
                  <li key={k}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={k === timeframe}
                      className={`sort-menu-item${k === timeframe ? ' active' : ''}`}
                      onClick={() => {
                        setTimeframe(k)
                        setTfOpen(false)
                      }}
                    >
                      {TIMEFRAME_LABELS[k]}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button type="button" className="primary" onClick={() => setRefreshTick((t) => t + 1)}>
            Refresh
          </button>
        </div>
      </div>

      <div className="metrics">
        <div className="tile">
          <span className="lbl">Total runs</span>
          <span className="val">
            {fmtCount(metrics?.total_runs)}
          </span>
          <span className="delta">all time</span>
        </div>
        <div className="tile">
          <span className="lbl">Runs · window</span>
          <span className="val">
            {fmtCount(metrics?.runs_in_window)}
          </span>
          <span className="delta">{TIMEFRAME_LABELS[timeframe].toLowerCase()}</span>
        </div>
        <div className="tile">
          <span className="lbl">Active runs</span>
          <span className="val">{fmtCount(metrics?.active_runs)}</span>
          <span className="delta">live, non-terminal</span>
        </div>
        <div className="tile">
          <span className="lbl">Success rate</span>
          <span className="val">{fmtPct(metrics?.success_rate ?? null)}</span>
          <span className="delta">
            {metrics
              ? `${metrics.completed_in_window} ok · ${metrics.failed_in_window} failed`
              : '—'}
          </span>
        </div>
      </div>

      <div className="metrics" style={{ marginTop: 6 }}>
        <div className="tile">
          <span className="lbl">Avg duration</span>
          <span className="val">{fmtDuration(metrics?.avg_duration_seconds ?? null)}</span>
          <span className="delta">completed runs in window</span>
        </div>
        <div className="tile">
          <span className="lbl">Most-used pipeline</span>
          <span className="val" style={{ fontSize: 18, lineHeight: 1.2 }}>
            {topPipeline ? topPipeline.label : '—'}
          </span>
          <span className="delta">
            {topPipeline ? `${topPipeline.count} runs` : 'no data'}
          </span>
        </div>
        <div className="tile">
          <span className="lbl">Pipelines online</span>
          <span className="val">{PIPELINES.length}</span>
          <span className="delta">live capabilities</span>
        </div>
        <div className="tile">
          <span className="lbl">Status</span>
          <span className="val" style={{ fontSize: 18, lineHeight: 1.2 }}>
            {loading && !metrics ? 'Loading…' : error ? 'Stale' : 'Live'}
          </span>
          <span className="delta">
            {metrics ? `as of ${new Date(metrics.as_of + 'Z').toLocaleTimeString()}` : '—'}
          </span>
        </div>
      </div>

      {metrics && metrics.pipeline_mix.length > 0 && (
        <div className="page-head" style={{ marginTop: 28 }}>
          <div>
            <h2 className="title" style={{ fontSize: 22 }}>
              <em>Pipeline mix</em>
            </h2>
            <div className="sub">RUNS PER PIPELINE · ALL TIME</div>
          </div>
        </div>
      )}
      {metrics && metrics.pipeline_mix.length > 0 && (
        <div className="reports" style={{ maxWidth: 720 }}>
          <table>
            <tbody>
              {metrics.pipeline_mix.map((m) => {
                const meta = pipelineById(m.pipeline_id as PipelineId)
                const accent = meta?.accent ?? 'var(--fg-3)'
                const pct = metrics.total_runs > 0
                  ? Math.round((m.count / metrics.total_runs) * 100)
                  : 0
                return (
                  <tr key={m.pipeline_id}>
                    <td className="label" style={{ width: 260 }}>
                      <span
                        className="pipeline-badge"
                        style={{
                          color: accent,
                          borderColor: accent + '55',
                          background: accent + '12',
                        }}
                      >
                        <span className="pipeline-dot" style={{ background: accent }} />
                        {m.label}
                      </span>
                    </td>
                    <td>{m.count.toLocaleString()} runs</td>
                    <td className="action">{pct}%</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {metrics && metrics.recent_failures.length > 0 && (
        <div className="page-head" style={{ marginTop: 28 }}>
          <div>
            <h2 className="title" style={{ fontSize: 22 }}>
              <em>Recent failures</em>
            </h2>
            <div className="sub">LAST 5 FAILED RUNS</div>
          </div>
        </div>
      )}
      {metrics && metrics.recent_failures.length > 0 && (
        <div className="reports" style={{ maxWidth: 920 }}>
          <table>
            <tbody>
              {metrics.recent_failures.map((f) => (
                <tr key={f.job_id}>
                  <td className="label" style={{ width: 130 }}>
                    {f.job_id.slice(0, 8)}
                  </td>
                  <td>
                    <div style={{ color: 'var(--fg-2)' }}>{f.workload_spec}</div>
                    {f.error && (
                      <div
                        style={{
                          color: '#f38764',
                          fontFamily: 'var(--font-mono)',
                          fontSize: 11,
                          marginTop: 4,
                        }}
                      >
                        {f.error}
                      </div>
                    )}
                  </td>
                  <td className="action" style={{ width: 160 }}>
                    {f.updated_at
                      ? new Date(f.updated_at + 'Z').toLocaleString()
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Settings ────────────────────────────────────────────────────────────── //

function SettingsView() {
  return (
    <div className="view active" id="view-settings">
      <div className="page-head">
        <div>
          <h1 className="title">
            <em>Settings</em>
          </h1>
          <div className="sub">WORKSPACE · MAX@SKORPIO.AI</div>
        </div>
      </div>

      <div className="reports" style={{ maxWidth: 760 }}>
        <table>
          <tbody>
            <tr><td className="label" style={{ width: 240 }}>Default region</td><td>Ontario · IESO</td><td className="action"><a href="#">Edit ›</a></td></tr>
            <tr><td className="label">Units</td><td>Metric · Canadian English</td><td className="action"><a href="#">Edit ›</a></td></tr>
            <tr><td className="label">Notifications</td><td>Email · alimximln@gmail.com</td><td className="action"><a href="#">Edit ›</a></td></tr>
            <tr><td className="label">Plan</td><td>Pro · seats 4 / 8</td><td className="action"><a href="#">Manage ›</a></td></tr>
            <tr><td className="label">API keys</td><td>2 active</td><td className="action"><a href="#">Manage ›</a></td></tr>
          </tbody>
        </table>
      </div>

      <div className="page-head" style={{ marginTop: 32 }}>
        <div>
          <h2 className="title" style={{ fontSize: 24 }}>
            <em>Pipelines</em>
          </h2>
          <div className="sub">PER-CAPABILITY DEFAULTS</div>
        </div>
      </div>

      <div className="reports" style={{ maxWidth: 760 }}>
        <table>
          <tbody>
            {PIPELINES.map((p) => (
              <tr key={p.id}>
                <td className="label" style={{ width: 240 }}>
                  <span
                    className="pipeline-badge"
                    style={{
                      color: p.accent,
                      borderColor: p.accent + '55',
                      background: p.accent + '12',
                    }}
                  >
                    <span className="pipeline-dot" style={{ background: p.accent }} />
                    {p.label}
                  </span>
                </td>
                <td>Enabled</td>
                <td className="action"><a href="#">Configure ›</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
