// TS mirrors of backend Pydantic models — keep in sync with backend/models/*.py.

export type PipelineStage =
  // Shared lifecycle states
  | 'queued'
  | 'completed'
  | 'failed'
  // Datacenter Siting stages
  | 'grid_analysis'
  | 'region_discovery'
  | 'site_generation'
  | 'scoring'
  | 'plan_synthesis'
  // Winter Peak Stress Tester stages
  | 'winter_workload'
  | 'winter_grid'
  | 'cold_event_sim'
  | 'feeder_risk'
  | 'winter_synthesis'
  // Neighborhood Electrification Readiness stages
  | 'electrification_workload'
  | 'neighborhood_profile'
  | 'adoption_modeling'
  | 'readiness_scoring'
  | 'electrification_synthesis'
  // Climate-Adapted Grid Investment Optimizer stages
  | 'investment_workload'
  | 'asset_catalog'
  | 'climate_risk_modeling'
  | 'portfolio_optimization'
  | 'investment_synthesis'
  // Datacenter Expansion Planner stages
  | 'expansion_workload'
  | 'operator_footprint'
  | 'demand_forecast'
  | 'expansion_scoring'
  | 'expansion_synthesis'

export interface SiteProfile {
  capacity_mw: number | null
  transmission_headroom_mw: number | null
  pue: number | null
  fiber_latency_ms: number | null
  water_l_per_mwh: number | null
  substation_distance_km: number | null
  spot_lmp_usd_mwh: number | null
  lease_cost_usd_yr: number | null
  meets_constraints: boolean
  overall_score: number | null
  has_policy_blockers: boolean
  has_alerts: boolean
  deployment_months: number | null
}

export interface ParetoObjectives {
  cost_economics: number
  carbon_intensity: number
  latency_fit: number
  transmission_headroom: number
  deployment_speed: number
  operational_resilience: number
  pareto_rank: number
  weighted_score: number
}

export interface Site {
  site_id: string
  name: string
  latitude: number
  longitude: number
  address: string | null
  region_iso: string
  profile: SiteProfile
  pareto_objectives: ParetoObjectives | null
  generation_method: string
  parent_site_id: string | null
  distance_to_known_dc_km: number | null
  nearest_known_operator: string | null
  diversity_cluster: number | null
  rank: number | null
}

export interface GridInteraction {
  facility: string
  interaction_type: string
  distance_km: number | null
  latency_ms: number | null
}

export interface PlacementScore {
  site: Site
  region_iso: string
  topology_id: string
  levelized_cost_usd_mwh: number
  uptime_lb: number | null
  uptime_ub: number | null
  plan_path: string | null
  plan_file: string | null
  topology_file: string | null
  scoring_method: string
  interactions: GridInteraction[]
  rank: number
  explanation: string
}

export interface NewsItem {
  arxiv_id: string
  title: string
  authors: string[]
  summary: string
  published: string
  url: string
  categories: string[]
}

export interface RegionInsight {
  region_iso: string
  market_outlook: string
  transmission_constraints: string
  regulatory_context: string
  top_sites: PlacementScore[]
  news_items: NewsItem[]
  topology_graph: Record<string, unknown> | null
}

export interface SitingPlan {
  job_id: string
  workload_spec: string
  workload_name: string
  workload_description: string
  target_capacity_mw: number
  target_latency_ms: number | null
  candidate_iso_codes: string[]
  executive_summary: string
  regions_analyzed: number
  sites_generated: number
  sites_scored: number
  region_insights: RegionInsight[]
  top_candidates: PlacementScore[]
  safety_flags: string[]
  limitations: string[]
  methodology_notes: string
  generated_at: string
  pipeline_duration_seconds: number | null
  news_items: NewsItem[]
}

// ── API request / response shapes (from backend/main.py) ───────────────── //

// Mirror of ALLOWED_MODELS in backend/main.py — keep in sync.
export type ClaudeModel =
  | 'claude-opus-4-7'
  | 'claude-sonnet-4-6'
  | 'claude-haiku-4-5-20251001'

export interface SiteRequest {
  workload: string
  max_regions?: number
  max_sites?: number
  model?: ClaudeModel
}

export interface SiteResponse {
  job_id: string
  message: string
  stream_url: string
  status_url: string
  results_url: string
}

export interface ProgressLogEntry {
  ts: string
  level: 'info' | 'ok' | 'warn' | 'error'
  text: string
}

export interface JobStatus {
  job_id: string
  workload_spec: string
  stage: PipelineStage
  progress: number
  message: string
  started_at: string | null
  updated_at: string
  error: string | null
  has_results: boolean
  pipeline_id?: string | null
  paused?: boolean
  // Accumulated progress messages over the life of the run. Empty for legacy
  // rows that pre-date the column. Used to replay the live log when reopening
  // a finished report.
  progress_log?: ProgressLogEntry[]
}

export interface JobListItem {
  job_id: string
  workload_spec: string
  stage: PipelineStage
  progress: number
  created_at: string
  // Optional — populated by the backend when known. Pre-router rows leave
  // pipeline_id null; CSV-imported rows carry the import provenance.
  pipeline_id?: string | null
  imported?: boolean
  imported_from_email?: string | null
}

export interface ImportConflict {
  job_id: string
  workload_spec: string
}

export type ImportStrategy = 'skip' | 'overwrite' | 'new'

export interface ImportResult {
  imported: number
  overwritten: number
  skipped: number
  renamed: number
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface StreamEvent {
  stage?: PipelineStage
  progress?: number
  message?: string
  error?: string
  level?: 'info' | 'ok' | 'warn' | 'error'
  paused?: boolean
  [key: string]: unknown
}

// ── Winter Peak Stress Tester (mirror of backend/models/winter_peak.py) ── //

export interface ScenarioPreset {
  name: string
  label: string
  heat_pump_adoption_pct: number
  ev_adoption_pct: number
  description: string
}

export interface WinterPeakSpec {
  query: string
  normalized_name: string
  city: string
  utility: string | null
  province: string
  iso_zone: string | null
  cold_event_id: string
  custom_min_temp_c: number | null
  custom_duration_hours: number | null
  scenarios: ScenarioPreset[]
  horizon_year: number
  context_summary: string
}

export interface HourlyTemperature {
  hour_offset: number
  temp_c: number
  wind_speed_kmh: number
  is_peak_hour: boolean
}

export interface ColdEvent {
  event_id: string
  name: string
  region: string
  start_date: string | null
  duration_hours: number
  min_temp_c: number
  avg_temp_c: number
  hourly_curve: HourlyTemperature[]
  description: string
  sources: string[]
}

export interface Substation {
  substation_id: string
  name: string
  latitude: number
  longitude: number
  voltage_kv: number
  nameplate_mva: number
  summer_peak_mw: number
  winter_peak_mw: number
  feeders: string[]
}

export interface Feeder {
  feeder_id: string
  name: string
  parent_substation_id: string
  voltage_kv: number
  rated_capacity_mva: number
  customer_count: number
  dwelling_mix: Record<string, number>
  primary_heating_mix: Record<string, number>
  ev_penetration_pct: number
  age_years: number
  has_recent_upgrade: boolean
}

export interface DistributionNetwork {
  city: string
  utility: string
  province: string
  substations: Substation[]
  feeders: Feeder[]
  baseline_winter_peak_mw: number
  baseline_year: number
  sources: string[]
  is_synthesized: boolean
}

export interface HourlyLoadPoint {
  hour_offset: number
  temp_c: number
  base_load_mw: number
  heat_pump_load_mw: number
  backup_resistance_mw: number
  baseboard_load_mw: number
  ev_load_mw: number
  other_load_mw: number
  total_load_mw: number
}

export interface HourlyLoadProfile {
  scenario_name: string
  cold_event_id: string
  hours: HourlyLoadPoint[]
  peak_load_mw: number
  peak_hour_offset: number
  peak_temp_c: number
  headroom_at_peak_mw: number
  headroom_pct_at_peak: number
}

export interface FeederRisk {
  feeder_id: string
  feeder_name: string
  parent_substation_id: string
  scenario_name: string
  overload_risk: number
  voltage_sag_risk: number
  time_to_failure_hours: number | null
  peak_load_mva: number
  capacity_utilization_pct: number
  failure_mode: string
  rationale: string
  rank: number
}

export interface SubstationRisk {
  substation_id: string
  substation_name: string
  scenario_name: string
  aggregate_risk: number
  peak_load_mva: number
  peak_utilization_pct: number
  at_risk_feeder_count: number
  rationale: string
}

export interface Mitigation {
  mitigation_id: string
  title: string
  category: string
  targeted_feeders: string[]
  estimated_load_relief_mw: number
  estimated_cost_cad: number | null
  deployment_months: number | null
  risk_reduction_pct: number
  rationale: string
}

export interface ScenarioOutcome {
  scenario: ScenarioPreset
  load_profile: HourlyLoadProfile
  feeder_risks: FeederRisk[]
  substation_risks: SubstationRisk[]
  summary_verdict: string
  headline: string
  notable_failures: string[]
}

export interface ResiliencePlan {
  job_id: string
  spec: WinterPeakSpec
  cold_event: ColdEvent
  network: DistributionNetwork
  scenarios: ScenarioOutcome[]
  mitigations: Mitigation[]
  executive_summary: string
  methodology_notes: string
  safety_flags: string[]
  limitations: string[]
  chart_paths: Record<string, string>
}

export interface WinterPeakRequest {
  query: string
  model?: ClaudeModel
}

// ── Neighborhood Electrification Readiness ──────────────────────────────── //

export interface AdoptionScenario {
  name: string
  label: string
  heat_pump_conversion_pct: number
  ev_adoption_pct: number
  target_year: number
  description: string
}

export interface ElectrificationSpec {
  query: string
  normalized_name: string
  city: string
  province: string
  fsas: string[]
  scope: string
  scenarios: AdoptionScenario[]
  horizon_year: number
  context_summary: string
}

export interface DwellingMix {
  single_detached: number
  semi_detached: number
  row: number
  apartment_low_rise: number
  apartment_high_rise: number
  other: number
}

export interface HeatingMix {
  natural_gas: number
  electric_baseboard: number
  electric_forced_air: number
  heat_pump: number
  oil: number
  wood: number
  other: number
}

export interface NeighborhoodProfile {
  fsa: string
  label: string
  city: string
  province: string
  latitude: number | null
  longitude: number | null
  households: number
  median_household_income_cad: number
  avg_household_size: number
  dwelling_mix: DwellingMix
  heating_mix: HeatingMix
  vehicles_per_household: number
  avg_dwelling_age_years: number
  heating_degree_days_18c: number
  sources: string[]
  is_synthesized: boolean
}

export interface LoadImpactPoint {
  hour: number
  base_load_kw_per_household: number
  new_heat_pump_kw_per_household: number
  new_ev_kw_per_household: number
  total_kw_per_household: number
}

export interface NeighborhoodLoadImpact {
  fsa: string
  scenario_name: string
  hours: LoadImpactPoint[]
  peak_kw_per_household: number
  peak_hour: number
  incremental_peak_mw: number
  transformer_overload_count: number
  panel_upgrade_household_pct: number
}

export interface ReadinessScore {
  fsa: string
  scenario_name: string
  grid_score: number
  building_score: number
  affordability_score: number
  policy_score: number
  overall_score: number
  verdict: string
  rank: number
  blockers: string[]
  rationale: string
}

export interface Intervention {
  intervention_id: string
  title: string
  category: string
  targeted_fsas: string[]
  households_unlocked: number
  estimated_cost_cad: number | null
  deployment_months: number | null
  readiness_lift_pct: number
  rationale: string
}

export interface FSAOutcome {
  profile: NeighborhoodProfile
  scenario: AdoptionScenario
  load_impact: NeighborhoodLoadImpact
  readiness: ReadinessScore
}

export interface ElectrificationPlan {
  job_id: string
  spec: ElectrificationSpec
  neighborhoods: NeighborhoodProfile[]
  fsa_outcomes: FSAOutcome[]
  interventions: Intervention[]
  executive_summary: string
  methodology_notes: string
  safety_flags: string[]
  limitations: string[]
  chart_paths: Record<string, string>
}

export interface ElectrificationRequest {
  query: string
  model?: ClaudeModel
}

// ── Climate-Adapted Grid Investment Optimizer ───────────────────────── //

export interface InvestmentSpec {
  query: string
  normalized_name: string
  utility: string
  province: string
  budget_cad: number
  horizon_years: number
  target_year: number
  priority_hazards: string[]
  context_summary: string
}

export interface GridAsset {
  asset_id: string
  name: string
  asset_type: string
  utility: string
  latitude: number | null
  longitude: number | null
  age_years: number
  replacement_cost_cad: number
  customers_served: number
  criticality: string
  notes: string
}

export interface HazardExposure {
  hazard: string
  annual_probability: number
  expected_loss_cad: number
  customer_hours_lost: number
  rationale: string
}

export interface ClimateRiskProfile {
  asset_id: string
  target_year: number
  hazard_exposures: HazardExposure[]
  aggregate_annual_loss_cad: number
  risk_tier: string
  rank: number
}

export interface UpgradeProject {
  project_id: string
  title: string
  category: string
  target_assets: string[]
  capex_cad: number
  annual_opex_cad: number
  risk_reduction_cad_per_year: number
  customers_protected: number
  deployment_months: number
  hazards_addressed: string[]
  rationale: string
}

export interface FundedProject {
  project: UpgradeProject
  cumulative_capex_cad: number
  roi_ratio: number
  rank: number
}

export interface InvestmentPlan {
  job_id: string
  spec: InvestmentSpec
  assets: GridAsset[]
  risk_profiles: ClimateRiskProfile[]
  candidate_projects: UpgradeProject[]
  funded_projects: FundedProject[]
  unfunded_projects: UpgradeProject[]
  total_capex_committed_cad: number
  total_annual_loss_avoided_cad: number
  portfolio_roi_ratio: number
  customers_protected: number
  executive_summary: string
  methodology_notes: string
  safety_flags: string[]
  limitations: string[]
  chart_paths: Record<string, string>
}

export interface InvestmentRequest {
  query: string
  model?: ClaudeModel
}

// ── Datacenter Expansion Planner ────────────────────────────────────── //

export interface ExpansionSpec {
  query: string
  normalized_name: string
  operator: string
  province: string
  target_additional_mw: number
  horizon_years: number
  target_year: number
  workload_mix: string
  prefer_brownfield: boolean
  context_summary: string
}

export interface ExistingSite {
  site_id: string
  name: string
  operator: string
  city: string
  province: string
  latitude: number
  longitude: number
  year_commissioned: number
  current_capacity_mw: number
  contracted_mw: number
  plot_acres: number
  transformer_headroom_mw: number
  fiber_providers: string[]
  cooling: string
  water_available_l_s: number
  grid_zone: string | null
  avg_carbon_g_kwh: number
  pue: number
  notes: string
}

export interface OperatorFootprint {
  operator: string
  province: string
  sites: ExistingSite[]
  total_current_capacity_mw: number
  is_synthesized: boolean
  sources: string[]
}

export interface DemandForecast {
  workload_mix: string
  horizon_years: number
  annual_growth_rate: number
  baseline_mw: number
  annual_demand_mw: number[]
  target_mw_year_n: number
  drivers: string[]
}

export interface ExpansionOption {
  option_id: string
  option_type: string
  target_site_id: string | null
  title: string
  new_capacity_mw: number
  capex_cad: number
  capex_per_mw_cad: number
  deployment_months: number
  grid_score: number
  sustainability_score: number
  speed_score: number
  cost_score: number
  risk_score: number
  overall_score: number
  rank: number
  rationale: string
  blockers: string[]
  latitude: number | null
  longitude: number | null
  grid_zone: string | null
  avg_carbon_g_kwh: number
}

export interface PhasedRollout {
  year: number
  options: string[]
  cumulative_new_mw: number
  cumulative_capex_cad: number
}

export interface ExpansionPlan {
  job_id: string
  spec: ExpansionSpec
  footprint: OperatorFootprint
  demand_forecast: DemandForecast
  options: ExpansionOption[]
  funded_options: ExpansionOption[]
  phased_rollout: PhasedRollout[]
  total_new_capacity_mw: number
  total_capex_cad: number
  blended_carbon_g_kwh: number
  coverage_pct: number
  executive_summary: string
  methodology_notes: string
  safety_flags: string[]
  limitations: string[]
  chart_paths: Record<string, string>
}

export interface ExpansionRequest {
  query: string
  model?: ClaudeModel
}
