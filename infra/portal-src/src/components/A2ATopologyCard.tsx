/**
 * A2ATopologyCard — Visual representation of the A2A agent graph topology.
 *
 * Shows the workflow graph (PESQUISA → ESCRITA → REVISAO) with real-time
 * status indicators and latency metrics from OpenTelemetry spans.
 *
 * Persona: Architect, Staff Engineer
 * Data Source: OTel traces (X-Ray) + DynamoDB workflow state
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Grid from '@cloudscape-design/components/grid';
import Box from '@cloudscape-design/components/box';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import SpaceBetween from '@cloudscape-design/components/space-between';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import Badge from '@cloudscape-design/components/badge';

interface AgentNode {
  name: string;
  endpoint: string;
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown';
  latencyP95Ms: number;
  latencyP99Ms: number;
  requestsPerMin: number;
  errorRate: number;
  lastHealthCheck: string;
}

interface A2ATopologyCardProps {
  agents?: AgentNode[];
  workflowActive?: boolean;
  totalWorkflows24h?: number;
}

const DEFAULT_AGENTS: AgentNode[] = [
  { name: 'Pesquisa', endpoint: 'pesquisa.fde.local:9001', status: 'unknown', latencyP95Ms: 0, latencyP99Ms: 0, requestsPerMin: 0, errorRate: 0, lastHealthCheck: '-' },
  { name: 'Escrita', endpoint: 'escrita.fde.local:9002', status: 'unknown', latencyP95Ms: 0, latencyP99Ms: 0, requestsPerMin: 0, errorRate: 0, lastHealthCheck: '-' },
  { name: 'Revisão', endpoint: 'revisao.fde.local:9003', status: 'unknown', latencyP95Ms: 0, latencyP99Ms: 0, requestsPerMin: 0, errorRate: 0, lastHealthCheck: '-' },
];

const statusMap = {
  healthy: 'success' as const,
  degraded: 'warning' as const,
  unhealthy: 'error' as const,
  unknown: 'pending' as const,
};

export const A2ATopologyCard: React.FC<A2ATopologyCardProps> = ({
  agents = DEFAULT_AGENTS,
  workflowActive = false,
  totalWorkflows24h = 0,
}) => {
  return (
    <Container
      header={
        <Header
          variant="h3"
          description="Agent-to-Agent communication graph with latency metrics"
          info={workflowActive ? <Badge color="blue">ACTIVE</Badge> : undefined}
        >
          A2A Topology
        </Header>
      }
    >
      <SpaceBetween size="l">
        {/* Graph flow indicator */}
        <Box textAlign="center" padding="s" color="text-status-info">
          <span style={{ fontFamily: 'monospace', fontSize: '14px' }}>
            PESQUISA → ESCRITA → REVISÃO → [APROVADO | ↩ ESCRITA]
          </span>
        </Box>

        {/* Agent nodes */}
        <Grid gridDefinition={[{ colspan: 4 }, { colspan: 4 }, { colspan: 4 }]}>
          {agents.map((agent) => (
            <div key={agent.name}>
              <Container variant="stacked">
                <SpaceBetween size="xs">
                  <Box variant="h4">
                    <StatusIndicator type={statusMap[agent.status]}>
                      {agent.name}
                    </StatusIndicator>
                  </Box>
                  <Box variant="small" color="text-body-secondary">
                    {agent.endpoint}
                  </Box>
                  <KeyValuePairs
                    columns={2}
                    items={[
                      { label: 'P95', value: `${agent.latencyP95Ms}ms` },
                      { label: 'P99', value: `${agent.latencyP99Ms}ms` },
                      { label: 'RPM', value: String(agent.requestsPerMin) },
                      { label: 'Errors', value: `${(agent.errorRate * 100).toFixed(1)}%` },
                    ]}
                  />
                </SpaceBetween>
              </Container>
            </div>
          ))}
        </Grid>

        {/* Summary */}
        <Box textAlign="center" variant="small" color="text-body-secondary">
          {totalWorkflows24h} workflows executed in last 24h
        </Box>
      </SpaceBetween>
    </Container>
  );
};
