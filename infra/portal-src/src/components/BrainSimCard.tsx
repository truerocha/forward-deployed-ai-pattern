import React from 'react';
import { Brain, AlertTriangle, TrendingUp } from 'lucide-react';

interface BrainSimCardProps {
  fidelity_trend?: number[] | null;
  emulation_ratio_percent?: number;
  organism_level?: string;
  memory_wall_detected?: boolean;
}

const Sparkline: React.FC<{ data: number[]; width?: number; height?: number }> = ({
  data,
  width = 120,
  height = 32,
}) => {
  if (data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const stepX = width / (data.length - 1);

  const points = data.map((v, i) => ({
    x: i * stepX,
    y: height - ((v - min) / range) * (height - 4) - 2,
  }));

  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');

  // Gradient fill area
  const areaD = pathD + ` L ${points[points.length - 1].x.toFixed(1)} ${height} L 0 ${height} Z`;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      <defs>
        <linearGradient id="sparkGradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgb(255, 153, 0)" stopOpacity="0.3" />
          <stop offset="100%" stopColor="rgb(255, 153, 0)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaD} fill="url(#sparkGradient)" />
      <path d={pathD} fill="none" stroke="rgb(255, 153, 0)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      {/* Latest point */}
      <circle
        cx={points[points.length - 1].x}
        cy={points[points.length - 1].y}
        r="2.5"
        fill="rgb(255, 153, 0)"
        stroke="white"
        strokeWidth="1"
      />
    </svg>
  );
};

const ORGANISM_LEVELS: Record<string, { label: string; color: string }> = {
  reactive: { label: 'Reactive', color: 'text-slate-400' },
  adaptive: { label: 'Adaptive', color: 'text-sky-400' },
  cognitive: { label: 'Cognitive', color: 'text-purple-400' },
  autonomous: { label: 'Autonomous', color: 'text-emerald-400' },
  sentient: { label: 'Sentient', color: 'text-aws-orange' },
};

export const BrainSimCard: React.FC<BrainSimCardProps> = ({
  fidelity_trend,
  emulation_ratio_percent,
  organism_level,
  memory_wall_detected,
}) => {
  const hasData = fidelity_trend || emulation_ratio_percent !== undefined || organism_level;

  if (!hasData) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <Brain className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Brain Simulation</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No simulation data
        </p>
      </div>
    );
  }

  const levelConfig = ORGANISM_LEVELS[organism_level || ''] || ORGANISM_LEVELS.reactive;
  const latestFidelity = fidelity_trend && fidelity_trend.length > 0 ? fidelity_trend[fidelity_trend.length - 1] : null;

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-aws-orange" aria-hidden="true" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">
            Brain Simulation
          </h2>
        </div>
        {memory_wall_detected && (
          <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-red-500/10 border border-red-500/20">
            <AlertTriangle className="w-3 h-3 text-red-400" aria-hidden="true" />
            <span className="text-[8px] font-bold text-red-400 uppercase">Memory Wall</span>
          </div>
        )}
      </div>

      {/* Organism level */}
      {organism_level && (
        <div className="mb-4 pb-4 border-b border-border-main">
          <p className="text-[9px] text-secondary-dynamic uppercase mb-1">Organism Level</p>
          <p className={`text-lg font-mono font-bold ${levelConfig.color}`}>{levelConfig.label}</p>
        </div>
      )}

      {/* Metrics row */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        {emulation_ratio_percent !== undefined && (
          <div>
            <p className="text-[9px] text-secondary-dynamic uppercase mb-1">Emulation Ratio</p>
            <p className="text-xl font-mono font-bold text-dynamic">{emulation_ratio_percent.toFixed(1)}%</p>
          </div>
        )}
        {latestFidelity !== null && (
          <div>
            <p className="text-[9px] text-secondary-dynamic uppercase mb-1">Fidelity</p>
            <div className="flex items-baseline gap-1">
              <p className="text-xl font-mono font-bold text-dynamic">{latestFidelity.toFixed(2)}</p>
              <TrendingUp className="w-3 h-3 text-emerald-400" aria-hidden="true" />
            </div>
          </div>
        )}
      </div>

      {/* Sparkline */}
      {fidelity_trend && fidelity_trend.length > 1 && (
        <div className="flex-1 flex flex-col">
          <p className="text-[9px] text-secondary-dynamic uppercase mb-2">Fidelity Trend</p>
          <div className="flex-1 flex items-center justify-center bg-black/5 dark:bg-white/5 rounded-lg p-3">
            <Sparkline data={fidelity_trend} width={160} height={40} />
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main text-[9px] text-secondary-dynamic font-mono">
        FDE Core Brain emulation metrics
      </div>
    </div>
  );
};
