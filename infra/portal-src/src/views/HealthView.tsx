/**
 * HealthView — DORA Metrics + Component Health using Cloudscape Grid + Container.
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Box from '@cloudscape-design/components/box';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import ColumnLayout from '@cloudscape-design/components/column-layout';

interface HealthViewProps {
  factoryData: any;
  apiStatus: any;
}

export const HealthView: React.FC<HealthViewProps> = ({ factoryData, apiStatus }) => {
  const dora = factoryData?.dora;
  const metrics = factoryData?.metrics;

  return (
    <SpaceBetween size="l">
      {/* DORA Metrics */}
      <Container
        header={<Header variant="h2" description="DevOps Research and Assessment">DORA Performance</Header>}
      >
        {dora ? (
          <ColumnLayout columns={4} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Level</Box>
              <Box variant="awsui-value-large">
                <StatusIndicator type={dora.level === 'Elite' ? 'success' : dora.level === 'High' ? 'info' : 'warning'}>
                  {dora.level}
                </StatusIndicator>
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Lead Time (Avg)</Box>
              <Box variant="awsui-value-large">
                {((dora.lead_time_avg_ms || 0) / 3_600_000).toFixed(1)}h
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Success Rate</Box>
              <Box variant="awsui-value-large">{dora.success_rate_pct || 0}%</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">Throughput (24h)</Box>
              <Box variant="awsui-value-large">{dora.throughput_24h || 0}</Box>
            </div>
          </ColumnLayout>
        ) : (
          <Box textAlign="center" color="inherit" padding="l">
            <StatusIndicator type="pending">No DORA metrics available</StatusIndicator>
          </Box>
        )}
      </Container>

      {/* System Health */}
      <Container
        header={<Header variant="h2" description="Live Infrastructure Status">Component Health</Header>}
      >
        {apiStatus?.checks ? (
          <SpaceBetween size="s">
            {apiStatus.checks.map((check: any, idx: number) => (
              <div key={idx}>
                <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                  <StatusIndicator
                    type={check.status === 'healthy' ? 'success' : check.status === 'degraded' ? 'warning' : 'error'}
                  >
                    {check.name}
                  </StatusIndicator>
                  <Box variant="small" color="text-body-secondary">{check.detail}</Box>
                </SpaceBetween>
              </div>
            ))}
          </SpaceBetween>
        ) : (
          <Box textAlign="center" color="inherit" padding="l">
            <StatusIndicator type="pending">Awaiting health data</StatusIndicator>
          </Box>
        )}
      </Container>

      {/* Resource Metrics */}
      {metrics && (
        <Container
          header={<Header variant="h2">Resource Metrics</Header>}
        >
          <KeyValuePairs
            columns={3}
            items={[
              { label: 'Active Tasks', value: String(metrics.active || 0) },
              { label: 'Completed (24h)', value: String(metrics.completed_24h || 0) },
              { label: 'Failed (24h)', value: String(metrics.failed_24h || 0) },
              { label: 'Avg Duration', value: `${((metrics.avg_duration_ms || 0) / 60000).toFixed(1)} min` },
              { label: 'Agents Provisioned', value: String(metrics.total_agents_provisioned || 0) },
              { label: 'Active Agents', value: String(metrics.active_agents || 0) },
            ]}
          />
        </Container>
      )}
    </SpaceBetween>
  );
};
