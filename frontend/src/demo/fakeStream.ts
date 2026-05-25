// Adapter hook that surfaces a single pipeline's theater state in the same
// shape as `useJobStream` (so PipelineLive can swap them transparently).
//
// All real progression logic — timers, stage advancement, log lines, the
// per-pipeline duration table — lives in `theaterManager.ts`. This hook
// just (1) ensures the theater is running for the given pipeline and (2)
// subscribes to its updates so the component re-renders on each tick.
//
// The hook does NOT own the timer: navigating away does not stop progress,
// and coming back doesn't restart it. That's what makes parallel-running
// background demos possible.

import { useEffect, useState } from 'react'
import type { JobStreamState } from '../hooks/useJobStream'
import type { PipelineId } from '../pipelines'
import {
  INITIAL_THEATER_STATE,
  getTheaterState,
  startTheater,
  subscribeTheater,
} from './theaterManager'

export interface UseFakeJobStreamOpts {
  pipelineId: PipelineId | null
  active: boolean
  // onDone is no longer wired here — the theater manager invokes
  // `markFixturePlayed` directly on completion. Accepted for API
  // compatibility with existing call sites.
  onDone?: () => void
}

export function useFakeJobStream({ pipelineId, active }: UseFakeJobStreamOpts): JobStreamState {
  // Cheap force-render counter; subscribeTheater bumps this on each tick.
  const [, force] = useState(0)

  useEffect(() => {
    if (!active || !pipelineId) return
    // Idempotent start: if the theater is already running (operator
    // submitted from the composer and we're now mounting in the report
    // view) this is a no-op and preserves the existing timer.
    startTheater(pipelineId)
    return subscribeTheater(pipelineId, () => force((v) => v + 1))
  }, [active, pipelineId])

  if (!active || !pipelineId) return INITIAL_THEATER_STATE
  return getTheaterState(pipelineId)
}
