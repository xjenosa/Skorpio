import { useEffect, useState, type ReactNode } from 'react'
import { usePrintReport } from '../hooks/usePrintReport'
import { PrintReportButton } from './PrintReportButton'
import { ReportChatBar } from './ReportChatBar'
import { renderMarkdown } from './reportMarkdown'
import { pipelineById, type PipelineId } from '../pipelines'
import { api } from '../api/client'
import type { JobStatus } from '../api/types'
import { ProvenanceChips } from './ProvenanceChips'
import { provenanceFor, statusForSource } from './provenance'
import './FinalReport.css'

// Shared shell for every Final report. Owns the page-head + title + Print
// button, the panel-pipeline container, the 3-stat header strip, the
// "Agent runtime" meta line, the 3 winner cards, the 01/02/03 expandable
// section cards (including the print-mode "expand all" behavior), the
// executive summary block (rendered as markdown), and the sticky
// ReportChatBar at the bottom.
//
// Each pipeline-specific report (FinalReport / WinterPeakReport /
// ElectrificationReport / InvestmentReport / ExpansionReport) becomes a
// thin wrapper that fetches its plan and passes structured data into the
// shell. The visible chrome stays identical across all 5; only the labeled
// content changes.

export interface ReportHeaderStat {
  label: string
  value: string | number
}

export interface ReportWinner {
  eyebrow: string
  value: ReactNode
  sub?: ReactNode
  /** Optional color override for the big `value` text (e.g. verdict colors). */
  color?: string
}

export type ReportSectionId = '01' | '02' | '03'

export interface ReportSection {
  id: ReportSectionId
  title: string
  sub: string
  body: ReactNode
}

export interface ReportShellProps {
  jobId: string
  pipelineId: PipelineId
  /** True while the plan is still loading. Renders a "Loading…" panel. */
  loading?: boolean
  loadingLabel?: string
  /** Non-null error message renders a red error panel. */
  error?: string | null
  errorLabel?: string
  headerStats: ReportHeaderStat[]
  /** Agent runtime in seconds. Formatted as "Xm Ys" by the shell. */
  agentRuntimeSeconds: number | null
  winners: ReportWinner[]
  sections: ReportSection[]
  /** Markdown source. Rendered by the shared `renderMarkdown` helper. */
  execSummary?: string | null
  /** External-data citations rendered in a Sources block under the exec summary.
      Empty / undefined hides the block entirely. See REPORTS_COHESION.md §7. */
  sources?: string[] | null
  /** Optional dict of source metadata keyed by short id (`s1`, `s2`, …). When
      the executive summary contains `[[sN|cited text]]` markers, the matching
      entry here drives the hover popover's label, detail, and provenance
      status. Omit to disable citations (markers fall back to plain text). */
  citationSources?: import('./reportMarkdown').CitationSources | null
  onPipelineChange?: (pipelineId: PipelineId) => void
}


// Strip markdown formatting so the clipboard receives clean plain text.
function stripMarkdown(md: string): string {
  return md
    // Unwrap citation markers first so a [[s1|$50M]] copies as "$50M".
    .replace(/\[\[s\w+\|([^\]]+)\]\]/g, '$1')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/_(.+?)_/g, '$1')
    .replace(/`(.+?)`/g, '$1')
    .replace(/^#+\s+/gm, '')
    .replace(/\[(.+?)\]\(.+?\)/g, '$1')
    .replace(/^[-*]\s+/gm, '• ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

// Recursively extract plain text from a ReactNode tree. Used for copying
// winner-card values/subs which may be either strings or small JSX trees.
function nodeToText(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(nodeToText).join('')
  if (typeof node === 'object' && 'props' in node) {
    return nodeToText((node as { props: { children?: ReactNode } }).props.children)
  }
  return ''
}

function formatRuntime(seconds: number | null): string {
  if (seconds == null || !isFinite(seconds) || seconds < 0) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  if (m === 0) return `${s}s`
  return `${m}m ${s}s`
}

// Copy + thumbs-up/down feedback row. Thumbs open a centered modal
// (matching Claude's feedback-dialog pattern); copy button copies the
// full report (header → winners → exec summary → sources) as plain
// text. UI-only — submit is a no-op confirmation, nothing is persisted.
function FeedbackBlock({
  userPrompt,
  pipelineLabel,
  headerStats,
  agentRuntimeSeconds,
  winners,
  execSummary,
  sources,
}: {
  userPrompt: string | null
  pipelineLabel: string
  headerStats: ReportHeaderStat[]
  agentRuntimeSeconds: number | null
  winners: ReportWinner[]
  execSummary?: string | null
  sources?: string[] | null
}) {
  const [vote, setVote] = useState<'up' | 'down' | null>(null)
  const [comment, setComment] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [copied, setCopied] = useState(false)

  const open = vote !== null && !submitted

  // ESC to close the modal
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setVote(null)
        setComment('')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const choose = (v: 'up' | 'down') => {
    // After submitting, clicking any thumb cancels the rating and
    // returns the widget to its neutral state.
    if (submitted) {
      setVote(null)
      setComment('')
      setSubmitted(false)
      return
    }
    setComment('')
    setVote(v)
  }

  const submit = () => {
    setSubmitted(true)
    // intentionally not persisted — UI-only shell for now
  }

  const cancel = () => {
    setVote(null)
    setComment('')
  }

  const copy = async () => {
    const parts: string[] = []
    parts.push(`SKORPIO · ${pipelineLabel.toUpperCase()}`)
    if (userPrompt) {
      parts.push('', `Query: ${userPrompt}`)
    }
    parts.push('')

    if (headerStats.length > 0) {
      parts.push(
        headerStats.map((s) => `${s.label}: ${s.value}`).join('  ·  '),
      )
    }
    if (agentRuntimeSeconds != null) {
      parts.push(`Agent runtime: ${formatRuntime(agentRuntimeSeconds)}`)
    }

    if (winners.length > 0) {
      parts.push('', 'HEADLINES', '')
      winners.forEach((w) => {
        const v = nodeToText(w.value).trim()
        const s = nodeToText(w.sub).trim()
        parts.push(`${w.eyebrow}: ${v}${s ? ` · ${s}` : ''}`)
      })
    }

    if (execSummary) {
      parts.push('', '', 'EXECUTIVE SUMMARY', '', stripMarkdown(execSummary))
    }
    if (sources && sources.length > 0) {
      parts.push('', '', 'SOURCES', '', ...sources.map((s) => `• ${s}`))
    }
    const text = parts.join('\n').trim()
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard write blocked — silent */
    }
  }

  const hasCopyable =
    !!execSummary ||
    (sources != null && sources.length > 0) ||
    winners.length > 0 ||
    headerStats.length > 0

  return (
    <div className="fr-feedback">
      <div className="fr-feedback-row">
        <button
          type="button"
          className={`fr-thumb${copied ? ' active' : ''}`}
          onClick={copy}
          disabled={!hasCopyable}
          aria-label={copied ? 'Copied' : 'Copy executive summary + sources'}
          title={
            copied
              ? 'Copied to clipboard'
              : 'Copy executive summary + sources as plain text'
          }
        >
          {copied ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 6 9 17l-5-5" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
              <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
            </svg>
          )}
        </button>
        <button
          type="button"
          className={`fr-thumb${vote === 'up' ? ' active' : ''}`}
          onClick={() => choose('up')}
          aria-label={submitted ? 'Cancel rating' : 'Helpful'}
          title={submitted ? 'Click to cancel rating' : 'Helpful'}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M7 10v12" />
            <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
          </svg>
        </button>
        <button
          type="button"
          className={`fr-thumb${vote === 'down' ? ' active' : ''}`}
          onClick={() => choose('down')}
          aria-label={submitted ? 'Cancel rating' : 'Not helpful'}
          title={submitted ? 'Click to cancel rating' : 'Not helpful'}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17 14V2" />
            <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
          </svg>
        </button>
      </div>

      {open && (
        <div className="fr-feedback-backdrop" onClick={cancel}>
          <div
            className="fr-feedback-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label={`Give ${vote === 'up' ? 'positive' : 'negative'} feedback`}
          >
            <h3 className="fr-feedback-modal-title">
              Give {vote === 'up' ? 'positive' : 'negative'} feedback
            </h3>
            <div>
              <label
                className="fr-feedback-modal-label"
                htmlFor="fr-feedback-comment"
              >
                Please provide details: (optional)
              </label>
              <textarea
                id="fr-feedback-comment"
                className="fr-feedback-textarea"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder={
                  vote === 'up'
                    ? 'What was satisfying about this report?'
                    : 'What was unsatisfying about this report?'
                }
                rows={3}
                autoFocus
              />
            </div>
            <div className="fr-feedback-modal-actions">
              <button
                type="button"
                className="fr-feedback-submit"
                onClick={submit}
              >
                Submit
              </button>
              <button
                type="button"
                className="fr-feedback-cancel"
                onClick={cancel}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function HeaderRow({
  jobId,
  userPrompt,
  printOnClick,
}: {
  jobId: string
  userPrompt: string | null
  printOnClick: () => void
}) {
  const shortId = jobId.slice(0, 8)
  return (
    <div className="page-head fr-page-head">
      <div>
        <h1 className="title">
          <em>Final</em> report
        </h1>
        {userPrompt && (
          <div className="sub">
            Run · {shortId} · {userPrompt}
          </div>
        )}
      </div>
      <div className="actions">
        <PrintReportButton onClick={printOnClick} />
      </div>
    </div>
  )
}

export function ReportShell({
  jobId,
  pipelineId,
  loading,
  loadingLabel = 'Loading report…',
  error,
  errorLabel = 'Failed to load report',
  headerStats,
  agentRuntimeSeconds,
  winners,
  sections,
  execSummary,
  sources,
  citationSources,
  onPipelineChange,
}: ReportShellProps) {
  const [openSection, setOpenSection] = useState<ReportSectionId | null>(null)
  // Fetch the job so the original user prompt (job.workload_spec) can be
  // rendered at the top of every report. Without it the printed PDF lacks
  // the question that generated the report — making the numbers useless
  // out of context.
  const [job, setJob] = useState<JobStatus | null>(null)
  useEffect(() => {
    let alive = true
    api
      .getJob(jobId)
      .then((j) => {
        if (alive) setJob(j)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [jobId])
  const userPrompt = job?.workload_spec ?? null

  // Print title — matches the Reports row identity (short run id + pipeline
  // tag) so the browser's print dialog and "Save as PDF" filename are
  // recognisable instead of the generic tab title.
  const printTitle = (() => {
    const shortId = jobId.slice(0, 8).toUpperCase()
    const tag = pipelineById(pipelineId)?.short ?? 'Report'
    return `Skorpio ${tag} · ${shortId}`
  })()
  const { printing, print } = usePrintReport(printTitle)
  const toggle = (s: ReportSectionId) =>
    setOpenSection(openSection === s ? null : s)

  if (error) {
    return (
      <>
        <HeaderRow jobId={jobId} userPrompt={userPrompt} printOnClick={print} />
        <div
          className="panel-pipeline fr-panel"
          style={{ padding: 16, color: 'var(--err)' }}
        >
          {errorLabel}: {error}
        </div>
        <ReportChatBar
          jobId={jobId}
          pipelineId={pipelineId}
          onPipelineChange={onPipelineChange}
        />
      </>
    )
  }

  if (loading) {
    return (
      <>
        <HeaderRow jobId={jobId} userPrompt={userPrompt} printOnClick={print} />
        <div
          className="panel-pipeline fr-panel"
          style={{ padding: 16, color: 'var(--fg-3)' }}
        >
          {loadingLabel}
        </div>
        <ReportChatBar
          jobId={jobId}
          pipelineId={pipelineId}
          onPipelineChange={onPipelineChange}
        />
      </>
    )
  }

  return (
    <>
      <HeaderRow jobId={jobId} userPrompt={userPrompt} printOnClick={print} />

      <div className="panel-pipeline fr-panel">
        {/* Header — stats on the left, agent runtime on the right. */}
        <div className="pp-head fr-head">
          <div className="fr-head-stats">
            {headerStats.map((s) => (
              <div className="fr-head-stat" key={s.label}>
                <div className="fr-head-stat-label">{s.label}</div>
                <h2 className="fr-head-stat-value">{s.value}</h2>
              </div>
            ))}
          </div>
          <div className="meta">
            <span>
              Agent runtime{' '}
              <strong>
                {agentRuntimeSeconds != null
                  ? formatRuntime(agentRuntimeSeconds)
                  : '—'}
              </strong>
            </span>
          </div>
        </div>

        {/* Three winner cards. */}
        <div className="fr-winners">
          {winners.map((w, i) => (
            <div className="fr-winner" key={i}>
              <span className="t-eyebrow">{w.eyebrow}</span>
              <strong style={w.color ? { color: w.color } : undefined}>
                {w.value}
              </strong>
              {w.sub != null && <span>{w.sub}</span>}
            </div>
          ))}
        </div>

        {/* Section cards — 01 / 02 / 03 expandable. Print mode forces all
            open so the printed PDF contains every section body. */}
        <div className="stages fr-sections">
          {sections.map((s) => {
            const isOpen = openSection === s.id
            return (
              <div key={s.id} className="fr-section-wrap">
                <button
                  type="button"
                  onClick={() => toggle(s.id)}
                  className={`stage-card${isOpen ? ' open' : ''}`}
                  aria-expanded={isOpen}
                >
                  <span className="corner tl" /><span className="corner tr" />
                  <span className="corner bl" /><span className="corner br" />
                  <span className="num">{s.title}</span>
                  <span className="label">{s.sub}</span>
                  <span className="stage-caret" aria-hidden>
                    {isOpen ? '▾' : '▸'}
                  </span>
                </button>
                {(isOpen || printing) && (
                  <div className="stage-viz fr-section-body">{s.body}</div>
                )}
              </div>
            )
          })}
        </div>

        {/* Executive summary — always rendered with the shared markdown helper. */}
        {execSummary && (
          <div className="fr-exec">
            <div className="t-eyebrow">Executive summary</div>
            <div className="fr-md">{renderMarkdown(execSummary, citationSources ?? undefined)}</div>
          </div>
        )}

        {/* Data provenance chips — at-a-glance color-coded summary of which
            stages of this pipeline ran on live data, frozen snapshots,
            modeled heuristics, or LLM narrative. Derived from pipelineId +
            the citations in `sources` so the chip set reflects what
            actually fired this run (e.g. the ArcGIS GeoEnrichment chip
            only lights up when its citation is present). See
            REPORTS_COHESION.md §7b and `./provenance.ts` for the chip
            definitions per pipeline. */}
        {(() => {
          const chips = provenanceFor(pipelineId, sources ?? [])
          if (chips.length === 0) return null
          return (
            <div className="fr-exec fr-provenance">
              <div className="t-eyebrow">Data provenance</div>
              <ProvenanceChips chips={chips} />
            </div>
          )
        })()}

        {/* Sources — citations to external data the agents pulled from. Each
            line gets a small inline status badge (LIVE / FROZEN / MODELED / LLM)
            so the reader can tell at a glance which provenance category the
            citation belongs to. The badge palette mirrors the chip row above
            via `statusForSource()` substring matching. */}
        {sources && sources.length > 0 && (
          <div className="fr-exec fr-sources">
            <div className="t-eyebrow">Sources</div>
            <ul className="fr-sources-list">
              {sources.map((s, i) => {
                const status = statusForSource(s)
                const label =
                  status === 'live' ? 'LIVE' :
                  status === 'frozen' ? 'FROZEN' :
                  status === 'modeled' ? 'MODELED' : 'LLM'
                return (
                  <li key={i}>
                    <span className={`pc-badge pc-${status}`}>
                      <span className="pc-dot" aria-hidden />
                      {label}
                    </span>
                    <span className="fr-source-text">{s}</span>
                  </li>
                )
              })}
            </ul>
          </div>
        )}

        <FeedbackBlock
          userPrompt={userPrompt}
          pipelineLabel={pipelineById(pipelineId)?.label ?? 'Report'}
          headerStats={headerStats}
          agentRuntimeSeconds={agentRuntimeSeconds}
          winners={winners}
          execSummary={execSummary}
          sources={sources}
        />
      </div>

      <ReportChatBar
        jobId={jobId}
        pipelineId={pipelineId}
        onPipelineChange={onPipelineChange}
      />
    </>
  )
}
