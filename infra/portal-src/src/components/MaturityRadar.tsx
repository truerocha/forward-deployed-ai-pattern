import React from 'react';
import { Radar, Lightbulb } from 'lucide-react';

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

const RadarChart: React.FC<{ scores: MaturityScores; size?: number }> = ({ scores, size = 200 }) => {
  const cx = size / 2;
  const cy = size / 2;
  const maxRadius = size * 0.38;
  const numAxes = AXES.length;
  const angleStep = (2 * Math.PI) / numAxes;
  const startAngle = -Math.PI / 2;

  // Grid rings
  const rings = [25, 50, 75, 100];

  // Data polygon points
  const dataPoints = AXES.map((axis, i) => {
    const value = (scores[axis.key as keyof MaturityScores] || 0) / 100;
    const angle = startAngle + i * angleStep;
    return polarToCartesian(cx, cy, maxRadius * value, angle);
  });
  const polygonPath = dataPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ') + ' Z';

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="mx-auto">
      {/* Grid rings */}
      {rings.map((ring) => {
        const r = maxRadius * (ring / 100);
        const ringPoints = Array.from({ length: numAxes }, (_, i) => {
          const angle = startAngle + i * angleStep;
          return polarToCartesian(cx, cy, r, angle);
        });
        const ringPath = ringPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ') + ' Z';
        return (
          <path
            key={ring}
            d={ringPath}
            fill="none"
            stroke="currentColor"
            strokeWidth="0.5"
            className="text-slate-300 dark:text-slate-700"
            opacity={0.5}
          />
        );
      })}

      {/* Axis lines */}
      {AXES.map((_, i) => {
        const angle = startAngle + i * angleStep;
        const end = polarToCartesian(cx, cy, maxRadius, angle);
        return (
          <line
            key={i}
            x1={cx}
            y1={cy}
            x2={end.x}
            y2={end.y}
            stroke="currentColor"
            strokeWidth="0.5"
            className="text-slate-300 dark:text-slate-700"
            opacity={0.4}
          />
        );
      })}

      {/* Data polygon */}
      <path
        d={polygonPath}
        fill="rgba(255, 153, 0, 0.15)"
        stroke="rgb(255, 153, 0)"
        strokeWidth="2"
        strokeLinejoin="round"
      />

      {/* Data points */}
      {dataPoints.map((p, i) => (
        <circle
          key={i}
          cx={p.x}
          cy={p.y}
          r="3"
          fill="rgb(255, 153, 0)"
          stroke="white"
          strokeWidth="1"
        />
      ))}

      {/* Axis labels */}
      {AXES.map((axis, i) => {
        const angle = startAngle + i * angleStep;
        const labelPos = polarToCartesian(cx, cy, maxRadius + 16, angle);
        return (
          <text
            key={axis.key}
            x={labelPos.x}
            y={labelPos.y}
            textAnchor="middle"
            dominantBaseline="middle"
            className="fill-current text-secondary-dynamic"
            fontSize="8"
            fontFamily="monospace"
          >
            {axis.label}
          </text>
        );
      })}
    </svg>
  );
};

export const MaturityRadar: React.FC<MaturityRadarProps> = ({ scores, archetype, autonomy_recommendation }) => {
  if (!scores) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <Radar className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Maturity Radar</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No assessment data
        </p>
      </div>
    );
  }

  const avgScore = (Object.values(scores) as number[]).reduce((sum, v) => sum + v, 0) / 7;

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-start mb-2">
        <div className="flex items-center gap-2">
          <Radar className="w-4 h-4 text-aws-orange" aria-hidden="true" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">
            Maturity Radar
          </h2>
        </div>
        <div className="text-right">
          <p className="text-lg font-mono font-bold text-dynamic">{avgScore.toFixed(0)}</p>
          <p className="text-[9px] text-secondary-dynamic">/100 avg</p>
        </div>
      </div>

      {/* Archetype badge */}
      {archetype && (
        <div className="mb-2 px-2 py-1 rounded bg-aws-orange/10 border border-aws-orange/20 inline-flex self-start">
          <span className="text-[9px] font-mono font-bold text-aws-orange uppercase">{archetype}</span>
        </div>
      )}

      {/* Radar chart */}
      <div className="flex-1 flex items-center justify-center min-h-0">
        <RadarChart scores={scores} size={180} />
      </div>

      {/* Recommendation */}
      {autonomy_recommendation && (
        <div className="mt-2 p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-start gap-2">
          <Lightbulb className="w-3 h-3 text-emerald-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
          <p className="text-[10px] text-emerald-400 leading-relaxed">{autonomy_recommendation}</p>
        </div>
      )}

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main text-[9px] text-secondary-dynamic font-mono">
        7-axis DORA capability assessment
      </div>
    </div>
  );
};
