/**
 * SquadExecutionCard — Squad agent execution using Cloudscape Container + ProgressBar.
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import Badge from '@cloudscape-design/components/badge';

interface AgentExecution {
  role: string;
  status: 'running' | 'complete' | 'error' | 'waiting' | 'paused';
  model_tier: string;
  stage: string;
  duration_seconds: number;
}

interface SquadExecutionCardProps {
  agents?: AgentExecution[] | null;
}

function mapAgentStatus(status: string): 'success' | 'error' | 'in-progress' | 'pending' | 'stopped' {
  switch (status) {
    case 'running': return 'in-progress';
    case 'complete': return 'success';
    case 'error': return 'error';
    case 'waiting': return 'pending';
    default: return 'stopped';
  }
}

function getTierBadgeColor(tier: string): 'blue' | 'green' | 'grey' | 'red' {
  switch (tier) {
    case 'frontier': return 'red';
    case 'standard': return 'blue';
    case 'fast': return 'green';
    default: return 'grey';
  }
}

const formatDuration = (seconds: number): string => {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`;
};

export const SquadExecutionCard: React.FC<SquadExecutionCardProps> = ({ agents }) => {
  if (!agents || agents.length === 0) {
    return (
      <Container header={<Header variant="h3">Squad Execution</Header>}>
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">No active agents</StatusIndicator>
        </Box>
      </Container>
    );
  }

  const runningCount = agents.filter((a) => a.status === 'running').length;
  const completeCount = agents.filter((a) => a.status === 'complete').length;
  const maxDuration = Math.max(...agents.map((a) => a.duration_seconds), 1);

  return (
    <Container
      header={
        <Header
          variant="h3"
          counter={`(${agents.length})`}
          description={`${runningCount} active • ${completeCount}/${agents.length} done`}
        >
          Squad Execution
        </Header>
      }
      footer={
        <Box fontSize="body-s" color="text-body-secondary">
          {agents.length} agents in squad
        </Box>
      }
    >
      <SpaceBetween size="s">
        {agents.map((agent, idx) => {
          const progressPercent = agent.status === 'complete' ? 100 : (agent.duration_seconds / maxDuration) * 80;
          return (
            <div key={`${agent.role}-${idx}`}>
              <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                <StatusIndicator type={mapAgentStatus(agent.status)}>{agent.role}</StatusIndicator>
                <Badge color={getTierBadgeColor(agent.model_tier)}>{agent.model_tier}</Badge>
                <Box fontSize="body-s" color="text-body-secondary">{formatDuration(agent.duration_seconds)}</Box>
              </SpaceBetween>
              <ProgressBar
                value={progressPercent}
                variant="standalone"
                additionalInfo={agent.stage}
                status={agent.status === 'error' ? 'error' : agent.status === 'running' ? 'in-progress' : undefined}
              />
            </div>
          );
        })}
      </SpaceBetween>
    </Container>
  );
};
