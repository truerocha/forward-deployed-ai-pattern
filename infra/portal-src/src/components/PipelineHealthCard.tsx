/**
 * PipelineHealthCard — ADR-034 Feature 7
 * Shows process trace funnel, timing, and anomaly detection.
 * Personas: SRE, Staff
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import SpaceBetween from '@cloudscape-design/components/space-between';

interface PipelineStep {
  module: string;
  edge: string;
  inputCount: number;
  outputCount: number;
  durationMs: number;
}

export interface PipelineHealthData {
  traceId: string;
  timestamp: string;
  healthy: boolean;
  funnelRatio: number;
  totalMs: number;
  anomalyCount: number;
  steps: PipelineStep[];
}

const SYNTHETIC_DATA: PipelineHealthData = {
  traceId: 'trace-a7f3c2',
  timestamp: '2026-05-15T14:32:00Z',
  healthy: true,
  funnelRatio: 0.18,
  totalMs: 1042,
  anomalyCount: 0,
  steps: [
    { module: 'extractor', edge: 'E1', inputCount: 312, outputCount: 127, durationMs: 450 },
    { module: 'catalog', edge: 'E2', inputCount: 127, outputCount: 89, durationMs: 120 },
    { module: 'reviewer', edge: 'E3', inputCount: 89, outputCount: 45, durationMs: 82 },
    { module: 'publish', edge: 'E4', inputCount: 45, outputCount: 23, durationMs: 240 },
    { module: 'sanitizer', edge: 'E5', inputCount: 23, outputCount: 23, durationMs: 150 },
  ],
};

interface PipelineHealthCardProps {
  data?: PipelineHealthData;
}

export const PipelineHealthCard: React.FC<PipelineHealthCardProps> = ({ data }) => {
  if (!data) {
    return (
      <Container
        header={
          <Header variant="h3" description="Process trace funnel + timing">
            Pipeline Health
          </Header>
        }
      >
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">
            No pipeline traces available — data populates after A2A workflow execution
          </StatusIndicator>
        </Box>
      </Container>
    );
  }

  const d = data;
  const maxInput = d.steps[0]?.inputCount || 1;

  return (
    <Container
      header={
        <Header
          variant="h3"
          description="Process trace funnel + timing"
          actions={
            <StatusIndicator type={d.healthy ? 'success' : 'warning'}>
              {d.healthy ? 'Healthy' : 'Anomaly'}
            </StatusIndicator>
          }
        >
          Pipeline Health
        </Header>
      }
      footer={
        <Box fontSize="body-s" color="text-body-secondary">
          Trace: {d.traceId} | {new Date(d.timestamp).toLocaleString()}
        </Box>
      }
    >
      <SpaceBetween size="m">
        <ColumnLayout columns={5} variant="text-grid">
          {d.steps.map((step) => (
            <div key={step.module}>
              <Box variant="awsui-key-label">{step.module}</Box>
              <Box fontSize="heading-m">{step.outputCount}</Box>
              <ProgressBar value={(step.outputCount / maxInput) * 100} />
            </div>
          ))}
        </ColumnLayout>

        <KeyValuePairs
          columns={3}
          items={[
            { label: 'Funnel Ratio', value: d.funnelRatio.toFixed(2) },
            { label: 'Duration', value: `${d.totalMs}ms` },
            { label: 'Anomalies', value: String(d.anomalyCount) },
          ]}
        />
      </SpaceBetween>
    </Container>
  );
};
