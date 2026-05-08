import React from 'react';
import { Shield, TrendingUp } from 'lucide-react';

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
    <div className="flex flex-col items-center">
      <div className="relative">
        <svg width={size} height={size} className="-rotate-90">
          {/* Background circle */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth={strokeWidth}
            className="text-slate-200 dark:text-slate-800"
          />
          {/* Progress circle */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            className="transition-all duration-700 ease-out"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-sm font-mono font-bold text-dynamic">{value.toFixed(0)}%</span>
        </div>
      </div>
      <p className="text-[9px] text-secondary-dynamic uppercase mt-1.5 text-center font-medium">{label}</p>
    </div>
  );
};

export const TrustCard: React.FC<TrustCardProps> = ({ snapshot }) => {
  if (!snapshot) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <Shield className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Trust Score</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No trust data
        </p>
      </div>
    );
  }

  const trustColor =
    snapshot.trust_score_composite >= 80
      ? 'rgb(52, 211, 153)'
      : snapshot.trust_score_composite >= 60
        ? 'rgb(251, 191, 36)'
        : 'rgb(248, 113, 113)';

  const trustTextColor =
    snapshot.trust_score_composite >= 80
      ? 'text-emerald-400'
      : snapshot.trust_score_composite >= 60
        ? 'text-amber-400'
        : 'text-red-400';

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-2">
          <Shield className="w-4 h-4 text-aws-orange" aria-hidden="true" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">
            Trust Score
          </h2>
        </div>
        <div className="flex items-center gap-1">
          <TrendingUp className={`w-3 h-3 ${trustTextColor}`} aria-hidden="true" />
          <span className={`text-xs font-mono font-bold ${trustTextColor}`}>
            {snapshot.trust_score_composite.toFixed(0)}
          </span>
        </div>
      </div>

      {/* Composite trust score - large */}
      <div className="flex justify-center mb-6">
        <CircularProgress
          value={snapshot.trust_score_composite}
          label="Composite Trust"
          color={trustColor}
          size={96}
        />
      </div>

      {/* Individual metrics */}
      <div className="flex justify-around flex-1">
        <CircularProgress
          value={snapshot.pr_acceptance_rate}
          label="PR Accept"
          color="rgb(52, 211, 153)"
          size={64}
        />
        <CircularProgress
          value={100 - snapshot.gate_override_rate}
          label="Gate Compliance"
          color="rgb(96, 165, 250)"
          size={64}
        />
      </div>

      {/* Override rate callout */}
      <div className="mt-4 p-2 rounded-lg bg-black/5 dark:bg-white/5 border border-border-main">
        <div className="flex justify-between items-center">
          <span className="text-[9px] text-secondary-dynamic uppercase">Override Rate</span>
          <span className={`text-[10px] font-mono font-bold ${snapshot.gate_override_rate > 20 ? 'text-red-400' : 'text-secondary-dynamic'}`}>
            {snapshot.gate_override_rate.toFixed(1)}%
          </span>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main text-[9px] text-secondary-dynamic font-mono">
        Human-AI trust calibration
      </div>
    </div>
  );
};
