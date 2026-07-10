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

export function listPipelines(): Promise<PipelineSummary[]> {
  return request<PipelineSummary[]>("/pipelines");
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
