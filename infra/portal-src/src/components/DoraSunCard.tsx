/**
 * DoraSunCard — DORA health pulse indicator.
 * Pattern: Cloudscape Container + constrained SVG gauge.
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Badge from '@cloudscape-design/components/badge';

interface ForecastData {
  health_pulse?: number;
  current_level?: string;
  projected_level_7d?: string;
  projected_level_30d?: string;
  weakest_metric?: string;
  weakest_reason?: string;
  risk_adjusted_cfr?: number;
  metrics?: {
    lead_time?: { trend_direction: string; current_value: number };
    deploy_frequency?: { trend_direction: string; current_value: number };
    change_fail_rate?: { trend_direction: string; current_value: number };
    mttr?: { trend_direction: string; current_value: number };
  };
}

interface DoraSunCardProps {
  forecast?: ForecastData | null;
}

function getLevelBadgeColor(level: string): 'green' | 'blue' | 'red' | 'grey' {
  switch (level) {
    case 'Elite': return 'green';
    case 'High': return 'blue';
    case 'Low': return 'red';
    default: return 'grey';
  }
}

function getTrendStatus(direction: string): 'success' | 'error' | 'stopped' {
  if (direction === 'improving') return 'success';
  if (direction === 'degrading') return 'error';
  return 'stopped';
}

const PulseGauge: React.FC<{ pulse: number }> = ({ pulse }) => {
  const arcDegrees = (pulse / 100) * 270;
  const color = pulse >= 80 ? '#10b981' : pulse >= 50 ? '#f59e0b' : '#ef4444';

  return (
    <div style={{ position: 'relative', width: '80px', height: '80px', margin: '0 auto' }}>
      <svg width="80" height="80" viewBox="0 0 100 100" style={{ transform: 'rotate(-135deg)' }} role="img" aria-label={`Health pulse: ${pulse}/100`}>
        <circle cx="50" cy="50" r="42" fill="none" stroke="var(--color-border-divider-default, #414d5c)" strokeWidth="8" strokeDasharray="198" strokeDashoffset="0" strokeLinecap="round" />
        <circle cx="50" cy="50" r="42" fill="none" stroke={color} strokeWidth="8" strokeDasharray="198" strokeDashoffset={198 - (198 * (arcDegrees / 270))} strokeLinecap="round" />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Box variant="awsui-value-large">{pulse}</Box>
      </div>
    </div>
  );
};

export const DoraSunCard: React.FC<DoraSunCardProps> = ({ forecast }) => {
  const pulse = forecast?.health_pulse ?? 50;
  const level = forecast?.current_level || 'Medium';
  const projected = forecast?.projected_level_7d || level;
  const weakest = forecast?.weakest_metric || '';
  const weakestReason = forecast?.weakest_reason || '';
  const metrics = forecast?.metrics;

  if (!forecast) {
    return (
      <Container header={<Header variant="h3">DORA Sun</Header>}>
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">Awaiting forecast data (requires 3+ weekly snapshots)</StatusIndicator>
        </Box>
      </Container>
    );
  }

  return (
    <Container
      header={
        <Header variant="h3" actions={<Badge color={getLevelBadgeColor(level)}>{level}</Badge>}>
          DORA Sun
        </Header>
      }
      footer={
        <Box fontSize="body-s" color="text-body-secondary">
          7d forecast: {level !== projected ? `${level} → ${projected}` : `${level} (stable)`}
        </Box>
      }
    >
      <SpaceBetween size="m">
        {/* Pulse gauge */}
        <PulseGauge pulse={pulse} />

        {/* Metric trends */}
        {metrics && (
          <ColumnLayout columns={4} variant="text-grid">
            {[
              { key: 'lead_time', label: 'Lead Time' },
              { key: 'deploy_frequency', label: 'Deploy Freq' },
              { key: 'change_fail_rate', label: 'CFR' },
              { key: 'mttr', label: 'MTTR' },
            ].map(({ key, label }) => {
              const metric = metrics[key as keyof typeof metrics];
              return (
                <div key={key} style={{ textAlign: 'center' }}>
                  <Box fontSize="body-s" color="text-body-secondary">{label}</Box>
                  {metric ? (
                    <StatusIndicator type={getTrendStatus(metric.trend_direction)}>
                      {metric.current_value?.toFixed(1) || '—'}
                    </StatusIndicator>
                  ) : (
                    <StatusIndicator type="stopped">—</StatusIndicator>
                  )}
                </div>
              );
            })}
          </ColumnLayout>
        )}

        {/* Weakest metric alert */}
        {weakest && (
          <StatusIndicator type="error">
            Weakest: {weakest.replace(/_/g, ' ')}{weakestReason ? ` — ${weakestReason}` : ''}
          </StatusIndicator>
        )}
      </SpaceBetween>
    </Container>
  );
};
