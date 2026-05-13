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
 * Maps factoryData → SquadExecutionCard props.
 *
 * Derives real agent names from task events' `phase` field rather than
 * the lifecycle table (which only has generic 'fde-pipeline' entries).
 * The phase field contains the actual agent role (e.g., 'swe-developer-agent',
 * 'swe-adversarial-agent', 'swe-dtl-commiter-agent').
 */
export function mapSquadExecution(data: DashboardData | null): AgentExecution[] {
  if (!data?.tasks) return [];

  const { tasks } = data;

  // Extract real agent names from task events' phase field
  const agentMap = new Map<string, { status: AgentExecution['status']; stage: string; lastTs: string; taskStatus: string }>();

  // Process active/recent tasks to find which agents have been active
  const recentTasks = [...tasks]
    .filter((t) => t.events?.length > 0)
    .sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
    .slice(0, 3);

  for (const task of recentTasks) {
    if (!task.events) continue;

    for (const event of task.events) {
      const phase = event.phase;
      if (!phase || phase === 'intake' || phase === 'workspace' || phase === 'review' || phase === 'completion') continue;

      const existing = agentMap.get(phase);
      const eventTs = event.ts || '';

      // Track the latest event per agent phase
      if (!existing || eventTs > existing.lastTs) {
        agentMap.set(phase, {
          status: task.status === 'running' || task.status === 'IN_PROGRESS' ? 'running' : 'complete',
          stage: task.current_stage || phase,
          lastTs: eventTs,
          taskStatus: task.status,
        });
      }
    }
  }

  // Convert to AgentExecution array
  if (agentMap.size > 0) {
    return Array.from(agentMap.entries()).map(([agentName, info]) => ({
      role: agentName,
      status: info.status,
      model_tier: inferModelTier(agentName),
      stage: info.stage,
      duration_seconds: 0, // Not available from events alone
    }));
  }

  // Fallback: if no events with phases, use lifecycle table
  const { agents } = data;
  if (agents && agents.length > 0) {
    return agents.map((agent: any) => {
      const assignedTask = tasks?.find((t) => t.agent?.instance_id === agent.instance_id);
      return {
        role: assignedTask?.current_stage || agent.name || agent.instance_id || 'agent',
        status: mapAgentStatus(agent.status),
        model_tier: inferModelTier(agent.name || ''),
        stage: assignedTask?.current_stage || 'idle',
        duration_seconds: Math.round((agent.execution_time_ms || 0) / 1000),
      };
    });
  }

  return [];
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

// ─── Agent Identity Resolution (Conductor Plan Metadata) ─────────────────────

import type { Agent, AgentRole } from '../types';

/**
 * Resolves agent identity from Conductor plan metadata stored in task events.
 *
 * The Conductor stores plan metadata in the task's knowledge_context which
 * gets emitted as events. This function cross-references ECS agent instances
 * with the Conductor's WorkflowPlan to produce rich agent identity:
 *   - Real role name (not "fde-pipeline")
 *   - Subtask description (what the agent is doing)
 *   - Model tier (fast/reasoning/deep)
 *   - Stage position (stage N of M)
 *   - Topology type (sequential/parallel/debate/recursive)
 *   - Synapse metadata (paradigm, design quality)
 *
 * Graceful degradation: when no Conductor metadata exists (legacy tasks or
 * monolith mode), falls back to the existing behavior.
 */
export function mapAgentsWithConductorPlan(data: DashboardData | null): Agent[] {
  if (!data) return [];

  const { agents, tasks } = data;

  // Try to extract Conductor plan from the most recent active task
  const conductorPlan = extractConductorPlan(tasks);
  const synapseData = extractSynapseAssessment(tasks);

  // If we have Conductor plan metadata, use it for rich agent identity
  if (conductorPlan && conductorPlan.steps && conductorPlan.steps.length > 0) {
    return mapFromConductorPlan(agents, conductorPlan, synapseData);
  }

  // Fallback: derive from task events (existing behavior, improved)
  return mapFromTaskEvents(data);
}

interface ConductorPlanMeta {
  topology: string;
  steps: Array<{
    subtask: string;
    agent_role: string;
    model_tier: string;
    step_index: number;
  }>;
  rationale: string;
  recursive_depth: number;
}

interface SynapseAssessmentMeta {
  paradigm: string;
  paradigm_confidence: number;
  design_quality_score: number;
  recommended_agents: number;
  coherent: boolean;
  epistemic_approach: string;
}

function extractConductorPlan(tasks: Task[]): ConductorPlanMeta | null {
  for (const task of tasks) {
    if (!task.events) continue;
    for (const event of task.events) {
      if (event.type === 'conductor_plan' || event.msg?.includes('_conductor_plan')) {
        try {
          const parsed = JSON.parse(event.context || event.msg || '{}');
          if (parsed.topology && parsed.steps) return parsed;
        } catch { /* continue searching */ }
      }
    }
  }

  for (const task of tasks) {
    const meta = (task as any)._conductor_plan || (task as any).conductor_plan;
    if (meta?.topology) return meta;
  }

  return null;
}

function extractSynapseAssessment(tasks: Task[]): SynapseAssessmentMeta | null {
  for (const task of tasks) {
    if (!task.events) continue;
    for (const event of task.events) {
      if (event.type === 'synapse_assessment' || event.msg?.includes('_synapse_assessment')) {
        try {
          const parsed = JSON.parse(event.context || event.msg || '{}');
          if (parsed.paradigm) return parsed;
        } catch { /* continue */ }
      }
    }
  }

  for (const task of tasks) {
    const meta = (task as any)._synapse_assessment || (task as any).synapse_assessment;
    if (meta?.paradigm) return meta;
  }

  return null;
}

function mapFromConductorPlan(
  rawAgents: DashboardData['agents'],
  plan: ConductorPlanMeta,
  synapse: SynapseAssessmentMeta | null,
): Agent[] {
  const totalStages = plan.steps.length;

  return plan.steps.map((step, idx) => {
    const matchedAgent = rawAgents.find((a) => a.task_id && a.status === 'RUNNING');
    const role = inferAgentRole(step.agent_role);
    const status = inferStepStatus(idx, rawAgents, totalStages);

    return {
      id: matchedAgent?.instance_id || `conductor-step-${idx}`,
      name: formatAgentName(step.agent_role),
      role,
      status,
      subtask: step.subtask,
      lastMessage: step.subtask,
      modelTier: step.model_tier,
      stageIndex: step.step_index + 1,
      totalStages,
      topology: plan.topology,
      paradigm: synapse?.paradigm,
      designQuality: synapse?.design_quality_score,
      progress: status === 'complete' ? 100 : status === 'working' ? 60 : 0,
      durationSeconds: 0,
    };
  });
}

function mapFromTaskEvents(data: DashboardData): Agent[] {
  const { tasks, agents } = data;
  const agentMap = new Map<string, { role: AgentRole; status: AgentStatus; subtask: string; lastTs: string }>();

  const recentTasks = [...tasks]
    .filter((t) => t.events?.length > 0)
    .sort((a, b) => (b.events?.[b.events.length - 1]?.ts || '').localeCompare(a.events?.[a.events.length - 1]?.ts || ''))
    .slice(0, 5);

  for (const task of recentTasks) {
    if (!task.events) continue;
    for (const event of task.events) {
      const phase = event.phase;
      if (!phase || phase === 'intake' || phase === 'workspace') continue;

      const existing = agentMap.get(phase);
      if (!existing || (event.ts || '') > existing.lastTs) {
        agentMap.set(phase, {
          role: inferAgentRole(phase),
          status: task.status === 'running' || task.status === 'IN_PROGRESS' ? 'working' : 'complete',
          subtask: event.msg || '',
          lastTs: event.ts || '',
        });
      }
    }
  }

  if (agentMap.size > 0) {
    return Array.from(agentMap.entries()).map(([name, info]) => ({
      id: name,
      name: formatAgentName(name),
      role: info.role,
      status: info.status,
      lastMessage: info.subtask || undefined,
      subtask: info.subtask || undefined,
      modelTier: inferModelTier(name),
      progress: info.status === 'complete' ? 100 : 50,
    }));
  }

  // Final fallback: raw ECS agents with better formatting
  return agents.slice(0, 10).map((a: any) => ({
    id: a.instance_id,
    name: a.name || 'fde-pipeline',
    role: 'coder' as const,
    status: a.status === 'RUNNING' ? 'working' as const :
            a.status === 'COMPLETED' ? 'complete' as const : 'idle' as const,
    lastMessage: a.task_id ? `Task: ${a.task_id.slice(-8)}` : undefined,
    progress: a.status === 'RUNNING' ? 50 : a.status === 'COMPLETED' ? 100 : 0,
  }));
}

function inferAgentRole(agentName: string): AgentRole {
  const name = agentName.toLowerCase();
  if (name.includes('tech-lead') || name.includes('intake') || name.includes('planner')) return 'planner';
  if (name.includes('architect')) return 'architect';
  if (name.includes('adversarial') || name.includes('redteam') || name.includes('security')) return 'adversarial';
  if (name.includes('fidelity') || name.includes('quality')) return 'fidelity';
  if (name.includes('reviewer')) return 'reviewer';
  if (name.includes('reporting') || name.includes('writer') || name.includes('commiter')) return 'reporting';
  if (name.includes('developer') || name.includes('swe') || name.includes('code')) return 'coder';
  return 'coder';
}

function formatAgentName(rawRole: string): string {
  return rawRole
    .replace(/-agent$/, '')
    .replace(/^(swe|fde)-/, (_, prefix) => prefix.toUpperCase() + ' ')
    .split('-')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
    .trim();
}

function inferStepStatus(
  stepIndex: number,
  rawAgents: DashboardData['agents'],
  totalSteps: number,
): AgentStatus {
  const runningCount = rawAgents.filter((a) => a.status === 'RUNNING').length;
  const completedCount = rawAgents.filter((a) => a.status === 'COMPLETED').length;

  if (runningCount === 0 && completedCount >= totalSteps) return 'complete';
  if (stepIndex < completedCount) return 'complete';
  if (stepIndex === completedCount && runningCount > 0) return 'working';
  return 'idle';
}
