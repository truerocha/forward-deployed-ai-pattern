/**
 * NetFrictionCard — Gate economics using Cloudscape Container + KeyValuePairs.
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import Badge from '@cloudscape-design/components/badge';

interface NetFrictionSnapshot {
  upstream_hours: number;
  downstream_saved_hours: number;
  net_friction_hours: number;
  roi_percent: number;
  is_net_negative: boolean;
}

interface NetFrictionCardProps {
  snapshot?: NetFrictionSnapshot | null;
}

export const NetFrictionCard: React.FC<NetFrictionCardProps> = ({ snapshot }) => {
  if (!snapshot) {
    return (
      <Container header={<Header variant="h3">Net Friction</Header>}>
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">No friction data</StatusIndicator>
        </Box>
      </Container>
    );
  }

  const isPositive = !snapshot.is_net_negative;

  return (
    <Container
      header={<Header variant="h3" description="Monthly gate economics" actions={<Badge color={isPositive ? 'green' : 'red'}>{isPositive ? 'Net Positive' : 'Net Negative'}</Badge>}>Net Friction</Header>}
      footer={<Box fontSize="body-s" color="text-body-secondary">ROI: {snapshot.roi_percent.toFixed(0)}%</Box>}
    >
      <SpaceBetween size="m">
        <Box textAlign="center">
          <Box variant="awsui-key-label">Gates saved this month</Box>
          <Box variant="awsui-value-large">
            <StatusIndicator type={isPositive ? 'success' : 'error'}>{snapshot.downstream_saved_hours.toFixed(1)}h</StatusIndicator>
          </Box>
        </Box>
        <KeyValuePairs columns={2} items={[
          { label: 'Upstream Cost', value: `${snapshot.upstream_hours.toFixed(1)}h` },
          { label: 'Downstream Saved', value: `${snapshot.downstream_saved_hours.toFixed(1)}h` },
          { label: 'Net Friction', value: `${snapshot.net_friction_hours > 0 ? '+' : ''}${snapshot.net_friction_hours.toFixed(1)}h` },
          { label: 'ROI', value: `${snapshot.roi_percent.toFixed(0)}%` },
        ]} />
        <ProgressBar value={Math.min(Math.abs(snapshot.roi_percent), 100)} label="Return on Investment" variant="standalone" status={isPositive ? undefined : 'error'} />
      </SpaceBetween>
    </Container>
  );
};
