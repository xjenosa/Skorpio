// Demo-mode prompt index — one fixed prompt per pipeline.
//
// These are the 5 hand-picked prompts the composer shows as suggestion cards
// when demo mode is on. They match the captured job fixtures under
// `frontend/src/demo/fixtures/<pipeline>/` and stay the same across reloads
// so the operator can rehearse a predictable walkthrough.
//
// Linked job-id prefixes (captured against the live backend, re-captured
// after the §0 data-provenance fixes shipped on 2026-05-18 — prior IDs
// 9dce7ec5 / 335ead0d / 57b8f39f / ce7f3fec / fefe91c6 used stale backend
// logic and were deleted):
//   siting           → a06b5cda
//   expansion        → 0801f572
//   winter-peak      → 476a2f1a
//   electrification  → 331e1dbc
//   investment       → f01f3b45

import type { PipelineId } from '../pipelines'

export interface DemoPrompt {
  pipelineId: PipelineId
  prompt: string
}

// Order = card order in the composer's suggestion grid. Walkthrough order:
// siting → expansion → winter → electrification → investment.
export const DEMO_PROMPTS: DemoPrompt[] = [
  {
    pipelineId: 'datacenter-siting',
    prompt:
      "Find the best site for a 75 MW AI training cluster in Alectra’s service territory, lowest carbon.",
  },
  {
    pipelineId: 'datacenter-expansion',
    prompt: 'Plan 30 MW of expansion at our Vaughan datacenter, 18-month horizon.',
  },
  {
    pipelineId: 'winter-peak-stress',
    prompt:
      "Will Mississauga’s grid hold a -25°C polar vortex with 30% heat pump adoption?",
  },
  {
    pipelineId: 'electrification-readiness',
    prompt:
      'Score Mississauga (L5B) for EV and heat pump growth through 2030.',
  },
  {
    pipelineId: 'grid-investment-optimizer',
    prompt:
      'How should Alectra spend $50M to maximize 2050 climate resilience in Mississauga?',
  },
]

export function demoPromptFor(id: PipelineId): string {
  return DEMO_PROMPTS.find((p) => p.pipelineId === id)?.prompt ?? ''
}
