// Pipeline catalog. Single source of truth for the 5 capabilities Skorpio
// exposes through the router-style composer. Used by:
//   - composer placeholder (random pick from `examples`)
//   - composer suggestion chips (one example per pipeline)
//   - reports table (pipeline badge per row)
//   - capabilities/dashboard surfaces
//
// When the backend router lands, the `id` here will be what the router emits
// in the job metadata so the UI can map back to label/color.

export type PipelineId =
  | 'datacenter-siting'
  | 'datacenter-expansion'
  | 'winter-peak-stress'
  | 'electrification-readiness'
  | 'grid-investment-optimizer'

export interface PipelineMeta {
  id: PipelineId
  label: string
  short: string
  blurb: string
  accent: string
  examples: string[]
  // Short follow-up questions surfaced as chips in the report chatbar
  // when the thread is empty. Shape mirrors the preferred chat voice
  // (terse, verdict-seeking, jargon allowed) — clicking one fills the
  // composer and submits. Two per pipeline keeps the chip row compact
  // and forces every chip to be obviously valuable.
  chatStarters: string[]
}

export const PIPELINES: PipelineMeta[] = [
  {
    id: 'datacenter-siting',
    label: 'Datacenter Siting',
    short: 'Siting',
    blurb: 'Place new AI/HPC capacity by carbon, latency, and cost.',
    accent: '#f38764',
    examples: [
      "Find the best site for a 75 MW AI training cluster in Alectra's service territory, lowest carbon.",
      'Where should I site a 120 MW inference datacenter in southern Ontario with sub-15 ms latency to Toronto?',
      'Score 5 candidate sites near Mississauga for a 200 MW HPC build, prioritize hydro.',
    ],
    chatStarters: [
      'Why is the top site ranked first?',
      'What is the biggest risk on the top site?',
    ],
  },
  {
    id: 'datacenter-expansion',
    label: 'Expansion Planner',
    short: 'Expansion',
    blurb: 'Plan next-phase capacity at existing datacenter sites.',
    accent: '#7aa2f7',
    examples: [
      'Plan 30 MW of expansion at our Vaughan datacenter, 18-month horizon.',
      'I have a 20 MW campus in Markham. Show me the cheapest path to 80 MW.',
      'How much can I grow our Brampton site without a new substation?',
    ],
    chatStarters: [
      "What is driving the top option's ranking?",
      'What blocks the top option from deploying faster?',
    ],
  },
  {
    id: 'winter-peak-stress',
    label: 'Winter Peak Stress Tester',
    short: 'Winter Stress',
    blurb: 'Simulate extreme cold on a regional grid: heat pump COP loss, EV cold-weather draw, baseboard spikes.',
    accent: '#6fcf8e',
    examples: [
      "Will Mississauga's grid hold a -25°C polar vortex with 30% heat pump adoption?",
      "Stress-test Mississauga's feeders for a 5-day cold snap with 50% heat pumps by 2030.",
      'How does a -30°C event affect EV charging load in Mississauga?',
    ],
    chatStarters: [
      'What if heat pump adoption hits 50%?',
      'Which upgrade gives us the most resilience per dollar?',
    ],
  },
  {
    id: 'electrification-readiness',
    label: 'Electrification Readiness',
    short: 'Electrification',
    blurb: 'Score a Canadian neighborhood on how ready it is for EV + heat pump growth.',
    accent: '#e0a44a',
    examples: [
      'Score Mississauga (L5B) for EV and heat pump growth through 2030.',
      'Rank Brampton FSAs by electrification readiness.',
      'Which Vaughan FSAs need transformer upgrades first under heat pump adoption?',
    ],
    chatStarters: [
      'Which FSA is the worst-ready and why?',
      'What single intervention unlocks the most households?',
    ],
  },
  {
    id: 'grid-investment-optimizer',
    label: 'Grid Investment Optimizer',
    short: 'Investment',
    blurb: 'Allocate a budget across grid upgrades for resilience ROI under climate scenarios.',
    accent: '#c889e6',
    examples: [
      'How should Alectra spend $50M to maximize 2050 climate resilience in Mississauga?',
      "Optimize a $200M investment plan for Alectra's GTHA feeders.",
      'Recommend grid upgrades for Alectra under a 2°C warming scenario.',
    ],
    chatStarters: [
      'Which funded project has the best ROI?',
      'What gets unlocked if the budget doubles?',
    ],
  },
]

export function pipelineById(id: PipelineId | string | undefined): PipelineMeta | undefined {
  if (!id) return undefined
  return PIPELINES.find((p) => p.id === id)
}

// Flatten all examples for the randomized placeholder. Picking from this pool
// means the placeholder advertises the full breadth of the agent, not just one
// pipeline.
export const ALL_EXAMPLES: string[] = PIPELINES.flatMap((p) => p.examples)

export function randomExample(): string {
  return ALL_EXAMPLES[Math.floor(Math.random() * ALL_EXAMPLES.length)]
}
