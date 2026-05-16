/**
 * A2AWorkflowCostCard — Token consumption and cost breakdown per workflow.
 *
 * Displays financial metrics for A2A workflow executions:
 *   - Total cost (USD) per workflow based on Bedrock token pricing
 *   - Cost distribution by agent (pesquisa/escrita/revisao)
 *   - Rework cost (tokens wasted on rejected deliverables)
 *   - Approval rate (first-pass vs multi-pass)
 *
 * Persona: PM, Architect
 * Data Source: Bedrock InvocationMetrics + DynamoDB workflow metricas_execucao
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import BarChart from '@cloudscape-design/components/bar-chart';
import Badge from '@cloudscape-design/components/badge';
import ColumnLayout from '@cloudscape-design/components/column-layout';

interface AgentCost {
  agent: string;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
}

interface A2AWorkflowCostCardProps {
  totalCostUsd?: number;
  agentCosts?: AgentCost[];
  reworkCostUsd?: number;
  approvalRate?: number;
  totalWorkflows?: number;
  avgCostPerWorkflow?: number;
}

export const A2AWorkflowCostCard: React.FC<A2AWorkflowCostCardProps> = ({
  totalCostUsd = 0,
  agentCosts = [],
  reworkCostUsd = 0,
  approvalRate = 0,
  totalWorkflows = 0,
  avgCostPerWorkflow = 0,
}) => {
  const barData = agentCosts.map((ac) => ({
    x: ac.agent,
    y: ac.costUsd,
  }));

  return (
    <Container
      header={
        <Header
          variant="h3"
          description="Token consumption and cost analysis for A2A workflows"
          info={<Badge color="grey">BEDROCK</Badge>}
        >
          Workflow Cost
        </Header>
      }
    >
      <SpaceBetween size="m">
        <ColumnLayout columns={4} variant="text-grid">
          <div>
            <Box variant="awsui-key-label">Total Cost (24h)</Box>
            <Box variant="awsui-value-large">${totalCostUsd.toFixed(4)}</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Avg per Workflow</Box>
            <Box variant="awsui-value-large">${avgCostPerWorkflow.toFixed(4)}</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Rework Waste</Box>
            <Box variant="awsui-value-large" color="text-status-error">
              ${reworkCostUsd.toFixed(4)}
            </Box>
          </div>
          <div>
            <Box variant="awsui-key-label">First-Pass Approval</Box>
            <Box variant="awsui-value-large">
              {(approvalRate * 100).toFixed(0)}%
            </Box>
          </div>
        </ColumnLayout>

        {agentCosts.length > 0 && (
          <BarChart
            series={[
              {
                title: 'Cost (USD)',
                type: 'bar',
                data: barData,
              },
            ]}
            xTitle="Agent"
            yTitle="Cost (USD)"
            hideFilter
            height={200}
            empty="No cost data available"
            noMatch="No matching data"
          />
        )}

        {agentCosts.length > 0 && (
          <KeyValuePairs
            columns={3}
            items={agentCosts.map((ac) => ({
              label: ac.agent,
              value: `${(ac.inputTokens / 1000).toFixed(1)}K in / ${(ac.outputTokens / 1000).toFixed(1)}K out`,
            }))}
          />
        )}

        <Box textAlign="center" variant="small" color="text-body-secondary">
          {totalWorkflows} total workflows • Pricing: Claude 3.5 Sonnet ($3/$15 per 1M tokens)
        </Box>
      </SpaceBetween>
    </Container>
  );
};
