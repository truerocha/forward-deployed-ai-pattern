/**
 * GoldenSignalsCard — 4 Golden Signals of SRE applied to the SDLC.
 *
 * Consolidates scattered metrics into the SRE framework:
 *   1. Latency: how fast tasks flow through the pipeline
 *   2. Traffic: volume of work being processed
 *   3. Errors: failure rates and dispatch issues
 *   4. Saturation: capacity utilization and bottlenecks
 *
 * Data sources: /status/tasks (metrics + dora) and /status/health (checks)
 * Renders nothing when no data is available (suppressed by hasData filter).
 *
 * Ref: Google SRE Book Ch.6 — Monitoring Distributed Systems
 */

import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Badge from '@cloudscape-design/components/badge';

// ─── Types ──────────────────────────────────────────────────────

interface GoldenSignalsMetrics {
  active: number;
  completed_24h: number;
  failed_24h: number;
  avg_duration_ms: number;
  active_agents: number;
  dispatch_stuck: number;
  dora: {
    lead_time_avg_ms: number;
    success_rate_pct: number;
    throughput_24h: number;
    change_failure_rate_pct: number;
    level: string;
  };
}

interface HealthCheck {
  name: string;
  status: string;
  detail: string;
}

interface GoldenSignalsHealth {
  status: string;
  checks: HealthCheck[];
}

interface GoldenSignalsCardProps {
  metrics: GoldenSignalsMetrics | null;
  health: GoldenSignalsHealth | null;
  routingHealth?: {
    orchestrator_ready: boolean;
    circuit_state: string;
    updated_by: string;
    updated_at: string;
    blast_radius?: {
      detection_window_min: number;
      max_failures_before_deregister: number;
      max_tasks_affected: number;
    };
  } | null;
}

// ─── Signal Status Logic ────────────────────────────────────────

type SignalStatus = 'success' | 'warning' | 'error';

function getLatencyStatus(avgMs: number): SignalStatus {
  const minutes = avgMs / 60000;
  if (minutes < 15) return 'success';
  if (minutes <= 60) return 'warning';
  return 'error';
}

function getErrorsStatus(cfr: number, failed: number, stuck: number): SignalStatus {
  if (cfr > 15 || failed > 3 || stuck > 2) return 'error';
  if (cfr > 5 || failed > 0 || stuck > 0) return 'warning';
  return 'success';
}

function getSaturationStatus(activeAgents: number, maxAgents: number, stuckCount: number): SignalStatus {
  const pct = maxAgents > 0 ? (activeAgents / maxAgents) * 100 : 0;
  if (pct > 80 || stuckCount > 2) return 'error';
  if (pct > 50 || stuckCount > 0) return 'warning';
  return 'success';
}

function getTrafficStatus(throughput: number): SignalStatus {
  if (throughput >= 5) return 'success';
  if (throughput >= 1) return 'warning';
  return 'warning';
}

function getOverallStatus(statuses: SignalStatus[]): SignalStatus {
  if (statuses.includes('error')) return 'error';
  if (statuses.includes('warning')) return 'warning';
  return 'success';
}

function formatDuration(ms: number): string {
  const minutes = ms / 60000;
  if (minutes < 1) return `${(ms / 1000).toFixed(0)}s`;
  if (minutes < 60) return `${minutes.toFixed(1)} min`;
  return `${(minutes / 60).toFixed(1)}h`;
}

function extractStuckCount(health: GoldenSignalsHealth | null): number {
  if (!health?.checks) return 0;
  const stuckCheck = health.checks.find((c) => c.name === 'stuck_tasks');
  if (!stuckCheck || stuckCheck.status === 'pass') return 0;
  const match = stuckCheck.detail.match(/(\d+)/);
  return match ? parseInt(match[1], 10) : 0;
}

function extractCapacityPct(health: GoldenSignalsHealth | null): number {
  if (!health?.checks) return 0;
  const capCheck = health.checks.find((c) => c.name === 'agent_capacity');
  if (!capCheck) return 0;
  const match = capCheck.detail.match(/(\d+)%/);
  return match ? parseInt(match[1], 10) : 0;
}

// ─── Component ──────────────────────────────────────────────────

export const GoldenSignalsCard: React.FC<GoldenSignalsCardProps> = ({ metrics, health, routingHealth }) => {
  if (!metrics) return null;

  const dora = metrics.dora || { lead_time_avg_ms: 0, throughput_24h: 0, change_failure_rate_pct: 0, success_rate_pct: 0, level: 'Low' };
  const stuckCount = extractStuckCount(health);
  const capacityPct = extractCapacityPct(health);

  const latencyStatus = getLatencyStatus(metrics.avg_duration_ms);
  const trafficStatus = getTrafficStatus(dora.throughput_24h);
  const errorsStatus = getErrorsStatus(dora.change_failure_rate_pct, metrics.failed_24h, metrics.dispatch_stuck);
  const saturationStatus = getSaturationStatus(metrics.active_agents, 10, stuckCount);
  const overallStatus = getOverallStatus([latencyStatus, errorsStatus, saturationStatus]);

  return (
    <Container
      header={
        <Header
          variant="h3"
          description="SRE signals applied to the SDLC pipeline"
          actions={
            <div data-testid="overall-health" data-status={overallStatus}>
              <Badge color={overallStatus === 'success' ? 'green' : overallStatus === 'warning' ? 'blue' : 'red'}>
                {overallStatus === 'success' ? 'HEALTHY' : overallStatus === 'warning' ? 'DEGRADED' : 'CRITICAL'}
              </Badge>
            </div>
          }
        >
          Golden Signals
        </Header>
      }
    >
      <ColumnLayout columns={4} variant="text-grid">
        {/* Signal 1: Latency */}
        <div data-testid="latency-status" data-status={latencyStatus}>
          <Box variant="awsui-key-label">Latency</Box>
          <StatusIndicator type={latencyStatus}>
            {formatDuration(metrics.avg_duration_ms)}
          </StatusIndicator>
          <Box fontSize="body-s" color="text-body-secondary">avg pipeline time</Box>
        </div>

        {/* Signal 2: Traffic */}
        <div data-testid="traffic-status" data-status={trafficStatus}>
          <Box variant="awsui-key-label">Traffic</Box>
          <SpaceBetween size="xxs">
            <StatusIndicator type={trafficStatus}>
              {dora.throughput_24h} tasks/24h
            </StatusIndicator>
            <Box fontSize="body-s" color="text-body-secondary">
              {metrics.active_agents} active agents
            </Box>
          </SpaceBetween>
        </div>

        {/* Signal 3: Errors */}
        <div data-testid="errors-status" data-status={errorsStatus}>
          <Box variant="awsui-key-label">Errors</Box>
          <SpaceBetween size="xxs">
            <StatusIndicator type={errorsStatus}>
              {dora.change_failure_rate_pct}% CFR
            </StatusIndicator>
            <Box fontSize="body-s" color="text-body-secondary">
              {metrics.failed_24h} failed (24h)
            </Box>
            {metrics.dispatch_stuck > 0 && (
              <Box fontSize="body-s" color="text-status-error">
                {metrics.dispatch_stuck} dispatch blocked
              </Box>
            )}
          </SpaceBetween>
        </div>

        {/* Signal 4: Saturation */}
        <div data-testid="saturation-status" data-status={saturationStatus}>
          <Box variant="awsui-key-label">Saturation</Box>
          <SpaceBetween size="xxs">
            <StatusIndicator type={saturationStatus}>
              {capacityPct}% capacity
            </StatusIndicator>
            {stuckCount > 0 && (
              <Box fontSize="body-s" color="text-status-error">
                {stuckCount} stuck tasks
              </Box>
            )}
          </SpaceBetween>
        </div>

        {/* Signal 5: Routing Health (Circuit Breaker) */}
        {routingHealth && (
          <div data-testid="routing-status">
            <Box variant="awsui-key-label">Routing</Box>
            <SpaceBetween size="xxs">
              <StatusIndicator type={routingHealth.circuit_state === 'closed' ? 'success' : 'warning'}>
                {routingHealth.circuit_state === 'closed' ? 'Orchestrator active' : 'Monolith fallback'}
              </StatusIndicator>
              <Box fontSize="body-s" color="text-body-secondary">
                Circuit: {routingHealth.circuit_state}
              </Box>
              {routingHealth.blast_radius && (
                <Box fontSize="body-s" color="text-body-secondary">
                  Blast radius: {routingHealth.blast_radius.max_tasks_affected} tasks max
                </Box>
              )}
            </SpaceBetween>
          </div>
        )}
      </ColumnLayout>
    </Container>
  );
};
