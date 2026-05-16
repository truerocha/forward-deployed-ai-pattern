/**
 * A2AResilienceCard — DLQ status, retry metrics, and circuit breaker state.
 *
 * Displays operational health of the A2A resilience layer:
 *   - SQS DLQ message count (with Flashbar alert on > 0)
 *   - Retry distribution by error classification
 *   - Active workflow failure rates
 *
 * Persona: SRE, Staff Engineer
 * Data Source: SQS metrics (CloudWatch) + DynamoDB retry counters
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import Flashbar, { FlashbarProps } from '@cloudscape-design/components/flashbar';
import PieChart from '@cloudscape-design/components/pie-chart';

interface DLQMetrics {
  messagesVisible: number;
  messagesInFlight: number;
  oldestMessageAge: number;
}

interface RetryDistribution {
  classification: string;
  count: number;
}

interface A2AResilienceCardProps {
  dlqMetrics?: DLQMetrics;
  retryDistribution?: RetryDistribution[];
  activeWorkflows?: number;
  failedWorkflows24h?: number;
  circuitBreakerOpen?: boolean;
}

export const A2AResilienceCard: React.FC<A2AResilienceCardProps> = ({
  dlqMetrics = { messagesVisible: 0, messagesInFlight: 0, oldestMessageAge: 0 },
  retryDistribution = [],
  activeWorkflows = 0,
  failedWorkflows24h = 0,
  circuitBreakerOpen = false,
}) => {
  const alerts: FlashbarProps.MessageDefinition[] = [];

  if (dlqMetrics.messagesVisible > 0) {
    alerts.push({
      type: 'error',
      dismissible: false,
      content: `${dlqMetrics.messagesVisible} workflow(s) in Dead Letter Queue — requires manual investigation`,
      id: 'dlq-alert',
    });
  }

  if (circuitBreakerOpen) {
    alerts.push({
      type: 'warning',
      dismissible: false,
      content: 'Circuit breaker OPEN — new workflows will be rejected until recovery',
      id: 'circuit-breaker-alert',
    });
  }

  const pieData = retryDistribution.map((item) => ({
    title: item.classification,
    value: item.count,
  }));

  return (
    <Container
      header={
        <Header
          variant="h3"
          description="DLQ status, retry metrics, and circuit breaker health"
          info={
            circuitBreakerOpen
              ? <Badge color="red">CIRCUIT OPEN</Badge>
              : <Badge color="green">NOMINAL</Badge>
          }
        >
          A2A Resilience
        </Header>
      }
    >
      <SpaceBetween size="m">
        {alerts.length > 0 && <Flashbar items={alerts} />}

        <KeyValuePairs
          columns={4}
          items={[
            {
              label: 'DLQ Messages',
              value: (
                <StatusIndicator type={dlqMetrics.messagesVisible > 0 ? 'error' : 'success'}>
                  {dlqMetrics.messagesVisible}
                </StatusIndicator>
              ),
            },
            { label: 'Active Workflows', value: String(activeWorkflows) },
            {
              label: 'Failed (24h)',
              value: (
                <StatusIndicator type={failedWorkflows24h > 0 ? 'warning' : 'success'}>
                  {failedWorkflows24h}
                </StatusIndicator>
              ),
            },
            {
              label: 'Oldest DLQ Msg',
              value: dlqMetrics.oldestMessageAge > 0
                ? `${Math.round(dlqMetrics.oldestMessageAge / 3600)}h ago`
                : '-',
            },
          ]}
        />

        {retryDistribution.length > 0 && (
          <ExpandableSection headerText="Error Classification Distribution">
            <PieChart
              data={pieData}
              size="medium"
              hideFilter
              hideLegend={false}
              noMatch="No error data available"
              empty="No failures recorded"
            />
          </ExpandableSection>
        )}

        <ExpandableSection headerText="DLQ Queue Details">
          <KeyValuePairs
            columns={3}
            items={[
              { label: 'Visible', value: String(dlqMetrics.messagesVisible) },
              { label: 'In Flight', value: String(dlqMetrics.messagesInFlight) },
              { label: 'Queue', value: 'fde-*-a2a-workflow-dlq' },
            ]}
          />
        </ExpandableSection>
      </SpaceBetween>
    </Container>
  );
};
