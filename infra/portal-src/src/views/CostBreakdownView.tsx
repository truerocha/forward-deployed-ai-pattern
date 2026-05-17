/**
 * CostBreakdownView — Dedicated RAIL view for cost analysis.
 *
 * Promoted from persona cards (PM, SRE, Staff) to its own navigation item
 * because cost data is cross-persona and needs drill-down detail that exceeds
 * a single dashboard card.
 */
import React from 'react';

import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import Grid from '@cloudscape-design/components/grid';
import Container from '@cloudscape-design/components/container';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Badge from '@cloudscape-design/components/badge';

import { mapCostMetrics } from '../mappers/factoryDataMapper';

interface CostBreakdownViewProps {
  factoryData: any;
}

export const CostBreakdownView: React.FC<CostBreakdownViewProps> = ({ factoryData }) => {
  const summary = mapCostMetrics(factoryData);

  if (!summary) {
    return (
      <ContentLayout header={<Header variant="h1">Cost Breakdown</Header>}>
        <Container>
          <Box textAlign="center" padding="xl" color="inherit">
            <StatusIndicator type="pending">
              No cost data available. Data will appear once tasks execute.
            </StatusIndicator>
          </Box>
        </Container>
      </ContentLayout>
    );
  }

  const totalInvocations = summary.cost_by_agent.reduce((sum, a) => sum + a.invocations, 0);

  // Deduplicate agents: aggregate costs by unique agent name
  const agentMap = new Map<string, { cost: number; invocations: number }>();
  for (const agent of summary.cost_by_agent) {
    const existing = agentMap.get(agent.agent) || { cost: 0, invocations: 0 };
    agentMap.set(agent.agent, {
      cost: existing.cost + agent.cost_usd,
      invocations: existing.invocations + agent.invocations,
    });
  }
  const sortedAgents = Array.from(agentMap.entries())
    .sort((a, b) => b[1].cost - a[1].cost);
  const maxAgentCost = sortedAgents.length > 0 ? sortedAgents[0][1].cost : 0.001;

  return (
    <ContentLayout
      header={
        <Header
          variant="h1"
          description={summary.period || 'Current execution period'}
          actions={
            summary.threshold_exceeded ? (
              <Badge color="red">Over Budget</Badge>
            ) : (
              <Badge color="green">Within Budget</Badge>
            )
          }
        >
          Cost Breakdown
        </Header>
      }
    >
      <SpaceBetween size="l">
        {/* Summary row */}
        <Grid gridDefinition={[
          { colspan: { l: 6, m: 6, default: 12 } },
          { colspan: { l: 6, m: 6, default: 12 } },
        ]}>
          <Container header={<Header variant="h3">Execution Summary</Header>}>
            <ColumnLayout columns={3} variant="text-grid">
              <div>
                <Box variant="awsui-key-label">Total Cost</Box>
                <Box variant="awsui-value-large">${summary.total_cost_usd.toFixed(4)}</Box>
              </div>
              <div>
                <Box variant="awsui-key-label">Budget Limit</Box>
                <Box variant="awsui-value-large">
                  {summary.threshold_usd ? `$${summary.threshold_usd.toFixed(2)}` : '—'}
                </Box>
              </div>
              <div>
                <Box variant="awsui-key-label">Total Invocations</Box>
                <Box variant="awsui-value-large">{totalInvocations.toLocaleString()}</Box>
              </div>
            </ColumnLayout>
          </Container>

          <Container
            header={<Header variant="h3">Budget Usage</Header>}
            footer={
              <Box fontSize="body-s" color="text-body-secondary">
                {summary.threshold_exceeded
                  ? 'Budget threshold exceeded — review agent tier allocation'
                  : 'Budget consumption within acceptable range'}
              </Box>
            }
          >
            <ProgressBar
              value={summary.threshold_usd
                ? Math.min((summary.total_cost_usd / summary.threshold_usd) * 100, 100)
                : 0}
              label="Budget consumed"
              additionalInfo={summary.threshold_usd
                ? `$${summary.total_cost_usd.toFixed(4)} of $${summary.threshold_usd.toFixed(2)}`
                : 'No budget threshold configured'}
              status={summary.threshold_exceeded ? 'error' : 'in-progress'}
              variant="standalone"
            />
          </Container>
        </Grid>

        {/* Tier + Agent breakdown — side by side on desktop */}
        <Grid gridDefinition={[
          { colspan: { l: 6, m: 6, default: 12 } },
          { colspan: { l: 6, m: 6, default: 12 } },
        ]}>
          <Container
            header={
              <Header variant="h3" description="Cost distribution across LLM model tiers">
                Cost by Model Tier
              </Header>
            }
            footer={
              <Box fontSize="body-s" color="text-body-secondary">
                {summary.cost_by_tier.length} tier(s) active
              </Box>
            }
          >
            <SpaceBetween size="s">
              {summary.cost_by_tier.map((tier) => (
                <div key={tier.tier}>
                  <ProgressBar
                    value={tier.percentage}
                    label={tier.tier}
                    additionalInfo={`$${tier.cost_usd.toFixed(4)} (${tier.percentage.toFixed(1)}%)`}
                    variant="standalone"
                  />
                </div>
              ))}
            </SpaceBetween>
          </Container>

          <Container
            header={
              <Header variant="h3" description="Cost attribution per squad agent">
                Cost by Agent
              </Header>
            }
            footer={
              <Box fontSize="body-s" color="text-body-secondary">
                {sortedAgents.length} agent(s) with cost data
              </Box>
            }
          >
            <SpaceBetween size="s">
              {sortedAgents.map(([name, data]) => (
                <div key={name}>
                  <ProgressBar
                    value={(data.cost / maxAgentCost) * 100}
                    label={name}
                    additionalInfo={`$${data.cost.toFixed(4)} · ${data.invocations} invocations`}
                    variant="standalone"
                  />
                </div>
              ))}
            </SpaceBetween>
          </Container>
        </Grid>

        {/* Cost alerts */}
        <Container
          header={<Header variant="h3">Cost Alerts</Header>}
          footer={
            <Box fontSize="body-s" color="text-body-secondary">
              Alerts trigger when cost exceeds configured thresholds
            </Box>
          }
        >
          {summary.threshold_exceeded ? (
            <StatusIndicator type="error">
              Budget threshold exceeded: ${summary.total_cost_usd.toFixed(4)} &gt; ${summary.threshold_usd?.toFixed(2) || '?'}
            </StatusIndicator>
          ) : (
            <StatusIndicator type="success">
              All cost metrics within acceptable thresholds
            </StatusIndicator>
          )}
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
};
