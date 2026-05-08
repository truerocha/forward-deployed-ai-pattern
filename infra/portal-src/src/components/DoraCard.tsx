import React from 'react';
import { motion } from 'motion/react';
import { BarChart3, TrendingUp, TrendingDown, Minus } from 'lucide-react';

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

const TrendIcon: React.FC<{ trend: 'up' | 'down' | 'flat'; positive?: boolean }> = ({ trend, positive = true }) => {
  if (trend === 'up') {
    return <TrendingUp className={`w-3 h-3 ${positive ? 'text-emerald-400' : 'text-red-400'}`} aria-hidden="true" />;
  }
  if (trend === 'down') {
    return <TrendingDown className={`w-3 h-3 ${positive ? 'text-red-400' : 'text-emerald-400'}`} aria-hidden="true" />;
  }
  return <Minus className="w-3 h-3 text-slate-400" aria-hidden="true" />;
};

const MetricTile: React.FC<{
  label: string;
  value: string;
  trend: 'up' | 'down' | 'flat';
  positiveIsUp?: boolean;
}> = ({ label, value, trend, positiveIsUp = true }) => (
  <div className="p-3 rounded-lg bg-black/5 dark:bg-white/5 border border-border-main">
    <div className="flex justify-between items-start mb-1">
      <p className="text-[9px] text-secondary-dynamic uppercase font-medium">{label}</p>
      <TrendIcon trend={trend} positive={positiveIsUp ? trend === 'up' : trend === 'down'} />
    </div>
    <p className="text-lg font-mono font-bold text-dynamic">{value}</p>
  </div>
);

export const DoraCard: React.FC<DoraCardProps> = ({ metrics, selectedLevel, onLevelChange }) => {
  const activeLevel = selectedLevel || LEVELS[0];

  if (!metrics || !metrics.by_level) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <BarChart3 className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">DORA Metrics</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No metrics available
        </p>
      </div>
    );
  }

  const currentMetrics = metrics.by_level[activeLevel];

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-center mb-4">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-aws-orange" aria-hidden="true" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">
            DORA 4 Metrics
          </h2>
        </div>
      </div>

      {/* Level selector */}
      <div className="flex gap-1 mb-4 p-1 rounded-lg bg-black/5 dark:bg-white/5">
        {LEVELS.filter((l) => metrics.by_level[l]).map((level) => (
          <button
            key={level}
            onClick={() => onLevelChange?.(level)}
            className={`flex-1 px-2 py-1 rounded text-[9px] font-mono font-bold uppercase transition-all ${
              activeLevel === level
                ? 'bg-aws-orange text-white'
                : 'text-secondary-dynamic hover:text-dynamic'
            }`}
          >
            {LEVEL_LABELS[level] || level}
          </button>
        ))}
      </div>

      {/* Metrics grid */}
      {currentMetrics ? (
        <motion.div
          key={activeLevel}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2 }}
          className="grid grid-cols-2 gap-3 flex-1"
        >
          <MetricTile
            label="Lead Time"
            value={`${currentMetrics.lead_time_hours.toFixed(1)}h`}
            trend={currentMetrics.trend}
            positiveIsUp={false}
          />
          <MetricTile
            label="Deploy Freq"
            value={`${currentMetrics.deploy_freq_per_day.toFixed(1)}/d`}
            trend={currentMetrics.trend}
            positiveIsUp={true}
          />
          <MetricTile
            label="CFR"
            value={`${currentMetrics.change_failure_rate_pct.toFixed(1)}%`}
            trend={currentMetrics.trend}
            positiveIsUp={false}
          />
          <MetricTile
            label="MTTR"
            value={`${currentMetrics.mttr_hours.toFixed(1)}h`}
            trend={currentMetrics.trend}
            positiveIsUp={false}
          />
        </motion.div>
      ) : (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-xs text-secondary-dynamic">No data for this level</p>
        </div>
      )}

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main text-[9px] text-secondary-dynamic font-mono">
        Filtered by autonomy level: {LEVEL_LABELS[activeLevel] || activeLevel}
      </div>
    </div>
  );
};
