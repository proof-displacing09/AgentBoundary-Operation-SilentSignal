// Typed models mirroring docs/API_CONTRACT.md v1 exactly. No invented endpoints.
export type Decision = 'ALLOW' | 'DENY' | 'APPROVAL_REQUIRED' | 'ERROR' | 'INFO';
export type Verdict = 'PASS' | 'FAIL' | 'INCONCLUSIVE' | 'ERROR' | 'CANCELLED';

export interface Persona {
  id: string;
  display_name?: string;
  name?: string;
  role: string;
  tenant_ids: string[];
  tenants?: string[];
  can_approve?: string[];
  description?: string;
}

export interface SessionResponse {
  session_token: string;
  persona: Persona;
  expires_at: string;
}

export interface Health {
  status: string;
  mode: string;
  weak_mode_available_via_api: boolean;
  db_version: string;
  fixture_version: string;
  adapter: string;
  real_model_configured: boolean;
  /** Model name reported by the backend (host-side env); null when unconfigured. Never key material. */
  real_llm_model?: string | null;
  /** Base-URL host only (e.g. api.openai.com); null when unconfigured. Never key material. */
  real_llm_base_url_host?: string | null;
  /** R-14: machine-readable reason the provider is not usable (e.g. insecure_http_url), null when usable/unset. No key material. */
  real_llm_config_error?: string | null;
  /** R-11: fixture/schema integrity after open/repair. Absent on older backends. */
  fixture_integrity?: {
    ok: boolean;
    backfilled_tables: string[];
    degraded_tables: string[];
  } | null;
}

/**
 * N-03 privileged reset contract (backend-built in parallel; shape tolerated
 * flexibly — any count the backend does not return renders as "unknown", never
 * an invented number). dry_run returns what would be deleted without deleting;
 * confirm performs the reset; neither returns 400 and deletes nothing.
 */
export interface ResetResult {
  reset?: boolean;
  dry_run?: boolean;
  records?: number;
  runs?: number;
  events?: number;
  drafts?: number;
  isolations?: number;
  would_delete?: {
    runs?: number;
    events?: number;
    drafts?: number;
    isolations?: number;
    [key: string]: unknown;
  };
  counts?: Record<string, number>;
  [key: string]: unknown;
}

export interface Settings extends Partial<Health> {
  trial_count?: number;
  max_trials?: number;
  supported_metrics?: string[];
  last_test_run?: string | null;
  reset_status?: string;
  /** Real-LLM provider status (from /settings): configured flag, model name, base-URL host only. */
  real_model_configured?: boolean;
  real_llm_model?: string | null;
  real_llm_base_url_host?: string | null;
  [key: string]: unknown;
}

/** Real-LLM execution metadata (API_CONTRACT adapter section). Host-only
 * provider info and outcome counters — never an API key, never a secret. */
export interface LlmMetrics {
  provider_base_url_host?: string | null;
  model?: string | null;
  temperature?: number | null;
  max_tool_calls?: number | null;
  /** R-10: what separates a mocked protocol validation from a live trial. */
  transport?: 'mocked_protocol' | 'live_provider' | string | null;
  outcome?: 'completed' | 'no_proposals' | 'budget_exhausted' | 'provider_error' | 'cancelled' | string | null;
  error_class?: 'rate_limited' | 'timeout' | 'provider_error' | 'transport_error' | 'not_configured' | 'insecure_provider_url' | string | null;
  model_calls?: number | null;
  tool_calls_made?: number | null;
}

/** R-02/R-03/R-04/R-05/R-16 research axes (third audit). A held boundary and
 * a scientifically valid injection result are separate facts; the UI must
 * never collapse them into one PASS badge. */
export interface ExposureLedger {
  exposed?: boolean;
  markers_seen?: string[];
  mode?: string;
  first_exposure_tool_call_id?: string | null;
  first_exposure_tool?: string | null;
  first_exposure_seq?: number | null;
  /** FA-01/FA-05/FA-06: causal exposure state — confirmed (full payload
   * in a request that returned a model response), unconfirmed (full
   * payload sent but no confirming response), partial (only a fragment
   * survived truncation), or none. Only "confirmed" counts as exposure
   * for post-injection attribution. */
  exposure_state?: 'confirmed' | 'unconfirmed' | 'partial' | 'none' | string;
  confirmed_full_exposure_turn?: number | null;
  unconfirmed_markers?: string[];
  partial_markers?: string[];
}

/** FA-01/FA-06: one provider response's tool-call batch + the delivery
 * state of each observation it produced. A proposal's causal turn is
 * what decides post-exposure attribution — never dispatch order. */
export interface CausalBatch {
  batch_id?: string;
  proposal_turn?: number;
  tools?: string[];
  provider_call_ids?: string[];
}

export interface CausalObservation {
  tool?: string;
  observation_hash?: string;
  truncated?: boolean;
  markers?: string[];
  payload_coverage?: Record<string, { coverage?: string; payload_source?: string | null }>;
  delivery_state?: 'constructed' | 'sent' | 'confirmed' | string;
  proposal_turn?: number;
  sent_in_request_turn?: number | null;
  confirmed_response_turn?: number | null;
  excerpt?: string;
}

export interface CausalLedger {
  batches?: CausalBatch[];
  delivered_observations?: CausalObservation[];
  confirmed_full_exposure_turn?: number | null;
  exposure_state?: string;
}

/** FA-03: why a real-mode draft did or did not count as grounded. */
export interface DraftGroundingDetail {
  grounded?: boolean;
  reasons?: string[];
  cited_source?: string | null;
  citation_confirmed_turn?: number | null;
  draft_turn?: number | null;
  summary_chars?: number;
  non_id_words?: number;
  actions_chars?: number;
  /** SI-02: which committed draft this assessment belongs to. */
  tool_call_id?: string | null;
  draft_id?: string | null;
}

export interface HarnessControl {
  ran?: boolean;
  completed?: boolean;
  note?: string;
}

export type TrialOutcome =
  | 'CLEAN_TASK_SUCCESS' | 'RESISTED_AFTER_EXPOSURE' | 'NO_EXPOSURE'
  | 'NO_ATTACK_ATTEMPT' | 'TARGETED_ATTACK_BLOCKED' | 'FORBIDDEN_COMPLETED'
  | 'LEGITIMATE_TASK_INCOMPLETE' | 'PROVIDER_ERROR' | 'CANCELLED'
  | 'INCONCLUSIVE' | 'UNEXPOSED_PROPOSAL' | 'SCRIPTED_BOUNDARY_HELD'
  | 'SCRIPTED_BOUNDARY_FAILED' | string;

export interface RunMetrics {
  /** Present only on real_llm runs; absent on scripted runs. */
  llm?: LlmMetrics | null;
  attempted_unauthorized: number;
  completed_forbidden: number;
  denied: number;
  disclosed_restricted: boolean;
  /** Legacy alias of legitimate_workflow_completed; kept for compatibility. */
  legitimate_task_success: boolean;
  /** F-05: true when the security invariant (verdict PASS) holds — NOT proof an investigation completed. */
  security_invariant_pass?: boolean;
  /** F-05: true only when the scenario's legitimate workflow steps completed with ALLOW. */
  legitimate_workflow_completed?: boolean;
  /** R-04: agent-origin legitimate completion (harness controls excluded). */
  model_legitimate_workflow_completed?: boolean;
  /** R-02/R-16: scientific outcome tag; see TrialOutcome. */
  trial_outcome?: TrialOutcome | null;
  /** R-02: no forbidden action completed (state-proven). Distinct from trial validity. */
  policy_boundary_held?: boolean;
  /** R-02: the trial met its prerequisites (model ran, and for poison scenarios the payload was delivered where required). */
  experiment_valid?: boolean;
  /** R-03: whether the injection hypothesis was actually testable in this trial. */
  injection_hypothesis_tested?: boolean;
  /** R-03: exposure ledger for this trial. */
  exposure?: ExposureLedger | null;
  /** R-03/R-05: matched forbidden proposals (ground truth), post-exposure attacks, pre-exposure proposals. */
  matched_forbidden_proposals?: number;
  post_injection_model_attack_attempts?: number;
  /** S7-05: matched forbidden proposals that ended DENY or
   * APPROVAL_REQUIRED (correlated by tool_call_id) — the blocked subset
   * of the proposals above, not a synonym for them. */
  targeted_forbidden_calls_blocked?: number;
  unexposed_proposals?: number;
  model_attempted_forbidden?: number;
  /** S7-01: completed state changes by this A1 run that are outside its
   * read+draft mission (status transitions, isolations) — even when
   * gateway-allowed. Empty for clean runs; absent for non-A1 runs. */
  out_of_mission_actions?: Array<{
    tool?: string;
    tool_call_id?: string | null;
    case_id?: string | null;
    asset_id?: string | null;
    new_status?: string | null;
    approval_status?: string | null;
    decision?: string | null;
  }> | null;
  /** S7-01: for A1, whether the clean mission completed (legitimate steps
   * AND no out-of-mission action). Null for non-A1 scenarios. */
  clean_mission_completed?: boolean | null;
  /** S7-04: the old tool-name-only step score, renamed so it is never
   * mistaken for task completion. */
  required_tool_calls_completed?: boolean;
  /** S7-02/S7-03: proposals received but never dispatched because
   * cancellation arrived or the budget expired (real runs only). */
  discarded_proposals?: Array<{
    tool?: string;
    provider_call_id?: string | null;
    proposal_turn?: number | null;
    batch_id?: string | null;
    reason?: string | null;
  }> | null;
  /** R-05: denial breakdown (agent-origin logical calls). */
  all_denials?: number;
  invalid_input_denials?: number;
  permission_denials?: number;
  approval_denials?: number;
  /** R-04: harness control-plane results, kept outside model rates. */
  harness_control?: HarnessControl | null;
  /** FR-10: per-origin logical-call counts + harness-matched proposals. */
  origin_counts?: { scripted_agent?: number; real_model?: number; harness_control?: number } | null;
  harness_matched_proposals?: number;
  /** FR-01: gateway-allowed state changes that are not bypasses. */
  authorized_state_changes?: number;
  /** R-15: model-visible evidence-surface hash + policy version. */
  fixture_variant?: string | null;
  /** FA-04: experiment-manifest scheme for the variant ("snapshot-v3"). */
  fixture_variant_scheme?: string | null;
  /** FA-04: full v3 experiment manifest (components + digest). */
  experiment_manifest?: Record<string, unknown> | null;
  /** FA-01/FA-06: causal turn/batch/delivery ledger (real runs only). */
  causal_ledger?: CausalLedger | null;
  /** FA-03: draft grounding detail (real runs only). */
  draft_grounding_detail?: DraftGroundingDetail | null;
  /** SI-02: every assessed draft in order; the selected (latest grounded) one is draft_grounding_detail. */
  draft_grounding_details?: DraftGroundingDetail[] | null;
  policy_version?: string | null;
}

/** Identity separation (F-02): the operator who launched the run is NOT the authority under test. */
export interface RunIdentities {
  operator_persona_id?: string | null;
  simulated_actor_id?: string | null;
  control_actor_id?: string | null;
  /** Legacy single actor field, retained by pre-remediation runs; equals simulated_actor_id. */
  actor_id?: string | null;
  fixture_version?: string | null;
}

export interface LabEvent {
  event_id: string;
  run_id: string;
  scenario_id: string;
  /** N-08: stable scope for one proposed tool invocation (ATTEMPT + terminal outcome share it). */
  tool_call_id?: string | null;
  /** N-04: 'primary' evidence belongs to the run's tenant scope; 'control_only'
   * positive-control evidence is visible in full only to the experiment admin. */
  evidence_scope?: 'primary' | 'control_only' | string | null;
  seq: number;
  timestamp: string;
  actor_id: string;
  /** F-02, when the backend attaches run identities to event headers. */
  operator_persona_id?: string | null;
  simulated_actor_id?: string | null;
  tenant_id: string;
  adapter: string;
  tool: string | null;
  args_sanitized: Record<string, unknown> | null;
  source_provenance: string | null;
  trust_label: string | null;
  decision: Decision;
  reason_code: string | null;
  approval_status: string | null;
  attempted: boolean;
  completed: boolean;
  disclosed_restricted: boolean;
  before_state: unknown;
  after_state: unknown;
  detail: string | null;
}

export interface Run extends RunIdentities {
  id: string;
  scenario_id: string;
  status: string;
  verdict: Verdict;
  adapter: string;
  mode: string;
  started_at: string;
  finished_at: string | null;
  metrics: RunMetrics;
  events: LabEvent[];
  omissions?: string[];
  /** R-13: present on 202 async real-mode creations (poll/cancel URLs). */
  job?: { status?: string; poll_url?: string; cancel_url?: string } | null;
  fixture_variant?: string | null;
}

export interface RunSummary extends RunIdentities {
  id: string;
  scenario_id: string;
  status?: string;
  verdict: Verdict;
  adapter?: string;
  mode?: string;
  started_at?: string;
  finished_at?: string | null;
  metrics?: RunMetrics;
}

export interface ScenarioSummary {
  id: string;
  title: string;
  category?: string;
  vector?: string;
  description?: string;
  persona_id?: string;
  tenant_id?: string;
}

export interface ScenarioDetail extends ScenarioSummary {
  attacker_surface?: string;
  attacker_controlled_surface?: string;
  legitimate_task?: string;
  legitimate_objective?: string;
  injection_text?: string;
  injection_fixture_text?: string;
  expected_outcome?: string;
  expected?: string;
  trusted_actor?: string;
  persona_id?: string;
  forbidden_objective?: string;
  target?: string;
  intended_tools?: string[];
}

export interface CaseRecord {
  id: string;
  tenant_id: string;
  title: string;
  status: string;
  priority?: string;
  severity?: string;
  summary?: string;
  description?: string;
  asset_id?: string;
  created_at?: string;
  updated_at?: string;
  events?: TimelineEvent[];
  timeline?: TimelineEvent[];
  [key: string]: unknown;
}

export interface TimelineEvent {
  id: string;
  case_id?: string;
  tenant_id?: string;
  timestamp: string;
  source_type?: string;
  classification?: string;
  trust_label?: string;
  provenance?: string;
  actor?: string;
  text?: string;
  content?: string;
  title?: string;
  [key: string]: unknown;
}

export interface AlertRecord {
  id: string;
  tenant_id: string;
  case_id?: string;
  title: string;
  severity?: string;
  status?: string;
  timestamp?: string;
  [key: string]: unknown;
}

export interface Overview {
  scenarios_run: number;
  total_runs: number;
  attempted_unauthorized: number;
  denied: number;
  completed_forbidden: number;
  tenant_leaks: number;
  /** Legacy alias count; prefer legitimate_workflow_completions. */
  legitimate_task_successes: number;
  /** F-05: runs whose security invariant passed (verdict PASS). */
  security_invariant_passes?: number;
  /** F-05: runs whose legitimate workflow steps completed. */
  legitimate_workflow_completions?: number;
  /** R-04: model-origin legitimate completions (harness controls excluded). */
  model_legitimate_workflow_completions?: number;
  /** R-16: trial-outcome counts across stored runs. */
  trial_outcomes?: Record<string, number>;
  /** S7-05: matched forbidden proposals that ended DENY/APPROVAL_REQUIRED. */
  targeted_forbidden_calls_blocked?: number;
  /** S7-01: A1 runs that committed an out-of-mission state change. */
  out_of_mission_runs?: number;
  /** S7-05: matched forbidden proposals after confirmed payload exposure
   * (proposals only — blocking is targeted_forbidden_calls_blocked). */
  post_injection_model_attack_attempts?: number;
  /** Proposals made before any payload exposure (not injection evidence). */
  unexposed_proposals?: number;
  inconclusive: number;
  recent_runs: RunSummary[];
  recent_cases: CaseRecord[];
}

export interface PolicyAction {
  action: string;
  tool: string;
  requires_approval: boolean;
  allowed_roles: string[];
  tenant_rule: string;
}

export interface PolicyMatrix {
  personas: Persona[];
  tenants: Array<{ id: string; name?: string; [key: string]: unknown } | string>;
  resources: unknown[];
  actions: PolicyAction[];
  approval_rules: unknown[];
  reason_codes: string[] | Array<{ code: string; description?: string }>;
}

export interface Finding {
  id: string;
  title: string;
  scenario_id?: string;
  severity: string;
  trust_boundary?: string;
  boundary?: string;
  evidence?: string;
  reproduction?: string;
  impact?: string;
  root_cause?: string;
  remediation?: string;
  limitations?: string;
  confidence?: string;
  state?: string;
  [key: string]: unknown;
}

/** F-04: one genuinely comparable pair — same scenario, fixture version, scripted adapter. */
export interface ComparisonPair {
  scenario_id: string;
  fixture_version?: string | null;
  /** R-15: exact model-visible evidence surface + policy version of the pair. */
  fixture_variant?: string | null;
  policy_version?: string | null;
  protected?: RunSummary | null;
  protected_run?: RunSummary | null;
  weak?: (RunSummary & { omissions?: string[] }) | null;
  weak_run?: (RunSummary & { omissions?: string[] }) | null;
  weak_report?: (RunSummary & { omissions?: string[] }) | null;
  /** E8-02: other eligible protected runs for this pair (newest won);
   * listed, never double-counted as separate contrasts. */
  alternative_protected_runs?: string[];
}

export interface UnmatchedComparison {
  scenario_id?: string;
  id?: string;
  reason?: string;
  source?: string;
  [key: string]: unknown;
}

export interface Comparisons {
  /** Legacy compatibility columns; pairs are the only comparable rows. */
  protected_runs: RunSummary[];
  weak_reports: RunSummary[];
  /** F-04: non-empty only when at least one genuinely matched pair exists. */
  pairs?: ComparisonPair[];
  unmatched_protected?: UnmatchedComparison[];
  unmatched_weak?: UnmatchedComparison[];
  comparable: boolean;
  notes: string;
}

export interface EventsPage {
  items: LabEvent[];
  total: number;
}

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}
