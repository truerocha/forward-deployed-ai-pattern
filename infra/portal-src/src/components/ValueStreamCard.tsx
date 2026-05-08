import React from 'react';
import { motion } from 'motion/react';
import { GitCommitHorizontal, AlertTriangle, Gauge } from 'lucide-react';

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
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <GitCommitHorizontal className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Value Stream</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No pipeline data
        </p>
      </div>
    );
  }

  const totalDuration = stages.reduce((sum, s) => sum + s.duration_seconds, 0);
  const efficiencyColor =
    (flow_efficiency_percent ?? 0) >= 70
      ? 'text-emerald-400'
      : (flow_efficiency_percent ?? 0) >= 40
        ? 'text-amber-400'
        : 'text-red-400';

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-2">
          <GitCommitHorizontal className="w-4 h-4 text-aws-orange" aria-hidden="true" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">
            Value Stream
          </h2>
        </div>
        {flow_efficiency_percent !== undefined && (
          <div className="flex items-center gap-1">
            <Gauge className={`w-3 h-3 ${efficiencyColor}`} aria-hidden="true" />
            <span className={`text-xs font-mono font-bold ${efficiencyColor}`}>
              {flow_efficiency_percent.toFixed(0)}%
            </span>
            <span className="text-[9px] text-secondary-dynamic">efficiency</span>
          </div>
        )}
      </div>

      {/* Horizontal timeline */}
      <div className="flex-1 flex flex-col justify-center">
        {/* Stage bars */}
        <div className="flex gap-0.5 w-full h-8 rounded-lg overflow-hidden mb-3">
          {stages.map((stage, idx) => {
            const widthPercent = totalDuration > 0 ? (stage.duration_seconds / totalDuration) * 100 : 100 / stages.length;
            const bgColor = stage.is_bottleneck
              ? 'bg-red-500'
              : stage.is_active
                ? 'bg-aws-orange'
                : 'bg-emerald-500/60';

            return (
              <motion.div
                key={`${stage.name}-${idx}`}
                initial={{ width: 0 }}
                animate={{ width: `${widthPercent}%` }}
                transition={{ duration: 0.5, delay: idx * 0.1 }}
                className={`h-full ${bgColor} relative group cursor-default min-w-[4px]`}
                title={`${stage.name}: ${formatDuration(stage.duration_seconds)}`}
              >
                {stage.is_active && (
                  <div className="absolute inset-0 bg-white/20 animate-pulse" />
                )}
              </motion.div>
            );
          })}
        </div>

        {/* Stage labels */}
        <div className="space-y-2 overflow-y-auto max-h-[200px] pr-2 scrollbar-thin">
          {stages.map((stage, idx) => (
            <div
              key={`label-${stage.name}-${idx}`}
              className={`flex items-center justify-between px-2 py-1.5 rounded ${
                stage.is_bottleneck
                  ? 'bg-red-500/10 border border-red-500/20'
                  : stage.is_active
                    ? 'bg-aws-orange/10 border border-aws-orange/20'
                    : 'bg-black/5 dark:bg-white/5'
              }`}
            >
              <div className="flex items-center gap-2">
                {stage.is_bottleneck && (
                  <AlertTriangle className="w-3 h-3 text-red-400 flex-shrink-0" aria-hidden="true" />
                )}
                {stage.is_active && !stage.is_bottleneck && (
                  <div className="w-2 h-2 rounded-full bg-aws-orange animate-pulse flex-shrink-0" />
                )}
                <span className={`text-[10px] font-medium ${stage.is_bottleneck ? 'text-red-400' : 'text-dynamic'}`}>
                  {stage.name}
                </span>
              </div>
              <span className={`text-[10px] font-mono font-bold ${stage.is_bottleneck ? 'text-red-400' : 'text-secondary-dynamic'}`}>
                {formatDuration(stage.duration_seconds)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main flex justify-between text-[9px] text-secondary-dynamic font-mono">
        <span>{stages.length} stages</span>
        <span>Total: {formatDuration(totalDuration)}</span>
      </div>
    </div>
  );
};
