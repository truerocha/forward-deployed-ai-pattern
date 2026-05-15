/**
 * DoraCard — DORA Metrics using Cloudscape Container + ColumnLayout.
 *
 * Migrated from Tailwind bento-card to Cloudscape Dashboard Item pattern.
 * Follows: https://cloudscape.design/patterns/general/service-dashboard/dashboard-items/
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Box from '@cloudscape-design/components/box';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import SegmentedControl from '@cloudscape-design/components/segmented-control';
import SpaceBetween from '@cloudscape-design/components/space-between';

interface DoraMetricSet {
  lead_time_hours: number;
  deploy_freq_per_day: number;
  change_failure_rate_pct: number;
  mttr_hours: number;
  trend: 'up' | 'down' | 'flat';
}

interface DoraMetrics {
  by_level: Record<string, DoraMetricSet>;
}

interface DoraCardProps {
  metrics?: DoraMetrics | null;
  selectedLevel?: string;
  onLevelChange?: (level: string) => void;
}

const LEVELS = ['L1_assisted', 'L2_supervised', 'L3_autonomous', 'L4_adaptive'];

const LEVEL_LABELS: Record<string, string> = {
  L1_assisted: 'L1 Assisted',
  L2_supervised: 'L2 Supervised',
  L3_autonomous: 'L3 Autonomous',
  L4_adaptive: 'L4 Adaptive',
};

function getTrendIndicator(trend: 'up' | 'down' | 'flat', positiveIsUp: boolean): 'success' | 'error' | 'stopped' {
  if (trend === 'flat') return 'stopped';
  if (positiveIsUp) return trend === 'up' ? 'success' : 'error';
  return trend === 'down' ? 'success' : 'error';
}

export const DoraCard: React.FC<DoraCardProps> = ({ metrics, selectedLevel, onLevelChange }) => {
  const detectedLevel = React.useMemo(() => {
    if (!metrics?.by_level) return LEVELS[0];
    const realLevel = Object.entries(metrics.by_level).find(
      ([_, m]) => (m as DoraMetricSet).trend !== 'flat'
    );
    return realLevel ? realLevel[0] : LEVELS[0];
  }, [metrics]);

  const [internalLevel, setInternalLevel] = React.useState<string>(detectedLevel);

  React.useEffect(() => {
    if (!selectedLevel) setInternalLevel(detectedLevel);
  }, [detectedLevel, selectedLevel]);

  const activeLevel = selectedLevel || internalLevel;
  const handleLevelChange = (level: string) => {
    if (onLevelChange) onLevelChange(level);
    else setInternalLevel(level);
  };

  if (!metrics || !metrics.by_level) {
    return (
      <Container header={<Header variant="h3">DORA Metrics</Header>}>
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">No metrics available</StatusIndicator>
        </Box>
      </Container>
    );
  }

  const currentMetrics = metrics.by_level[activeLevel];
  const availableLevels = LEVELS.filter((l) => metrics.by_level[l]);

  return (
    <Container
      header={<Header variant="h3" description="DevOps Research and Assessment">DORA Metrics</Header>}
      footer={
        <Box fontSize="body-s" color="text-body-secondary">
          Filtered by autonomy level: {LEVEL_LABELS[activeLevel] || activeLevel}
        </Box>
      }
    >
      <SpaceBetween size="m">
        {/* Level selector */}
        <SegmentedControl
          selectedId={activeLevel}
          onChange={({ detail }) => handleLevelChange(detail.selectedId)}
          options={availableLevels.map((level) => ({
            id: level,
            text: LEVEL_LABELS[level] || level,
          }))}
        />

        {/* Metrics grid */}
        {currentMetrics ? (
          <ColumnLayout columns={2} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">Lead Time</Box>
              <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                <Box variant="awsui-value-large">{currentMetrics.lead_time_hours.toFixed(1)}h</Box>
                <StatusIndicator type={getTrendIndicator(currentMetrics.trend, false)} />
              </SpaceBetween>
            </div>
            <div>
              <Box variant="awsui-key-label">Deploy Freq</Box>
              <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                <Box variant="awsui-value-large">{currentMetrics.deploy_freq_per_day.toFixed(1)}/d</Box>
                <StatusIndicator type={getTrendIndicator(currentMetrics.trend, true)} />
              </SpaceBetween>
            </div>
            <div>
              <Box variant="awsui-key-label">CFR</Box>
              <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                <Box variant="awsui-value-large">{currentMetrics.change_failure_rate_pct.toFixed(1)}%</Box>
                <StatusIndicator type={getTrendIndicator(currentMetrics.trend, false)} />
              </SpaceBetween>
            </div>
            <div>
              <Box variant="awsui-key-label">MTTR</Box>
              <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                <Box variant="awsui-value-large">{currentMetrics.mttr_hours.toFixed(1)}h</Box>
                <StatusIndicator type={getTrendIndicator(currentMetrics.trend, false)} />
              </SpaceBetween>
            </div>
          </ColumnLayout>
        ) : (
          <Box textAlign="center" color="inherit">
            <StatusIndicator type="pending">No data for this level</StatusIndicator>
          </Box>
        )}
      </SpaceBetween>
    </Container>
  );
};
