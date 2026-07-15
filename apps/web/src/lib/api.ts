export const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // response body wasn't JSON (or was empty) - fall back to statusText
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export interface PipelineSummary {
  id: number;
  name: string;
  stage_count: number;
  models_used: string[];
  benchmark_query_count: number;
}

export interface ImportResult {
  pipeline_id: number;
  name: string;
  stage_count: number;
  trace_count: number;
}

export interface DagLayer {
  stage_ids: number[];
}

export interface StageInfo {
  id: number;
  name: string;
  model: string;
  avg_tokens_in: number | null;
  avg_tokens_out: number | null;
  avg_latency_ms: number | null;
}

export interface DagEdge {
  from_stage_id: number;
  to_stage_id: number;
}

export interface DagResponse {
  pipeline_id: number;
  layers: DagLayer[];
  stages: Record<string, StageInfo>;
  edges: DagEdge[];
}

export interface RubricOut {
  id: number;
  stage_id: number;
  stage_name: string;
  deterministic_checks: Record<string, unknown>[];
  judge_criteria: Record<string, unknown>[];
  downstream_contract: string[];
  approved: boolean;
}

export interface RubricUpdate {
  deterministic_checks?: Record<string, unknown>[];
  judge_criteria?: Record<string, unknown>[];
  downstream_contract?: string[];
}

export function listPipelines(): Promise<PipelineSummary[]> {
  return request<PipelineSummary[]>("/pipelines");
}

export function listRubrics(pipelineId: number): Promise<RubricOut[]> {
  return request<RubricOut[]>(`/pipelines/${pipelineId}/rubrics`);
}

export function updateRubric(rubricId: number, update: RubricUpdate): Promise<RubricOut> {
  return request<RubricOut>(`/rubrics/${rubricId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
}

export function approveRubric(rubricId: number): Promise<RubricOut> {
  return request<RubricOut>(`/rubrics/${rubricId}/approve`, { method: "POST" });
}

export function approveAllRubrics(pipelineId: number): Promise<RubricOut[]> {
  return request<RubricOut[]>(`/pipelines/${pipelineId}/rubrics/approve-all`, {
    method: "POST",
  });
}

export function generateRubric(pipelineId: number, stageId: number, model: string): Promise<RubricOut> {
  return request<RubricOut>(`/pipelines/${pipelineId}/stages/${stageId}/generate-rubric`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ model }),
  });
}

export function getPipelineDag(pipelineId: number): Promise<DagResponse> {
  return request<DagResponse>(`/pipelines/${pipelineId}/dag`);
}

export interface ModelOption {
  model: string;
  provider: string | null;
  input_cost_per_1m: number | null;
  output_cost_per_1m: number | null;
  max_input_tokens: number | null;
  max_output_tokens: number | null;
  supports_json_mode: boolean;
  supports_function_calling: boolean;
  requires_api_key: boolean;
}

export interface TargetModelConfig {
  models: string[];
}

export interface MigrationCreate {
  target_model_config: TargetModelConfig;
  budget: number;
  parity_threshold: number;
}

// "idle" | "running" | "done" | "failed" — see
// apps/api/src/reprompt_api/migrations.py's `_compute_stage_states` for the
// derivation rule. Keyed by stage DB id as a string, matching the DAG
// canvas's React Flow node ids (String(stage.id)).
export type StageRunState = "idle" | "running" | "done" | "failed";

export interface MigrationOut {
  id: number;
  pipeline_id: number;
  target_model_config: TargetModelConfig;
  budget: number;
  parity_threshold: number;
  status: string;
  total_cost_usd: number | null;
  stopped_early: boolean;
  stop_reason: string | null;
  progress_stage_name: string | null;
  progress_current: number | null;
  progress_total: number | null;
  // Live sub-step within progress_stage_name — one of StagePhase below,
  // null before a run starts. See apps/api's optimizer_runner.py on_phase
  // closure and packages/core's reprompt_core.optimizer.loop.StagePhase.
  progress_substep: StagePhase | null;
  completed_at: string | null;
  stage_states: Record<string, StageRunState>;
}

// Mirrors reprompt_core.optimizer.loop.StagePhase (packages/core) exactly —
// see stage-node.tsx's SUBSTEP_LABEL for the human-readable mapping.
export type StagePhase = "mutating" | "cheap_scoring" | "critiquing" | "refining" | "sweeping" | "scoring";

export function listModelOptions(pipelineId: number): Promise<ModelOption[]> {
  return request<ModelOption[]>(`/pipelines/${pipelineId}/models`);
}

export function createMigration(
  pipelineId: number,
  migration: MigrationCreate
): Promise<MigrationOut> {
  return request<MigrationOut>(`/pipelines/${pipelineId}/migrations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(migration),
  });
}

export function listMigrations(pipelineId: number): Promise<MigrationOut[]> {
  return request<MigrationOut[]>(`/pipelines/${pipelineId}/migrations`);
}

export function startMigration(pipelineId: number, migrationId: number): Promise<MigrationOut> {
  return request<MigrationOut>(`/pipelines/${pipelineId}/migrations/${migrationId}/start`, {
    method: "POST",
  });
}

export function getMigrationStatus(pipelineId: number, migrationId: number): Promise<MigrationOut> {
  return request<MigrationOut>(`/pipelines/${pipelineId}/migrations/${migrationId}/status`);
}

// ---------------------------------------------------------------------------
// Model cards (migration wizard): read-only info on model family transforms
// ---------------------------------------------------------------------------
//
// Public, unauthenticated - serves metadata about prompt transforms per model
// family, so the UI can display what rewriting rules apply to a candidate.

export interface TransformRuleInfo {
  name: string;
  description: string;
  applies_to: "all" | "small_only";
  will_apply: boolean;
}

export interface ModelCardInfo {
  family: string;
  version: number;
  description: string;
  is_small_variant: boolean;
  rules: TransformRuleInfo[];
}

export function getModelCard(model: string): Promise<ModelCardInfo> {
  return request<ModelCardInfo>(`/model-cards/${encodeURIComponent(model).replace(/%2F/g, "/")}`);
}

export async function importPipeline(file: File): Promise<ImportResult> {
  const formData = new FormData();
  formData.append("file", file);
  return request<ImportResult>("/pipelines/import", {
    method: "POST",
    body: formData,
  });
}

// ---------------------------------------------------------------------------
// Trace format reference (screen: /schema)
// ---------------------------------------------------------------------------
//
// Public, unauthenticated - serves the raw JSON Schema document generated
// from packages/core's Pydantic TraceFile model (see docs/trace-format.md).
// Typed as unknown rather than a specific interface since it's a JSON Schema
// document, not a Reprompt domain object - the schema page only needs to
// stringify and download it, not read individual fields off it.
export function getTraceFormatSchema(): Promise<unknown> {
  return request<unknown>("/trace-format/schema");
}

// ---------------------------------------------------------------------------
// Auth (magic link)
// ---------------------------------------------------------------------------
//
// See apps/api/src/reprompt_api/auth.py's module docstring for the full
// design (lazy account creation, dev-mode magic links, the session token
// mechanism). The session token is stored in localStorage (not a cookie) -
// simplest option that works across the Vite dev server (:5173) and API
// (:8000) running on different origins without needing to reason about
// cross-origin cookie/CORS credential settings for an MVP that doesn't need
// route guards yet (see login.tsx / auth-verify.tsx).

const SESSION_TOKEN_STORAGE_KEY = "reprompt_session_token";

export function setSessionToken(token: string): void {
  localStorage.setItem(SESSION_TOKEN_STORAGE_KEY, token);
}

export function getSessionToken(): string | null {
  return localStorage.getItem(SESSION_TOKEN_STORAGE_KEY);
}

export function clearSessionToken(): void {
  localStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
}

export interface RequestMagicLinkResult {
  message: string;
  // Only present when the API's dev-mode-link flag is on (default in this
  // environment - there's no real email provider configured yet).
  dev_magic_link: string | null;
}

export function requestMagicLink(email: string): Promise<RequestMagicLinkResult> {
  return request<RequestMagicLinkResult>("/auth/request-link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

export interface AuthUser {
  id: number;
  email: string;
}

export interface AuthWorkspace {
  id: number;
  name: string;
}

export interface VerifyMagicLinkResult {
  session_token: string;
  user: AuthUser;
  workspace: AuthWorkspace;
}

export function verifyMagicLink(token: string): Promise<VerifyMagicLinkResult> {
  return request<VerifyMagicLinkResult>("/auth/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
}

export interface MeResult {
  user: AuthUser;
  workspace: AuthWorkspace;
}

export function getCurrentUser(): Promise<MeResult> {
  const token = getSessionToken();
  return request<MeResult>("/auth/me", {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
}

// ---------------------------------------------------------------------------
// Settings (screen 9): workspace name + BYOK provider API keys
// ---------------------------------------------------------------------------
//
// Every call here needs the Bearer session token - see
// apps/api/src/reprompt_api/settings.py, mounted behind get_current_user.
// authHeaders() mirrors the inline pattern getCurrentUser() already uses
// above, pulled out since every settings function needs it.

function authHeaders(): HeadersInit {
  const token = getSessionToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface WorkspaceSettings {
  name: string;
}

export function getWorkspaceSettings(): Promise<WorkspaceSettings> {
  return request<WorkspaceSettings>("/settings/workspace", { headers: authHeaders() });
}

export function updateWorkspaceSettings(name: string): Promise<WorkspaceSettings> {
  return request<WorkspaceSettings>("/settings/workspace", {
    method: "PATCH",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export interface ApiKeyOut {
  id: number;
  provider: string;
  last_four: string;
  created_at: string;
}

export function listApiKeys(): Promise<ApiKeyOut[]> {
  return request<ApiKeyOut[]>("/settings/api-keys", { headers: authHeaders() });
}

export function addApiKey(provider: string, apiKey: string): Promise<ApiKeyOut> {
  return request<ApiKeyOut>("/settings/api-keys", {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ provider, api_key: apiKey }),
  });
}

export async function deleteApiKey(id: number): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/settings/api-keys/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // response body wasn't JSON (or was empty, as on a 204) - fall back
    }
    throw new ApiError(detail, response.status);
  }
}
