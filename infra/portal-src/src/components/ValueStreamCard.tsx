/**
 * ValueStreamCard — Value Stream visualization using Cloudscape Container + ProgressBar.
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import ColumnLayout from '@cloudscape-design/components/column-layout';

interface ValueStreamStage {
  name: string;
  duration_seconds: number;
  is_active: boolean;
  is_bottleneck: boolean;
}

interface ValueStreamCardProps {
  stages?: ValueStreamStage[] | null;
  flow_efficiency_percent?: number;
}

const formatDuration = (seconds: number): string => {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
};

export const ValueStreamCard: React.FC<ValueStreamCardProps> = ({ stages, flow_efficiency_percent }) => {
  if (!stages || stages.length === 0) {
    return (
      <Container header={<Header variant="h3">Value Stream</Header>}>
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">No pipeline data</StatusIndicator>
        </Box>
      </Container>
    );
  }

  const totalDuration = stages.reduce((sum, s) => sum + s.duration_seconds, 0);

  return (
    <Container
      header={
        <Header
          variant="h3"
          description={flow_efficiency_percent !== undefined ? `${flow_efficiency_percent.toFixed(0)}% flow efficiency` : undefined}
        >
          Value Stream
        </Header>
      }
      footer={
        <Box fontSize="body-s" color="text-body-secondary">
          {stages.length} stages • Total: {formatDuration(totalDuration)}
        </Box>
      }
    >
      <SpaceBetween size="s">
        {stages.map((stage, idx) => {
          const percent = totalDuration > 0 ? (stage.duration_seconds / totalDuration) * 100 : 0;
          return (
            <div key={`${stage.name}-${idx}`}>
              <ProgressBar
                value={percent}
                label={
                  <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                    <span>{stage.name}</span>
                    {stage.is_bottleneck && <StatusIndicator type="error">Bottleneck</StatusIndicator>}
                    {stage.is_active && !stage.is_bottleneck && <StatusIndicator type="in-progress">Active</StatusIndicator>}
                  </SpaceBetween>
                }
                additionalInfo={formatDuration(stage.duration_seconds)}
                variant="standalone"
                status={stage.is_bottleneck ? 'error' : stage.is_active ? 'in-progress' : undefined}
              />
            </div>
          );
        })}
      </SpaceBetween>
    </Container>
  );
};
