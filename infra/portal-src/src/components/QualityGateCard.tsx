/**
 * QualityGateCard — ADR-034 Feature 4+5
 * Shows DoD v3.0 compliance (7 dimensions) + compound review lens activity.
 * Personas: SWE, Staff
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import SpaceBetween from '@cloudscape-design/components/space-between';

interface DimensionStatus {
  name: string;
  passCount: number;
  totalCount: number;
}

export interface QualityGateData {
  period: string;
  totalTasks: number;
  passRate: number;
  dimensions: DimensionStatus[];
  topLens: string;
  topFailDimension: string;
}

const SYNTHETIC_DATA: QualityGateData = {
  period: 'Last 7 days',
  totalTasks: 14,
  passRate: 79,
  dimensions: [
    { name: 'Correctness', passCount: 13, totalCount: 14 },
    { name: 'Architecture', passCount: 12, totalCount: 14 },
    { name: 'Contracts', passCount: 14, totalCount: 14 },
    { name: 'Scope Match', passCount: 11, totalCount: 14 },
    { name: 'Knowledge', passCount: 8, totalCount: 10 },
    { name: 'Pipeline Test', passCount: 9, totalCount: 14 },
    { name: 'Not-Done Signals', passCount: 12, totalCount: 14 },
  ],
  topLens: 'Pipeline Edge',
  topFailDimension: 'Pipeline Test',
};

interface QualityGateCardProps {
  data?: QualityGateData;
}

export const QualityGateCard: React.FC<QualityGateCardProps> = ({ data }) => {
  const d = data || SYNTHETIC_DATA;
  const passColor = d.passRate >= 80 ? 'green' : d.passRate >= 60 ? 'blue' : 'red';

  return (
    <Container
      header={
        <Header
          variant="h3"
          description="DoD v3.0 + Compound Review"
          actions={<Badge color={passColor}>{d.passRate}% PASS</Badge>}
        >
          Quality Gate
        </Header>
      }
      footer={
        <Box fontSize="body-s" color="text-body-secondary">
          {d.totalTasks} tasks evaluated | {d.period}
        </Box>
      }
    >
      <SpaceBetween size="m">
        <ColumnLayout columns={3} variant="text-grid">
          <div>
            <Box variant="awsui-key-label">Pass Rate</Box>
            <Box variant="awsui-value-large">{d.passRate}%</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Top Failing</Box>
            <Box fontSize="heading-m">{d.topFailDimension}</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Active Lens</Box>
            <Box fontSize="heading-m">{d.topLens}</Box>
          </div>
        </ColumnLayout>

        <SpaceBetween size="xs">
          {d.dimensions.map((dim) => (
            <StatusIndicator
              key={dim.name}
              type={dim.passCount === dim.totalCount ? 'success' : dim.passCount / dim.totalCount >= 0.7 ? 'warning' : 'error'}
            >
              {dim.name}: {dim.passCount}/{dim.totalCount}
            </StatusIndicator>
          ))}
        </SpaceBetween>
      </SpaceBetween>
    </Container>
  );
};
