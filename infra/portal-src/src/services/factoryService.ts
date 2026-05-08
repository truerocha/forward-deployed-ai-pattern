/**
 * Factory Service — Connects to the Code Factory Status API.
 * All data comes from the real API. No simulations.
 */

export interface TaskEvent {
  ts: string;
  type: string;
  msg: string;
  phase?: string;
  gate_name?: string;
  gate_result?: string;
  criteria?: string;
  context?: string;
  autonomy_level?: string;
  confidence?: string;
}

export interface Task {
  task_id: string;
  title: string;
  status: string;
  current_stage: string;
  stage_progress: { current: number; total: number; percent: number };
  agent: { instance_id: string; name: string } | null;
  repo: string;
  source: string;
  issue_url: string;
  pr_url: string;
  pr_error: string;
  priority: string;
  elapsed_ms: number;
  duration_ms: number;
  events: TaskEvent[];
}

export interface DashboardData {
  metrics: {
    active: number;
    completed_24h: number;
    failed_24h: number;
    avg_duration_ms: number;
    total_agents_provisioned: number;
    active_agents: number;
  };
  dora: {
    level: string;
    lead_time_avg_ms: number;
    success_rate_pct: number;
    throughput_24h: number;
    change_failure_rate_pct: number;
  } | null;
  tasks: Task[];
  projects: { repo: string; display_name: string; task_count: number; active: number }[];
}

function getApiUrl(): string {
  return document.querySelector('meta[name="factory-api-url"]')?.getAttribute('content') || '';
}

export async function fetchDashboardData(repoFilter?: string): Promise<DashboardData | null> {
  const api = getApiUrl();
  if (!api) return null;

  const url = repoFilter
    ? `${api}/status/tasks?repo=${encodeURIComponent(repoFilter)}`
    : `${api}/status/tasks`;

  try {
    const r = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

export async function fetchTaskReasoning(taskId: string): Promise<{ events: TaskEvent[]; gate_summary: { total: number; passed: number; failed: number } } | null> {
  const api = getApiUrl();
  if (!api) return null;

  try {
    const r = await fetch(`${api}/status/tasks/${taskId}/reasoning`, { headers: { Accept: 'application/json' } });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

export async function fetchHealth(): Promise<{ status: string; checks: { name: string; status: string; detail: string }[] } | null> {
  const api = getApiUrl();
  if (!api) return null;

  try {
    const r = await fetch(`${api}/status/health`, { headers: { Accept: 'application/json' } });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}


