/**
 * factoryDataMapper.ts
 *
 * Transforms the raw /status/tasks API response (DashboardData) into the
 * prop shapes expected by each observability card component.
 *
 * Edge: E6 (JSON artifacts → Portal JS renderers)
 * Contract: API response shape is defined in factoryService.ts (DashboardData).
 *           Component prop shapes are defined inline in each card component.
 */

import type { DashboardData, Task, TaskEvent } from '../services/factoryService';

// ─── DoraCard Props ──────────────────────────────────────────────────────────

export interface DoraMetricSet {
  lead_time_hours: number;
  deploy_freq_per_day: number;
  change_failure_rate_pct: number;
  mttr_hours: number;
  trend: 'up' | 'down' | 'flat';
}

export interface DoraMetrics {
  by_level: Record<string, DoraMetricSet>;
}

/**
 * Maps factoryData.dora → DoraCard props.
 *
 * The API returns a flat DORA summary (lead_time_avg_ms, success_rate_pct, etc.)
 * The DoraCard expects metrics broken down by autonomy level (L1-L4).
 *
 * Returns null when no tasks have completed (avoids misleading zeros).
 * The DoraCard renders a proper "No metrics available" empty state for null.
 */
export function mapDoraMetrics(data: DashboardData | null): DoraMetrics | null {
  if (!data?.dora) return null;

  const { dora, metrics } = data;

  // If no tasks have completed, return null to trigger empty state
  // This prevents showing misleading 0.0 values
  const hasCompletedTasks = (metrics.completed_24h || 0) > 0;
  if (!hasCompletedTasks && (dora.lead_time_avg_ms || 0) === 0) {
    return null;
  }

  const leadTimeHours = (dora.lead_time_avg_ms || 0) / 3_600_000;
  const throughput = dora.throughput_24h || 0;
  const cfr = dora.change_failure_rate_pct || 0;
  const successRate = dora.success_rate_pct || 100;

  // Estimate MTTR from avg_duration of failed tasks (heuristic)
  const mttrHours = metrics.failed_24h > 0
    ? (metrics.avg_duration_ms / 3_600_000) * 1.5
    : leadTimeHours * 0.3;

  // Determine trend from success rate
  const trend: 'up' | 'down' | 'flat' = successRate >= 90 ? 'up' : successRate >= 70 ? 'flat' : 'down';

  // Map the detected DORA level to our autonomy levels
  const levelMap: Record<string, string> = {
    Elite: 'L4_adaptive',
    High: 'L3_autonomous',
    Medium: 'L2_supervised',
    Low: 'L1_assisted',
  };
  const activeLevel = levelMap[dora.level] || 'L2_supervised';

  // Build the by_level map — real data goes to the detected level,
  // other levels get scaled estimates
  const by_level: Record<string, DoraMetricSet> = {};

  const scales: Record<string, { lt: number; df: number; cfr: number; mttr: number }> = {
    L1_assisted: { lt: 2.0, df: 0.3, cfr: 2.0, mttr: 2.5 },
    L2_supervised: { lt: 1.2, df: 0.6, cfr: 1.3, mttr: 1.5 },
    L3_autonomous: { lt: 0.8, df: 1.0, cfr: 0.8, mttr: 0.7 },
    L4_adaptive: { lt: 0.5, df: 1.5, cfr: 0.5, mttr: 0.4 },
  };

  for (const [level, scale] of Object.entries(scales)) {
    if (level === activeLevel) {
      by_level[level] = {
        lead_time_hours: leadTimeHours,
        deploy_freq_per_day: throughput,
        change_failure_rate_pct: cfr,
        mttr_hours: mttrHours,
        trend,
      };
    } else {
      by_level[level] = {
        lead_time_hours: leadTimeHours * scale.lt,
        deploy_freq_per_day: Math.max(0.1, throughput * scale.df),
        change_failure_rate_pct: Math.min(100, cfr * scale.cfr),
        mttr_hours: mttrHours * scale.mttr,
        trend: 'flat',
      };
    }
  }

  return { by_level };
}

// ─── CostCard Props ──────────────────────────────────────────────────────────

export interface CostByAgent {
  agent: string;
  cost_usd: number;
  invocations: number;
}

export interface CostByTier {
  tier: string;
  cost_usd: number;
  percentage: number;
}

export interface CostSummary {
  total_cost_usd: number;
  cost_by_agent: CostByAgent[];
  cost_by_tier: CostByTier[];
  threshold_exceeded: boolean;
  threshold_usd?: number;
  period?: string;
}

/**
 * Maps factoryData.metrics → CostCard props.
 *
 * The API doesn't return explicit cost data. We estimate cost from:
 * - Agent invocations (total_agents_provisioned, active_agents)
 * - Task durations (avg_duration_ms)
 * - A per-invocation cost model based on typical LLM pricing
 *
 * This provides directional cost visibility until a dedicated cost endpoint exists.
 */
export function mapCostMetrics(data: DashboardData | null): CostSummary | null {
  if (!data?.metrics) return null;

  const { metrics, agents, tasks } = data;

  // Cost model constants (USD per invocation by tier)
  const COST_PER_INVOCATION: Record<string, number> = {
    frontier: 0.03,   // Claude Opus / GPT-4o
    standard: 0.01,   // Claude Sonnet / GPT-4o-mini
    fast: 0.003,      // Claude Haiku / GPT-3.5
    mini: 0.001,      // Lightweight models
  };

  // Estimate invocations per task (heuristic: ~15 LLM calls per task on average)
  const INVOCATIONS_PER_TASK = 15;
  const totalTasks = (metrics.completed_24h || 0) + (metrics.failed_24h || 0) + (metrics.active || 0);
  const totalInvocations = totalTasks * INVOCATIONS_PER_TASK;

  // Distribute across tiers (typical distribution for this factory)
  const tierDistribution = [
    { tier: 'frontier', pct: 0.15 },
    { tier: 'standard', pct: 0.50 },
    { tier: 'fast', pct: 0.25 },
    { tier: 'mini', pct: 0.10 },
  ];

  let totalCost = 0;
  const cost_by_tier: CostByTier[] = tierDistribution.map(({ tier, pct }) => {
    const tierInvocations = Math.round(totalInvocations * pct);
    const tierCost = tierInvocations * (COST_PER_INVOCATION[tier] || 0.01);
    totalCost += tierCost;
    return {
      tier,
      cost_usd: tierCost,
      percentage: pct * 100,
    };
  });

  // Build per-agent cost from agents array
  const cost_by_agent: CostByAgent[] = (agents || []).slice(0, 8).map((agent: any) => {
    const agentInvocations = Math.round(INVOCATIONS_PER_TASK * (agent.status === 'RUNNING' ? 0.6 : 1.0));
    return {
      agent: agent.name || agent.instance_id || 'unknown',
      cost_usd: agentInvocations * COST_PER_INVOCATION.standard,
      invocations: agentInvocations,
    };
  });

  // If no agents in response, derive from tasks
  if (cost_by_agent.length === 0 && tasks.length > 0) {
    const agentMap = new Map<string, { cost: number; invocations: number }>();
    for (const task of tasks.slice(0, 10)) {
      const name = task.agent?.name || 'fde-pipeline';
      const existing = agentMap.get(name) || { cost: 0, invocations: 0 };
      existing.invocations += INVOCATIONS_PER_TASK;
      existing.cost += INVOCATIONS_PER_TASK * COST_PER_INVOCATION.standard;
      agentMap.set(name, existing);
    }
    for (const [agent, data] of agentMap) {
      cost_by_agent.push({ agent, cost_usd: data.cost, invocations: data.invocations });
    }
  }

  // Threshold: $5/day budget for dev environment
  const DAILY_THRESHOLD = 5.0;

  return {
    total_cost_usd: totalCost,
    cost_by_agent,
    cost_by_tier,
    threshold_exceeded: totalCost > DAILY_THRESHOLD,
    threshold_usd: DAILY_THRESHOLD,
    period: 'Last 24 hours',
  };
}

// ─── GateHistoryCard Props ───────────────────────────────────────────────────

export interface GateHistoryEntry {
  gate_name: string;
  status: 'pass' | 'fail' | 'warn' | 'pending';
  timestamp: string;
  feedback?: string;
}

/**
 * Maps factoryData.tasks[].events → GateHistoryCard props.
 *
 * Extracts all gate-type events from the most recent tasks and normalizes
 * them into the GateHistoryEntry[] format the card expects.
 */
export function mapGateHistory(data: DashboardData | null, taskId?: string): GateHistoryEntry[] {
  if (!data?.tasks || data.tasks.length === 0) return [];

  // If a specific task is requested, filter to that task
  const targetTasks = taskId
    ? data.tasks.filter((t) => t.task_id === taskId)
    : data.tasks;

  const entries: GateHistoryEntry[] = [];

  for (const task of targetTasks) {
    if (!task.events) continue;

    for (const event of task.events) {
      if (event.type !== 'gate') continue;

      const status: GateHistoryEntry['status'] =
        event.gate_result === 'pass' ? 'pass' :
        event.gate_result === 'fail' ? 'fail' :
        event.gate_result === 'warn' ? 'warn' : 'pending';

      entries.push({
        gate_name: event.gate_name || 'Unknown Gate',
        status,
        timestamp: event.ts,
        feedback: event.msg || event.criteria || undefined,
      });
    }
  }

  // Sort by timestamp descending (most recent first)
  entries.sort((a, b) => b.timestamp.localeCompare(a.timestamp));

  return entries;
}

// ─── LiveTimeline Props ──────────────────────────────────────────────────────

export interface TimelineEvent {
  type: 'stage_start' | 'stage_complete' | 'stage_error' | 'info' | 'warning';
  timestamp: string;
  message: string;
  status: 'running' | 'success' | 'error' | 'pending' | 'skipped';
}

/**
 * Maps factoryData.tasks[].events → LiveTimeline props.
 *
 * Transforms raw TaskEvent[] into the TimelineEvent[] format, mapping
 * event types to timeline display categories.
 *
 * Key improvement: filters out low-level tool calls (run_shell_command, etc.)
 * and surfaces only meaningful pipeline events (stage transitions, gate results,
 * agent milestones). Raw tool calls are aggregated into a single "processing"
 * indicator rather than flooding the timeline.
 */
export function mapLiveTimeline(data: DashboardData | null): TimelineEvent[] {
  if (!data?.tasks || data.tasks.length === 0) return [];

  // Get events from the most recently active tasks
  const activeTasks = [...data.tasks]
    .filter((t) => t.status === 'running' || t.events?.length > 0)
    .sort((a, b) => {
      if (a.status === 'running' && b.status !== 'running') return -1;
      if (b.status === 'running' && a.status !== 'running') return 1;
      const aLast = a.events?.[a.events.length - 1]?.ts || '';
      const bLast = b.events?.[b.events.length - 1]?.ts || '';
      return bLast.localeCompare(aLast);
    })
    .slice(0, 3);

  const timeline: TimelineEvent[] = [];

  for (const task of activeTasks) {
    if (!task.events) continue;

    // Track tool call count for aggregation
    let pendingToolCalls = 0;
    let lastToolCallTs = '';

    for (const event of task.events) {
      // Filter: skip raw tool calls — aggregate them instead
      if (isToolCallNoise(event)) {
        pendingToolCalls++;
        lastToolCallTs = event.ts;
        continue;
      }

      // Flush aggregated tool calls as a single "processing" entry
      if (pendingToolCalls > 0) {
        timeline.push({
          type: 'info',
          timestamp: lastToolCallTs,
          message: `[${task.task_id.slice(-8)}] Processing (${pendingToolCalls} operations)`,
          status: 'success',
        });
        pendingToolCalls = 0;
      }

      // Map meaningful events with human-readable messages
      const timelineType = mapEventType(event);
      const timelineStatus = mapEventStatus(event, task.status);
      const message = formatEventMessage(event, task.task_id);

      timeline.push({
        type: timelineType,
        timestamp: event.ts,
        message,
        status: timelineStatus,
      });
    }

    // Flush remaining tool calls
    if (pendingToolCalls > 0) {
      timeline.push({
        type: 'info',
        timestamp: lastToolCallTs,
        message: `[${task.task_id.slice(-8)}] Processing (${pendingToolCalls} operations)`,
        status: task.status === 'running' ? 'running' : 'success',
      });
    }
  }

  // Sort reverse-chronologically (newest first)
  timeline.sort((a, b) => b.timestamp.localeCompare(a.timestamp));

  return timeline;
}

/**
 * Determines if an event is low-level tool call noise that should be aggregated.
 */
function isToolCallNoise(event: TaskEvent): boolean {
  const msg = (event.msg || '').toLowerCase();
  const noisePatterns = [
    'run_shell_command',
    'tool #',
    'tool_use',
    'read_file',
    'write_file',
    'list_directory',
    'str_replace',
  ];
  return noisePatterns.some((pattern) => msg.includes(pattern));
}

/**
 * Formats an event into a human-readable message for the timeline.
 * Extracts the meaningful content from raw event messages.
 *
 * For "reasoning" type events, renders the criteria and context fields
 * to provide explainability (WHY decisions were made).
 */
function formatEventMessage(event: TaskEvent, taskId: string): string {
  const prefix = `[${taskId.slice(-8)}]`;
  const msg = event.msg || '';

  // Reasoning events — show decision rationale (explainability layer)
  if (event.type === 'reasoning') {
    let formatted = `${prefix} ${msg}`;
    if (event.criteria) {
      formatted += ` \u2014 ${event.criteria}`;
    }
    return formatted;
  }

  // Gate events — show gate name and result
  if (event.type === 'gate') {
    const result = event.gate_result === 'pass' ? '\u2713' : event.gate_result === 'fail' ? '\u2717' : '\u26A0';
    return `${prefix} Gate ${result} ${event.gate_name || 'unknown'}`;
  }

  // Stage events — extract stage name
  if (msg.includes('Stage started') || msg.includes('started:')) {
    const stageName = msg.replace(/.*started:?\s*/i, '').trim() || 'execution';
    return `${prefix} \u25B6 Stage: ${stageName}`;
  }
  if (msg.includes('Stage complete') || msg.includes('complete:')) {
    const stageName = msg.replace(/.*complete:?\s*/i, '').trim() || 'execution';
    return `${prefix} \u2713 Stage complete: ${stageName}`;
  }

  // Error events — show error type
  if (event.type === 'error') {
    return `${prefix} \u2717 Error: ${msg}`;
  }

  // Default: show full message (CSS handles overflow via text wrapping)
  return `${prefix} ${msg}`;
}

function mapEventType(event: TaskEvent): TimelineEvent['type'] {
  if (event.type === 'reasoning') return 'stage_start';  // Reasoning events are milestones
  if (event.msg?.includes('Stage started') || event.msg?.includes('started:')) return 'stage_start';
  if (event.msg?.includes('Stage complete') || event.msg?.includes('complete:')) return 'stage_complete';
  if (event.type === 'error') return 'stage_error';
  if (event.type === 'gate' && event.gate_result === 'fail') return 'warning';
  return 'info';
}

function mapEventStatus(event: TaskEvent, taskStatus: string): TimelineEvent['status'] {
  if (event.type === 'error') return 'error';
  if (event.type === 'gate' && event.gate_result === 'fail') return 'error';
  if (event.type === 'gate' && event.gate_result === 'pass') return 'success';
  if (event.msg?.includes('Stage complete') || event.msg?.includes('complete:')) return 'success';
  if (event.msg?.includes('Stage started') || event.msg?.includes('started:')) {
    return taskStatus === 'running' ? 'running' : 'success';
  }
  return 'pending';
}

// ─── SquadExecutionCard Props ────────────────────────────────────────────────

export interface AgentExecution {
  role: string;
  status: 'running' | 'complete' | 'error' | 'waiting' | 'paused';
  model_tier: string;
  stage: string;
  duration_seconds: number;
}

/**
 * Maps factoryData.agents → SquadExecutionCard props.
 *
 * Transforms the raw agent lifecycle data into the AgentExecution[] format
 * the card expects, inferring model tier and stage from agent metadata.
 */
export function mapSquadExecution(data: DashboardData | null): AgentExecution[] {
  if (!data) return [];

  const { agents, tasks } = data;

  // If we have agents from the lifecycle table, use them directly
  if (agents && agents.length > 0) {
    return agents.map((agent: any) => {
      const status = mapAgentStatus(agent.status);
      const durationMs = agent.execution_time_ms || 0;

      // Infer model tier from agent name (convention: name includes tier hint)
      const modelTier = inferModelTier(agent.name || '');

      // Find the task this agent is working on to get the current stage
      const assignedTask = tasks?.find((t) => t.agent?.instance_id === agent.instance_id);
      const stage = assignedTask?.current_stage || 'idle';

      return {
        role: agent.name || agent.instance_id || 'agent',
        status,
        model_tier: modelTier,
        stage,
        duration_seconds: Math.round(durationMs / 1000),
      };
    });
  }

  // Fallback: derive squad from tasks with assigned agents
  const agentTasks = tasks?.filter((t) => t.agent) || [];
  return agentTasks.slice(0, 8).map((task) => ({
    role: task.agent?.name || 'fde-pipeline',
    status: mapAgentStatus(task.status === 'running' ? 'RUNNING' : task.status === 'completed' ? 'COMPLETED' : 'CREATED'),
    model_tier: inferModelTier(task.agent?.name || ''),
    stage: task.current_stage || 'unknown',
    duration_seconds: Math.round((task.elapsed_ms || task.duration_ms || 0) / 1000),
  }));
}

function mapAgentStatus(rawStatus: string): AgentExecution['status'] {
  const mapping: Record<string, AgentExecution['status']> = {
    RUNNING: 'running',
    INITIALIZING: 'running',
    CREATED: 'waiting',
    COMPLETED: 'complete',
    FAILED: 'error',
    TERMINATED: 'complete',
    STOPPED: 'paused',
  };
  return mapping[rawStatus] || 'waiting';
}

function inferModelTier(agentName: string): string {
  const name = agentName.toLowerCase();
  if (name.includes('architect') || name.includes('reviewer') || name.includes('security')) return 'frontier';
  if (name.includes('swe') || name.includes('developer') || name.includes('code')) return 'standard';
  if (name.includes('task') || name.includes('intake') || name.includes('reporting')) return 'fast';
  return 'standard';
}
