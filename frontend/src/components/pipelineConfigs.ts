import type { PipelineStage } from '../api/types'
import type { PipelineId } from '../pipelines'

// Per-pipeline UI metadata. PipelineLive looks up the relevant config from
// here based on the pipelineId of the running job, and renders the matching
// stage cards + per-stage viz. Adding a new pipeline = adding an entry here
// (plus the corresponding viz components).
//
// Keep stage names in sync with backend/models/report.py PipelineStage enum
// and the orchestrator stages it emits.

export interface PipelineStageConfig {
  /** Backend stage value emitted via crud.update_progress(stage=...). */
  stage: PipelineStage
  /** Stage card label (e.g. "01 · Workload Intelligence"). */
  label: string
  /** One-sentence description shown under the label. */
  description: string
}

export interface PipelineConfig {
  /** Ordered list of stages this pipeline emits, mapped to UI metadata. */
  stages: PipelineStageConfig[]
}

// Datacenter Siting — the original 5-stage pipeline.
// Labels follow the cross-pipeline convention:
//   01 · Workload Intelligence → 02 · [Domain] → 03 · [Modeling] →
//   04 · [Scoring] → 05 · Plan Synthesis
const SITING: PipelineConfig = {
  stages: [
    {
      stage: 'grid_analysis',
      label: '01 · Workload Intelligence',
      description: 'Parse the workload (capacity target, latency budget, region preferences) from the question, then pull grid telemetry, energy pricing, weather, and carbon intensity.',
    },
    {
      stage: 'region_discovery',
      label: '02 · Grid Intelligence',
      description: 'Filter candidate regions by transmission access, cooling feasibility, water, and policy posture.',
    },
    {
      stage: 'site_generation',
      label: '03 · Site Generation',
      description: 'Generate optimized datacenter layouts: cooling systems, renewable mix, and grid interaction.',
    },
    {
      stage: 'scoring',
      label: '04 · Site Scoring',
      description: 'Score every site against the workload on cost, carbon, latency, headroom, speed, and resilience.',
    },
    {
      stage: 'plan_synthesis',
      label: '05 · Plan Synthesis',
      description: 'Bring it together as a ranked siting report: top candidates, region context, methodology, caveats.',
    },
  ],
}

// Winter Peak Stress Tester — labels + descriptions lifted from the
// presentation/skorpio script.txt narration so the live UI matches the demo.
const WINTER_PEAK: PipelineConfig = {
  stages: [
    {
      stage: 'winter_workload',
      label: '01 · Workload Intelligence',
      description: 'Pull the scenario from the question: region, cold event, heat pump adoption, time horizon.',
    },
    {
      stage: 'winter_grid',
      label: '02 · Grid Intelligence',
      description: "Load the city's distribution network: feeders, substations, and baseline winter load.",
    },
    {
      stage: 'cold_event_sim',
      label: '03 · Cold-Event Simulation',
      description: 'Model what the cold weather does to demand: heat pump COP loss, baseboard spikes, EV cold draw.',
    },
    {
      stage: 'feeder_risk',
      label: '04 · Risk Scoring',
      description: 'Rank every feeder and substation on overload risk, voltage sag, and time-to-failure.',
    },
    {
      stage: 'winter_synthesis',
      label: '05 · Plan Synthesis',
      description: 'Bring it together as a clean resilience report: peak demand, at-risk assets, mitigations.',
    },
  ],
}

// Neighborhood Electrification Readiness — 5 stages mirroring Winter Peak.
const ELECTRIFICATION: PipelineConfig = {
  stages: [
    {
      stage: 'electrification_workload',
      label: '01 · Workload Intelligence',
      description: 'Pull the scope from the question: city, FSAs, scenarios, target year.',
    },
    {
      stage: 'neighborhood_profile',
      label: '02 · Neighborhood Profile',
      description: 'Fetch demographics, housing stock, and heating mix per FSA from StatsCan + ECCC.',
    },
    {
      stage: 'adoption_modeling',
      label: '03 · Adoption Modeling',
      description: 'Project the new electric load (heat pump conversions and EV charging) per FSA × scenario.',
    },
    {
      stage: 'readiness_scoring',
      label: '04 · Readiness Scoring',
      description: 'Score grid headroom, building suitability, affordability, and policy support.',
    },
    {
      stage: 'electrification_synthesis',
      label: '05 · Plan Synthesis',
      description: 'Combine into a readiness report with verdicts and recommended interventions.',
    },
  ],
}

// Climate-Adapted Grid Investment Optimizer.
const INVESTMENT: PipelineConfig = {
  stages: [
    {
      stage: 'investment_workload',
      label: '01 · Workload Intelligence',
      description: 'Parse utility, budget, horizon, and priority hazards from the request.',
    },
    {
      stage: 'asset_catalog',
      label: '02 · Asset Catalog',
      description: "Load the utility's at-risk grid assets: substations, lines, feeders, transformers.",
    },
    {
      stage: 'climate_risk_modeling',
      label: '03 · Climate Risk Modeling',
      description: 'Project hazard exposure per asset under the target year (CCCS-scaled).',
    },
    {
      stage: 'portfolio_optimization',
      label: '04 · Portfolio Optimization',
      description: 'Generate candidate hardening projects and run a greedy ROI knapsack against the budget.',
    },
    {
      stage: 'investment_synthesis',
      label: '05 · Plan Synthesis',
      description: 'Bring it together as a board-ready investment plan with avoided-loss totals.',
    },
  ],
}

// Datacenter Expansion Planner.
const EXPANSION: PipelineConfig = {
  stages: [
    {
      stage: 'expansion_workload',
      label: '01 · Workload Intelligence',
      description: 'Parse operator, target MW, horizon, and workload mix from the request.',
    },
    {
      stage: 'operator_footprint',
      label: '02 · Operator Footprint',
      description: 'Load the operator\'s existing sites and enrich each with live grid carbon intensity.',
    },
    {
      stage: 'demand_forecast',
      label: '03 · Demand Forecast',
      description: 'Project annual MW demand under the chosen workload mix and CAGR.',
    },
    {
      stage: 'expansion_scoring',
      label: '04 · Expansion Scoring',
      description: 'Generate brownfield + greenfield candidates and score on grid, sustainability, speed, cost, risk.',
    },
    {
      stage: 'expansion_synthesis',
      label: '05 · Plan Synthesis',
      description: 'Bring it together as a phased rollout: funded options, capex, blended carbon, coverage.',
    },
  ],
}

const CONFIGS: Record<PipelineId, PipelineConfig> = {
  'datacenter-siting': SITING,
  'winter-peak-stress': WINTER_PEAK,
  'electrification-readiness': ELECTRIFICATION,
  'grid-investment-optimizer': INVESTMENT,
  'datacenter-expansion': EXPANSION,
}

export function configForPipeline(pipelineId: string | undefined | null): PipelineConfig {
  if (!pipelineId) return SITING
  return CONFIGS[pipelineId as PipelineId] ?? SITING
}

/** Lookup helpers used by PipelineLive. */
export function stageOrder(pipelineId: string | undefined | null): PipelineStage[] {
  return configForPipeline(pipelineId).stages.map((s) => s.stage)
}

export function stageLabel(pipelineId: string | undefined | null, stage: PipelineStage): string {
  const cfg = configForPipeline(pipelineId)
  const found = cfg.stages.find((s) => s.stage === stage)
  if (found) return found.label
  // Lifecycle states not in the per-pipeline config
  if (stage === 'queued') return 'Queued'
  if (stage === 'completed') return 'Completed'
  if (stage === 'failed') return 'Failed'
  return stage
}

export function stageDescription(pipelineId: string | undefined | null, stage: PipelineStage): string {
  const cfg = configForPipeline(pipelineId)
  const found = cfg.stages.find((s) => s.stage === stage)
  if (found) return found.description
  if (stage === 'queued') return 'Waiting to start.'
  if (stage === 'completed') return 'Pipeline finished.'
  if (stage === 'failed') return 'Pipeline failed.'
  return ''
}
