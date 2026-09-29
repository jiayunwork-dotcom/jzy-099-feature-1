import type {
  Algorithm,
  ExperimentCreated,
  ExperimentEdit,
  ExperimentResult,
  ExperimentSummary,
  GraphData,
  PresetMap,
  RunResult,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parseError(resp: Response): Promise<Error> {
  try {
    const data = await resp.json();
    return new ApiError(resp.status, data.detail ?? `请求失败（${resp.status}）`);
  } catch {
    return new ApiError(resp.status, `请求失败（${resp.status}）`);
  }
}

export async function runAlgorithm(
  graph: GraphData,
  source: string,
  algorithm: Algorithm,
  options: { target?: string | null; allowNegative?: boolean } = {},
): Promise<RunResult> {
  const resp = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      graph,
      source,
      target: options.target ?? null,
      algorithm,
      allow_negative: options.allowNegative ?? false,
    }),
  });
  if (!resp.ok) throw await parseError(resp);
  return (await resp.json()) as RunResult;
}

export async function fetchPresets(): Promise<PresetMap> {
  const resp = await fetch("/api/presets");
  if (!resp.ok) throw await parseError(resp);
  return (await resp.json()) as PresetMap;
}

// ---- 动态实验 -----------------------------------------------------------

export async function createExperiment(
  graph: GraphData,
  source: string,
): Promise<ExperimentCreated> {
  const resp = await fetch("/api/experiments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ graph, source }),
  });
  if (!resp.ok) throw await parseError(resp);
  return (await resp.json()) as ExperimentCreated;
}

export async function submitExperimentEdit(
  experimentId: string,
  edit: ExperimentEdit,
): Promise<ExperimentResult> {
  const resp = await fetch(
    `/api/experiments/${experimentId}/edits`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(edit),
    },
  );
  if (!resp.ok) throw await parseError(resp);
  return (await resp.json()) as ExperimentResult;
}

export async function fetchExperiment(
  experimentId: string,
): Promise<ExperimentSummary> {
  const resp = await fetch(`/api/experiments/${experimentId}`);
  if (!resp.ok) throw await parseError(resp);
  return (await resp.json()) as ExperimentSummary;
}

export async function fetchExperimentVersion(
  experimentId: string,
  version: number,
): Promise<ExperimentResult> {
  const resp = await fetch(
    `/api/experiments/${experimentId}/versions/${version}`,
  );
  if (!resp.ok) throw await parseError(resp);
  return (await resp.json()) as ExperimentResult;
}

export async function deleteExperiment(experimentId: string): Promise<void> {
  const resp = await fetch(`/api/experiments/${experimentId}`, {
    method: "DELETE",
  });
  if (!resp.ok) throw await parseError(resp);
}
