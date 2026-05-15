/**
 * BrainSimCard — Brain Simulation metrics.
 * Pattern: Cloudscape Container shell + custom SVG sparkline.
 */
import React from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Badge from '@cloudscape-design/components/badge';

interface BrainSimCardProps {
  fidelity_trend?: number[] | null;
  emulation_ratio_percent?: number;
  organism_level?: string;
  memory_wall_detected?: boolean;
  transparency_score?: number;
  reasoning_divergence_avg?: number;
  execution_mode?: 'standard' | 'heartbeat';
  heartbeat_cycles?: number;
}

const Sparkline: React.FC<{ data: number[]; width?: number; height?: number }> = ({ data, width = 140, height = 36 }) => {
  if (data.length < 2) return null;
  const min = Math.min(...data); const max = Math.max(...data); const range = max - min || 1;
  const stepX = width / (data.length - 1);
  const points = data.map((v, i) => ({ x: i * stepX, y: height - ((v - min) / range) * (height - 4) - 2 }));
  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  const areaD = pathD + ` L ${points[points.length - 1].x.toFixed(1)} ${height} L 0 ${height} Z`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Fidelity trend" style={{ display: 'block', margin: '0 auto' }}>
      <defs><linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#FF9900" stopOpacity="0.3" /><stop offset="100%" stopColor="#FF9900" stopOpacity="0" /></linearGradient></defs>
      <path d={areaD} fill="url(#sparkGrad)" /><path d={pathD} fill="none" stroke="#FF9900" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={points[points.length - 1].x} cy={points[points.length - 1].y} r="2.5" fill="#FF9900" stroke="var(--color-background-container-content, white)" strokeWidth="1" />
    </svg>
  );
};

const ORGANISM_LEVELS: Record<string, { label: string; color: 'blue' | 'green' | 'grey' | 'red' }> = {
  reactive: { label: 'Reactive', color: 'grey' }, adaptive: { label: 'Adaptive', color: 'blue' },
  cognitive: { label: 'Cognitive', color: 'blue' }, autonomous: { label: 'Autonomous', color: 'green' }, sentient: { label: 'Sentient', color: 'red' },
};

export const BrainSimCard: React.FC<BrainSimCardProps> = ({ fidelity_trend, emulation_ratio_percent, organism_level, memory_wall_detected, transparency_score, execution_mode, heartbeat_cycles }) => {
  const hasData = fidelity_trend || emulation_ratio_percent !== undefined || organism_level;
  if (!hasData) {
    return (<Container header={<Header variant="h3">Brain Simulation</Header>}><Box textAlign="center" padding="l" color="inherit"><StatusIndicator type="pending">No simulation data</StatusIndicator></Box></Container>);
  }
  const levelConfig = ORGANISM_LEVELS[organism_level || ''] || ORGANISM_LEVELS.reactive;
  const latestFidelity = fidelity_trend && fidelity_trend.length > 0 ? fidelity_trend[fidelity_trend.length - 1] : null;

  return (
    <Container
      header={<Header variant="h3" description="FDE Core Brain emulation" actions={<SpaceBetween direction="horizontal" size="xs">{organism_level && <Badge color={levelConfig.color}>{levelConfig.label}</Badge>}{memory_wall_detected && <Badge color="red">Memory Wall</Badge>}</SpaceBetween>}>Brain Simulation</Header>}
      footer={<Box fontSize="body-s" color="text-body-secondary">FDE Core Brain emulation metrics</Box>}
    >
      <SpaceBetween size="m">
        <ColumnLayout columns={2} variant="text-grid">
          {emulation_ratio_percent !== undefined && (<div><Box variant="awsui-key-label">Emulation Ratio</Box><Box variant="awsui-value-large">{emulation_ratio_percent.toFixed(1)}%</Box></div>)}
          {latestFidelity !== null && (<div><Box variant="awsui-key-label">Fidelity</Box><Box variant="awsui-value-large">{latestFidelity.toFixed(2)}</Box></div>)}
          {transparency_score !== undefined && (<div><Box variant="awsui-key-label">Transparency</Box><StatusIndicator type={transparency_score >= 0.7 ? 'success' : transparency_score >= 0.4 ? 'warning' : 'error'}>{(transparency_score * 100).toFixed(0)}%</StatusIndicator></div>)}
          {execution_mode === 'heartbeat' && (<div><Box variant="awsui-key-label">Heartbeat Cycles</Box><Box variant="awsui-value-large">{heartbeat_cycles || 0}</Box></div>)}
        </ColumnLayout>
        {fidelity_trend && fidelity_trend.length > 1 && (<div><Box fontSize="body-s" color="text-body-secondary" margin={{ bottom: 'xs' }}>Fidelity Trend</Box><div style={{ padding: '12px', borderRadius: '8px', background: 'var(--color-background-layout-main, #0f1b2a)' }}><Sparkline data={fidelity_trend} width={160} height={40} /></div></div>)}
      </SpaceBetween>
    </Container>
  );
};
