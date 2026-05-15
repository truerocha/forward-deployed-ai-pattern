/**
 * CostCard — Cost Breakdown using Cloudscape Container + ColumnLayout.
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Badge from '@cloudscape-design/components/badge';

interface CostByAgent {
  agent: string;
  cost_usd: number;
  invocations: number;
}

interface CostByTier {
  tier: string;
  cost_usd: number;
  percentage: number;
}

interface CostSummary {
  total_cost_usd: number;
  cost_by_agent: CostByAgent[];
  cost_by_tier: CostByTier[];
  threshold_exceeded: boolean;
  threshold_usd?: number;
  period?: string;
}

interface CostCardProps {
  summary?: CostSummary | null;
}

export const CostCard: React.FC<CostCardProps> = ({ summary }) => {
  if (!summary) {
    return (
      <Container header={<Header variant="h3">Cost Breakdown</Header>}>
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">No cost data available</StatusIndicator>
        </Box>
      </Container>
    );
  }

  const maxAgentCost = Math.max(...summary.cost_by_agent.map((a) => a.cost_usd), 0.001);

  return (
    <Container
      header={
        <Header
          variant="h3"
          description={summary.period || 'Current period'}
          actions={
            summary.threshold_exceeded ? (
              <Badge color="red">Over Budget</Badge>
            ) : undefined
          }
        >
          Cost Breakdown
        </Header>
      }
      footer={
        <Box fontSize="body-s" color="text-body-secondary">
          {summary.cost_by_agent.reduce((sum, a) => sum + a.invocations, 0)} total invocations
        </Box>
      }
    >
      <SpaceBetween size="m">
        {/* Total cost */}
        <ColumnLayout columns={2} variant="text-grid">
          <div>
            <Box variant="awsui-key-label">Total Cost</Box>
            <Box variant="awsui-value-large">${summary.total_cost_usd.toFixed(4)}</Box>
          </div>
          {summary.threshold_usd && (
            <div>
              <Box variant="awsui-key-label">Budget Limit</Box>
              <Box variant="awsui-value-large">${summary.threshold_usd.toFixed(2)}</Box>
            </div>
          )}
        </ColumnLayout>

        {/* Tier breakdown */}
        <div>
          <Box fontSize="body-s" color="text-body-secondary" margin={{ bottom: 'xs' }}>By Model Tier</Box>
          <SpaceBetween size="xs">
            {summary.cost_by_tier.map((tier) => (
              <div key={tier.tier}>
                <ProgressBar
                  value={tier.percentage}
                  label={tier.tier}
                  additionalInfo={`$${tier.cost_usd.toFixed(4)}`}
                  variant="standalone"
                />
              </div>
            ))}
          </SpaceBetween>
        </div>

        {/* Per-agent breakdown */}
        <div>
          <Box fontSize="body-s" color="text-body-secondary" margin={{ bottom: 'xs' }}>By Agent</Box>
          <SpaceBetween size="xs">
            {summary.cost_by_agent.map((agent) => (
              <div key={agent.agent}>
                <ProgressBar
                  value={(agent.cost_usd / maxAgentCost) * 100}
                  label={agent.agent}
                  additionalInfo={`$${agent.cost_usd.toFixed(4)}`}
                  variant="standalone"
                />
              </div>
            ))}
          </SpaceBetween>
        </div>
      </SpaceBetween>
    </Container>
  );
};
