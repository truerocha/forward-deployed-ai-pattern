/**
 * TrustCard — Trust Score using Cloudscape Container + ColumnLayout.
 * Keeps the SVG CircularProgress visualization (no Cloudscape equivalent).
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';

interface TrustSnapshot {
  pr_acceptance_rate: number;
  gate_override_rate: number;
  trust_score_composite: number;
}

interface TrustCardProps {
  snapshot?: TrustSnapshot | null;
}

const CircularProgress: React.FC<{
  value: number;
  label: string;
  color: string;
  size?: number;
}> = ({ value, label, color, size = 72 }) => {
  const strokeWidth = 5;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (value / 100) * circumference;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <div style={{ position: 'relative' }}>
        <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
          <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--color-border-divider-default, #414d5c)" strokeWidth={strokeWidth} />
          <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={color} strokeWidth={strokeWidth} strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round" style={{ transition: 'stroke-dashoffset 0.7s ease-out' }} />
        </svg>
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Box variant="code" fontSize="body-s" fontWeight="bold">{value.toFixed(0)}%</Box>
        </div>
      </div>
      <Box fontSize="body-s" color="text-body-secondary" margin={{ top: 'xxs' }}>{label}</Box>
    </div>
  );
};

export const TrustCard: React.FC<TrustCardProps> = ({ snapshot }) => {
  if (!snapshot) {
    return (
      <Container header={<Header variant="h3">Trust Score</Header>}>
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">No trust data</StatusIndicator>
        </Box>
      </Container>
    );
  }

  const trustColor = snapshot.trust_score_composite >= 80 ? 'rgb(52, 211, 153)' : snapshot.trust_score_composite >= 60 ? 'rgb(251, 191, 36)' : 'rgb(248, 113, 113)';
  const trustStatus: 'success' | 'warning' | 'error' = snapshot.trust_score_composite >= 80 ? 'success' : snapshot.trust_score_composite >= 60 ? 'warning' : 'error';

  return (
    <Container
      header={
        <Header variant="h3" description="Human-AI trust calibration">
          Trust Score
        </Header>
      }
      footer={
        <Box fontSize="body-s" color="text-body-secondary">
          Override rate: {snapshot.gate_override_rate.toFixed(1)}%
          {snapshot.gate_override_rate > 20 && ' ⚠️'}
        </Box>
      }
    >
      <SpaceBetween size="m">
        {/* Composite score */}
        <Box textAlign="center">
          <CircularProgress value={snapshot.trust_score_composite} label="Composite Trust" color={trustColor} size={96} />
        </Box>

        {/* Individual metrics */}
        <ColumnLayout columns={2} variant="text-grid">
          <div style={{ textAlign: 'center' }}>
            <CircularProgress value={snapshot.pr_acceptance_rate} label="PR Accept" color="rgb(52, 211, 153)" size={64} />
          </div>
          <div style={{ textAlign: 'center' }}>
            <CircularProgress value={100 - snapshot.gate_override_rate} label="Gate Compliance" color="rgb(96, 165, 250)" size={64} />
          </div>
        </ColumnLayout>
      </SpaceBetween>
    </Container>
  );
};
