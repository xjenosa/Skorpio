import { FormEvent, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { ChatMessage, ClaudeModel } from '../api/types'
import { pipelineById, type PipelineId } from '../pipelines'
import { useDemoMode } from '../hooks/useDemoMode'
import { PipelineTagPicker } from './PipelineTagPicker'
import { renderMarkdown } from './reportMarkdown'
import './ReportChatBar.css'

// Sticky chat textbox pinned to the bottom of every individual report page.
// Visually mirrors the New session composer (textarea + model picker + send),
// but the routing slot is replaced by a static badge that reflects which
// pipeline this report belongs to — the conversation is grounded in that
// report's data, so there's nothing to "route" here.

const MODEL_OPTIONS: Array<{ id: ClaudeModel; label: string; sub: string }> = [
  { id: 'claude-sonnet-4-6', label: 'Sonnet 4.6', sub: 'Balanced · default' },
  { id: 'claude-opus-4-7', label: 'Opus 4.7', sub: 'Highest reasoning · slower' },
  { id: 'claude-haiku-4-5-20251001', label: 'Haiku 4.5', sub: 'Fastest · cheapest' },
]
const MODEL_STORAGE_KEY = 'skorpio.model'

// Surfaced as the error pill above the composer when the user clicks
// send (or hits Enter) with an empty textbox. Tone and shape mirror
// the NewSession composer's "Describe your scenario in a sentence."
// message so the two surfaces feel like one product. The exact text
// is stored as a constant so the pill-row render check can identify
// THIS error specifically and style it as a pill, leaving other
// errors (stream failures, etc.) to render in the inline error slot.
const EMPTY_PROMPT_MESSAGE =
  'Describe your follow-up in a sentence. Try one of the starter chips.'

// Chat threads are persisted per-job to localStorage so revisiting a
// completed report restores the conversation the user was having. Key
// shape matches `skorpio.chat.<job_id>`; the "Clear conversation" button
// wipes both state and the stored copy. Reset on navigation away would
// feel like data loss when the user might step away mid-conversation
// (scroll the report, hop tabs) and come back expecting their context.
const CHAT_STORAGE_PREFIX = 'skorpio.chat.'

function chatStorageKey(jobId: string): string {
  return `${CHAT_STORAGE_PREFIX}${jobId}`
}

function loadStoredModel(): ClaudeModel {
  if (typeof window === 'undefined') return 'claude-sonnet-4-6'
  const stored = window.localStorage.getItem(MODEL_STORAGE_KEY)
  if (stored && MODEL_OPTIONS.some((m) => m.id === stored)) {
    return stored as ClaudeModel
  }
  return 'claude-sonnet-4-6'
}

function loadStoredMessages(jobId: string): ChatMessage[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(chatStorageKey(jobId))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    // Drop the last entry if it's an empty assistant placeholder — that
    // indicates the user navigated away mid-stream and the assistant
    // slot never got filled. Restoring an empty bubble looks broken.
    const cleaned = parsed.filter(
      (m): m is ChatMessage =>
        m && typeof m.role === 'string' && typeof m.content === 'string',
    )
    while (
      cleaned.length > 0 &&
      cleaned[cleaned.length - 1].role === 'assistant' &&
      cleaned[cleaned.length - 1].content.trim() === ''
    ) {
      cleaned.pop()
    }
    return cleaned
  } catch {
    return []
  }
}

interface ReportChatBarProps {
  jobId: string
  pipelineId: PipelineId
  /** When provided, the topic pill becomes a pipeline-routing dropdown so the
   *  user can re-tag the job from inside the chat composer. When omitted, the
   *  pill stays a static badge. This is where the old "Routed to · change"
   *  control lives now — the report header no longer carries it. */
  onPipelineChange?: (pipelineId: PipelineId) => void
}

export function ReportChatBar({ jobId, pipelineId, onPipelineChange }: ReportChatBarProps) {
  const meta = pipelineById(pipelineId)
  const [demo] = useDemoMode()
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState<ClaudeModel>(loadStoredModel)
  const [modelOpen, setModelOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [threadOpen, setThreadOpen] = useState(false)
  const modelRef = useRef<HTMLDivElement>(null)
  const threadRef = useRef<HTMLDivElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)
  // True for the single save-effect run that fires immediately after a
  // hydration. Without it the save effect runs once with the still-stale
  // `messages = []` from initial state and wipes localStorage[jobId]
  // before the queued `setMessages(stored)` is applied. Restored on the
  // next effect cycle, but the brief wipe was racing the user's
  // navigation away and intermittently leaving the key empty.
  const isHydratingRef = useRef(true)

  // Hydrate from localStorage whenever the user navigates to a different
  // job — each job has its own thread so context never leaks across runs,
  // and a thread persists across navigations / refreshes within one job.
  // The thread is ALWAYS collapsed on navigation, even when prior messages
  // exist — landing on an old report and immediately seeing the previous
  // conversation expanded was disorienting; the operator now sees the
  // report first and clicks "show conversation · N" to open the history.
  useEffect(() => {
    isHydratingRef.current = true
    const stored = loadStoredMessages(jobId)
    setMessages(stored)
    setError(null)
    setThreadOpen(false)
    setPrompt('')
  }, [jobId])

  // Persist the thread whenever it changes — but only when we're not
  // mid-stream, so we never write a half-filled assistant bubble. After
  // the stream completes, `streaming` flips false and this effect fires
  // once with the final state.
  useEffect(() => {
    if (isHydratingRef.current) {
      // First fire after hydration: skip writing because `messages` is
      // still the stale pre-hydration value in this closure. The next
      // run (triggered when the queued setMessages applies) will save
      // with the correct messages.
      isHydratingRef.current = false
      return
    }
    if (typeof window === 'undefined') return
    if (streaming) return
    const key = chatStorageKey(jobId)
    if (messages.length === 0) {
      window.localStorage.removeItem(key)
      return
    }
    try {
      window.localStorage.setItem(key, JSON.stringify(messages))
    } catch {
      // Quota exceeded or storage disabled — fail silently rather than
      // breaking the chat for a persistence-layer hiccup.
    }
  }, [jobId, messages, streaming])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(MODEL_STORAGE_KEY, model)
  }, [model])

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

  // Auto-scroll the thread to the latest message as it streams.
  useEffect(() => {
    if (!threadRef.current) return
    threadRef.current.scrollTop = threadRef.current.scrollHeight
  }, [messages, streaming])

  // Auto-grow the textarea up to the CSS max-height.
  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
  }, [prompt])

  const activeModel = MODEL_OPTIONS.find((m) => m.id === model) ?? MODEL_OPTIONS[0]

  // Shared send path used by the form submit AND the starter-chip clicks.
  // Pulled out of onSubmit so chips don't have to synthesize a fake
  // FormEvent; they call this directly with the chip text.
  const sendPrompt = async (text: string) => {
    const trimmed = text.trim()
    if (streaming) return
    if (!trimmed) {
      // Surface a visible error pill above the composer, matching the
      // NewSession "Describe your scenario in a sentence." pattern in
      // tone and colour. The pill is cleared as soon as the user starts
      // typing (see textarea onChange below).
      setError(EMPTY_PROMPT_MESSAGE)
      return
    }

    const next: ChatMessage[] = [...messages, { role: 'user', content: trimmed }]
    setMessages(next)
    setPrompt('')
    setError(null)
    setStreaming(true)
    setThreadOpen(true)

    // Reserve the assistant slot so streaming chunks append into a stable
    // index instead of racing each other.
    const assistantIndex = next.length
    setMessages((m) => [...m, { role: 'assistant', content: '' }])

    try {
      await api.chatStream(
        jobId,
        next,
        model,
        (chunk) => {
          setMessages((m) => {
            const out = [...m]
            if (out[assistantIndex]) {
              out[assistantIndex] = {
                ...out[assistantIndex],
                content: out[assistantIndex].content + chunk,
              }
            }
            return out
          })
        },
        // Post-stream reconciliation: backend caught Claude quoting a
        // number that drifted >5% from the report's source-of-truth and
        // emitted the corrected full text. Replace the streamed content
        // so the user never sees the hallucinated value persist.
        (corrected) => {
          setMessages((m) => {
            const out = [...m]
            if (out[assistantIndex]) {
              out[assistantIndex] = {
                ...out[assistantIndex],
                content: corrected,
              }
            }
            return out
          })
        },
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setStreaming(false)
    }
  }

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    await sendPrompt(prompt)
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Cmd/Ctrl+Enter or plain Enter (no Shift) submits, matching Claude's UX.
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      const form = (e.currentTarget.form as HTMLFormElement | null) ?? null
      form?.requestSubmit()
    }
  }

  const clearThread = () => {
    setMessages([])
    setError(null)
    setThreadOpen(false)
    // The save effect above also removes the entry when messages becomes
    // empty, but clearing here too keeps the localStorage key out of the
    // small race window where the persist effect hasn't fired yet.
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(chatStorageKey(jobId))
    }
  }

  return (
    <div className="report-chatbar-shell">
      <div className="report-chatbar-inner">
        {threadOpen && messages.length > 0 && (
          <div className="report-chatbar-thread" ref={threadRef}>
            <div className="report-chatbar-thread-head">
              <span className="t-eyebrow">Follow-up · grounded in this report</span>
              <div className="report-chatbar-thread-actions">
                <button
                  type="button"
                  className="report-chatbar-thread-close"
                  onClick={clearThread}
                  aria-label="Clear conversation"
                  title="Clear conversation"
                >
                  clear
                </button>
                <button
                  type="button"
                  className="report-chatbar-thread-hide"
                  onClick={() => setThreadOpen(false)}
                  aria-label="Hide conversation"
                  title="Hide conversation (messages stay saved)"
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M6 9l6 6 6-6" />
                  </svg>
                </button>
              </div>
            </div>
            {messages.map((m, i) => (
              <div
                key={i}
                className={`report-chatbar-msg report-chatbar-msg--${m.role}`}
              >
                <span className="report-chatbar-msg-role">
                  {m.role === 'user' ? 'You' : 'Skorpio'}
                </span>
                <div className="report-chatbar-msg-body">
                  {m.content
                    ? (m.role === 'assistant' ? renderMarkdown(m.content) : m.content)
                    : (streaming && i === messages.length - 1 ? <em className="report-chatbar-typing">…thinking</em> : '')}
                </div>
              </div>
            ))}
            {error && <div className="report-chatbar-error">{error}</div>}
          </div>
        )}

        {/* Pill row sitting directly above the composer. Holds two
            independent pills that share one vertical band:
              · Left: the empty-prompt error pill. Only appears AFTER
                the user clicks send (or hits Enter) with an empty
                textbox — it's a correction, not a permanent tip. Tone
                and colour mirror the NewSession composer's "Describe
                your scenario in a sentence." pattern so both surfaces
                feel like one product.
              · Right: "show conversation · N" toggle that re-opens the
                hidden thread. Counts USER PROMPTS only (`role: 'user'`)
                so a 2-turn conversation reads as 2, not 4 — the
                previous count totalled user + assistant turns, which
                read as inflated.
            The wrapping flex row reserves the vertical space whether
            zero, one, or both pills are present, so the composer below
            doesn't shift up when the right pill toggles. */}
        {(() => {
          const userPromptCount = messages.filter((m) => m.role === 'user').length
          const showEmptyError = error === EMPTY_PROMPT_MESSAGE
          const showThreadPill = !threadOpen && messages.length > 0
          if (!showEmptyError && !showThreadPill) return null
          return (
            <div className="report-chatbar-pill-row">
              {showEmptyError ? (
                <span className="report-chatbar-empty-error" role="alert" aria-live="polite">
                  {EMPTY_PROMPT_MESSAGE}
                </span>
              ) : (
                <span />
              )}
              {showThreadPill && (
                <button
                  type="button"
                  className="report-chatbar-thread-show"
                  onClick={() => setThreadOpen(true)}
                  title="Show hidden conversation"
                >
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d="M18 15l-6-6-6 6" />
                  </svg>
                  show conversation · {userPromptCount}
                </button>
              )}
            </div>
          )
        })()}

        {demo ? (
          <div
            className="report-chatbar-demo-notice"
            role="status"
            aria-live="polite"
            style={{
              padding: '14px 18px',
              border: '1px solid rgba(243, 135, 100, 0.35)',
              borderRadius: 10,
              background: 'rgba(243, 135, 100, 0.08)',
              color: 'var(--fg-2, #cfcbc6)',
              fontSize: 13,
              lineHeight: 1.5,
              display: 'flex',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <span
              aria-hidden="true"
              style={{
                display: 'inline-block',
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: '#F38764',
                flexShrink: 0,
              }}
            />
            <span>
              <strong style={{ color: '#F38764' }}>Demo preview</strong> ·
              Follow-up chat is disabled in demo mode. See this feature
              live during the in-person demo.
            </span>
          </div>
        ) : (
        <form className="composer report-chatbar-composer" onSubmit={onSubmit} noValidate>
          <textarea
            ref={taRef}
            rows={1}
            placeholder={
              meta
                ? `Ask a follow-up about this ${meta.short.toLowerCase()} report…`
                : 'Ask a follow-up about this report…'
            }
            value={prompt}
            onChange={(e) => {
              setPrompt(e.target.value)
              // Clear the empty-prompt error the moment the user starts
              // typing again. Keeps the error from persisting after the
              // user has obviously fixed it. Other errors (stream
              // failures) are left alone since typing doesn't resolve
              // them.
              if (error === EMPTY_PROMPT_MESSAGE) setError(null)
            }}
            onKeyDown={onKeyDown}
            disabled={streaming}
          />
          <div className="composer-row">
            {meta && onPipelineChange && (
              <PipelineTagPicker
                current={pipelineId}
                onSelect={(pid) => {
                  if (pid !== pipelineId) onPipelineChange(pid)
                }}
                wrapperClassName="report-chatbar-topic-picker"
                renderTrigger={({ open, toggle, triggerRef }) => (
                  <button
                    ref={triggerRef}
                    type="button"
                    className="report-chatbar-topic report-chatbar-topic--button"
                    aria-haspopup="listbox"
                    aria-expanded={open}
                    onClick={toggle}
                    title={`Routed to ${meta.label}. Click to re-tag.`}
                    // Tinted background + border in the pipeline's accent
                    // colour so the pill matches the routing pill in the
                    // Agent Pipeline page header and the Reports table
                    // badges. `accent + '12'` ≈ 7% alpha fill;
                    // `accent + '55'` ≈ 33% alpha border.
                    style={{
                      color: meta.accent,
                      background: meta.accent + '12',
                      borderColor: meta.accent + '55',
                    }}
                  >
                    <span
                      className="report-chatbar-topic-dot"
                      style={{ background: meta.accent }}
                    />
                    <span style={{ color: meta.accent }}>{meta.short}</span>
                    <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M6 9l6 6 6-6" />
                    </svg>
                  </button>
                )}
              />
            )}
            {meta && !onPipelineChange && (
              <span
                className="report-chatbar-topic"
                title={`Conversation grounded in this ${meta.label} report`}
                style={{
                  color: meta.accent,
                  background: meta.accent + '12',
                  borderColor: meta.accent + '55',
                }}
              >
                <span
                  className="report-chatbar-topic-dot"
                  style={{ background: meta.accent }}
                />
                <span style={{ color: meta.accent }}>{meta.short}</span>
              </span>
            )}
            {/* Starter chips — always visible (no longer cold-start only).
                When present they REPLACE the spacer: the chip strip is
                `flex: 1` and centers its contents, so the topic pill
                stays left and the model picker stays right while the
                chips sit between them. Clicking a chip FILLS the
                textbox with the question and focuses it — the user
                can edit and then send. Auto-submitting on click felt
                jarring because it skipped the "I'm in control of what
                gets sent" step. */}
            {meta && meta.chatStarters.length > 0 ? (
              <div
                className="report-chatbar-starters"
                aria-label="Suggested follow-up questions"
              >
                {meta.chatStarters.map((q, i) => (
                  <button
                    key={i}
                    type="button"
                    className="report-chatbar-starter"
                    onClick={() => {
                      setPrompt(q)
                      // Defer focus so the new prompt value is applied
                      // first; otherwise the cursor lands in an empty
                      // textarea and the user has to click again.
                      requestAnimationFrame(() => taRef.current?.focus())
                    }}
                    disabled={streaming}
                    style={{
                      borderColor: meta.accent + '55',
                      color: meta.accent,
                    }}
                    title="Click to fill the composer (edit, then press Enter to send)"
                  >
                    {q}
                  </button>
                ))}
              </div>
            ) : (
              <span className="spacer" />
            )}

            <div className="model-picker" ref={modelRef}>
              <button
                className="model-pill"
                type="button"
                aria-haspopup="listbox"
                aria-expanded={modelOpen}
                onClick={() => setModelOpen((o) => !o)}
                disabled={streaming}
              >
                Skorpio · {activeModel.label}
                <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M6 9l6 6 6-6" />
                </svg>
              </button>
              {modelOpen && (
                <ul className="model-menu report-chatbar-model-menu" role="listbox" aria-label="Claude model">
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
              aria-label="Send follow-up"
              title="Send follow-up"
              // Stay enabled even when the textbox is empty so the
              // click reaches onSubmit → sendPrompt, which surfaces the
              // "Describe your follow-up in a sentence" error pill.
              // Only the streaming state truly blocks the action;
              // empty-prompt validation is now an explicit pill, not
              // an unclickable button.
              disabled={streaming}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14" />
                <path d="M13 6l6 6-6 6" />
              </svg>
            </button>
          </div>
        </form>
        )}
      </div>
    </div>
  )
}
