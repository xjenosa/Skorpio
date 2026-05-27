// Demo-mode prompt index — one fixed prompt per pipeline.
//
// These are the 5 hand-picked prompts the composer shows as suggestion cards
// when demo mode is on. They match the captured job fixtures under
// `frontend/src/demo/fixtures/<pipeline>/` and stay the same across reloads
// so the operator can rehearse a predictable walkthrough.
//
// Linked job-id prefixes (re-captured against the live backend on
// 2026-05-26 after the latest pipeline fixes — feeder load distribution,
// HP physics, expanded cold-event catalog, label cleanup, and the
// inline-chip + threshold-line UI). Source of truth lives in
// `frontend/src/demo/jobs.ts::DEMO_JOB_PREFIXES`:
//   siting           → 49d354bd
//   expansion        → ce0585bf
//   winter-peak      → e5d77262
//   electrification  → f4b26d6a
//   investment       → 2621702d

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
