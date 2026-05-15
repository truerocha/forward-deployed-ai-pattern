/**
 * MaturityRadar — 7-axis DORA capability assessment.
 *
 * Pattern: Cloudscape Container shell + custom SVG radar chart.
 * The radar chart is a custom visualization with no Cloudscape equivalent.
 * We wrap it in Container + Header for unified dashboard item appearance.
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Badge from '@cloudscape-design/components/badge';

interface MaturityScores {
  c1_ci_cd: number;
  c2_testing: number;
  c3_monitoring: number;
  c4_architecture: number;
  c5_culture: number;
  c6_process: number;
  c7_security: number;
}

interface MaturityRadarProps {
  scores?: MaturityScores | null;
  archetype?: string;
  autonomy_recommendation?: string;
}

const AXES = [
  { key: 'c1_ci_cd', label: 'CI/CD' },
  { key: 'c2_testing', label: 'Testing' },
  { key: 'c3_monitoring', label: 'Monitoring' },
  { key: 'c4_architecture', label: 'Architecture' },
  { key: 'c5_culture', label: 'Culture' },
  { key: 'c6_process', label: 'Process' },
  { key: 'c7_security', label: 'Security' },
] as const;

const polarToCartesian = (cx: number, cy: number, radius: number, angleRad: number) => ({
  x: cx + radius * Math.cos(angleRad),
  y: cy + radius * Math.sin(angleRad),
});

const RadarChart: React.FC<{ scores: MaturityScores; size?: number }> = ({ scores, size = 180 }) => {
  const cx = size / 2;
  const cy = size / 2;
  const maxRadius = size * 0.38;
  const numAxes = AXES.length;
  const angleStep = (2 * Math.PI) / numAxes;
  const startAngle = -Math.PI / 2;

  const rings = [25, 50, 75, 100];

  const dataPoints = AXES.map((axis, i) => {
    const value = (scores[axis.key as keyof MaturityScores] || 0) / 100;
    const angle = startAngle + i * angleStep;
    return polarToCartesian(cx, cy, maxRadius * value, angle);
  });
  const polygonPath = dataPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ') + ' Z';

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ display: 'block', margin: '0 auto' }} role="img" aria-label="Maturity radar chart showing 7 capability dimensions">
      {rings.map((ring) => {
        const r = maxRadius * (ring / 100);
        const ringPoints = Array.from({ length: numAxes }, (_, i) => polarToCartesian(cx, cy, r, startAngle + i * angleStep));
        const ringPath = ringPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ') + ' Z';
        return <path key={ring} d={ringPath} fill="none" stroke="var(--color-border-divider-default, #414d5c)" strokeWidth="0.5" opacity={0.5} />;
      })}
      {AXES.map((_, i) => {
        const end = polarToCartesian(cx, cy, maxRadius, startAngle + i * angleStep);
        return <line key={i} x1={cx} y1={cy} x2={end.x} y2={end.y} stroke="var(--color-border-divider-default, #414d5c)" strokeWidth="0.5" opacity={0.4} />;
      })}
      <path d={polygonPath} fill="rgba(255, 153, 0, 0.15)" stroke="#FF9900" strokeWidth="2" strokeLinejoin="round" />
      {dataPoints.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r="3" fill="#FF9900" stroke="var(--color-background-container-content, white)" strokeWidth="1" />)}
      {AXES.map((axis, i) => {
        const labelPos = polarToCartesian(cx, cy, maxRadius + 16, startAngle + i * angleStep);
        return <text key={axis.key} x={labelPos.x} y={labelPos.y} textAnchor="middle" dominantBaseline="middle" fill="var(--color-text-body-secondary, #8d99a8)" fontSize="8" fontFamily="monospace">{axis.label}</text>;
      })}
    </svg>
  );
};

export const MaturityRadar: React.FC<MaturityRadarProps> = ({ scores, archetype, autonomy_recommendation }) => {
  if (!scores) {
    return (
      <Container header={<Header variant="h3">Maturity Radar</Header>}>
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">No assessment data</StatusIndicator>
        </Box>
      </Container>
    );
  }

  const avgScore = (Object.values(scores) as number[]).reduce((sum, v) => sum + v, 0) / 7;

  return (
    <Container
      header={
        <Header variant="h3" description="7-axis DORA capability assessment" actions={archetype ? <Badge color="blue">{archetype}</Badge> : undefined}>
          Maturity Radar
        </Header>
      }
      footer={
        autonomy_recommendation
          ? <StatusIndicator type="success">{autonomy_recommendation}</StatusIndicator>
          : <Box fontSize="body-s" color="text-body-secondary">Average score: {avgScore.toFixed(0)}/100</Box>
      }
    >
      <RadarChart scores={scores} size={180} />
    </Container>
  );
};
