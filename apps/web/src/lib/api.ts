const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

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
  avg_tokens_in: number;
  avg_tokens_out: number;
  avg_latency_ms: number;
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

export function getPipelineDag(pipelineId: number): Promise<DagResponse> {
  return request<DagResponse>(`/pipelines/${pipelineId}/dag`);
}

export async function importPipeline(file: File): Promise<ImportResult> {
  const formData = new FormData();
  formData.append("file", file);
  return request<ImportResult>("/pipelines/import", {
    method: "POST",
    body: formData,
  });
}
