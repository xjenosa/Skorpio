import { useEffect, useState } from 'react'
import type { PipelineStage, StreamEvent } from '../api/types'
import { isFixtureJobId, loadDemoJobStatus } from '../demo/fixturesLoader'

const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export interface LogLine {
  ts: string
  level: 'info' | 'ok' | 'warn' | 'error'
  text: string
}

export interface JobStreamState {
  stage: PipelineStage
  progress: number
  message: string
  log: LogLine[]
  error: string | null
  closed: boolean
  paused: boolean
}

const INITIAL: JobStreamState = {
  stage: 'queued',
  progress: 0,
  message: '',
  log: [],
  error: null,
  closed: false,
  paused: false,
}

function nowHMS() {
  const d = new Date()
  return d.toTimeString().slice(0, 8)
}

export function useJobStream(jobId: string | undefined): JobStreamState {
  const [state, setState] = useState<JobStreamState>(INITIAL)

  useEffect(() => {
    if (!jobId) return

    // Fixture-backed job: synthesize the terminal stream state from the
    // fixture's persisted job_status instead of opening SSE. Fires in any
    // mode (not just demo) so the empty-state Sample run on the Agent
    // Pipeline tab also works outside demo. On Vercel there's no backend
    // so SSE would error out and leave the stream stuck at INITIAL
    // ('queued', 0%), which then breaks every downstream check gated on
    // stream.stage === 'completed' (siting plan fetch, stage card
    // unlocking, Reports table status, etc.).
    if (isFixtureJobId(jobId)) {
      const status = loadDemoJobStatus(jobId)
      if (status) {
        setState({
          stage: status.stage,
          progress: status.progress,
          message: status.message ?? '',
          log: [],
          error: status.error,
          closed: true,
          paused: false,
        })
        return
      }
    }

    setState(INITIAL)

    const es = new EventSource(`${BASE_URL}/api/stream/${jobId}`)

    es.onmessage = (ev) => {
      let data: StreamEvent
      try {
        data = JSON.parse(ev.data) as StreamEvent
      } catch {
        return
      }
      setState((prev) => {
        const next: JobStreamState = { ...prev }
        if (data.stage) next.stage = data.stage
        if (typeof data.progress === 'number') next.progress = data.progress
        // Backend polls and re-emits the same payload every 500ms — only
        // append a log line when the message text actually changes.
        if (data.message && data.message !== prev.message) {
          next.message = data.message
          const level: LogLine['level'] =
            data.stage === 'failed'
              ? 'error'
              : data.stage === 'completed'
                ? 'ok'
                : 'info'
          next.log = [...prev.log, { ts: nowHMS(), level, text: data.message }]
        }
        if (data.error) next.error = data.error
        if (typeof data.paused === 'boolean') next.paused = data.paused
        if (data.stage === 'completed' || data.stage === 'failed') {
          next.closed = true
        }
        return next
      })
    }

    es.onerror = () => {
      setState((prev) => ({ ...prev, closed: true }))
      es.close()
    }

    return () => es.close()
  }, [jobId])

  return state
}
