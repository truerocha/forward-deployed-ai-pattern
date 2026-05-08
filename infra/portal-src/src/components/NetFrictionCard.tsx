import React from 'react';
import { motion } from 'motion/react';
import { Scale, TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight } from 'lucide-react';

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
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <Scale className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Net Friction</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No friction data
        </p>
      </div>
    );
  }

  const isPositive = !snapshot.is_net_negative;
  const netColor = isPositive ? 'text-emerald-400' : 'text-red-400';
  const netBg = isPositive ? 'bg-emerald-500/10' : 'bg-red-500/10';
  const netBorder = isPositive ? 'border-emerald-500/20' : 'border-red-500/20';

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-2">
          <Scale className="w-4 h-4 text-aws-orange" aria-hidden="true" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">
            Net Friction
          </h2>
        </div>
        <div className={`flex items-center gap-1 px-2 py-1 rounded ${netBg} border ${netBorder}`}>
          {isPositive ? (
            <ArrowUpRight className="w-3 h-3 text-emerald-400" aria-hidden="true" />
          ) : (
            <ArrowDownRight className="w-3 h-3 text-red-400" aria-hidden="true" />
          )}
          <span className={`text-[9px] font-bold uppercase ${netColor}`}>
            {isPositive ? 'Net Positive' : 'Net Negative'}
          </span>
        </div>
      </div>

      {/* Main metric */}
      <div className={`p-4 rounded-lg ${netBg} border ${netBorder} mb-4 text-center`}>
        <p className="text-[9px] text-secondary-dynamic uppercase mb-1">
          Gates saved this month
        </p>
        <p className={`text-3xl font-mono font-bold ${netColor}`}>
          {snapshot.downstream_saved_hours.toFixed(1)}h
        </p>
      </div>

      {/* Breakdown */}
      <div className="space-y-3 flex-1">
        {/* Upstream cost */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-amber-500" />
            <span className="text-[10px] text-secondary-dynamic">Upstream Cost</span>
          </div>
          <span className="text-xs font-mono font-bold text-dynamic">
            {snapshot.upstream_hours.toFixed(1)}h
          </span>
        </div>

        {/* Downstream savings */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-emerald-500" />
            <span className="text-[10px] text-secondary-dynamic">Downstream Saved</span>
          </div>
          <span className="text-xs font-mono font-bold text-emerald-400">
            {snapshot.downstream_saved_hours.toFixed(1)}h
          </span>
        </div>

        {/* Net friction */}
        <div className="flex items-center justify-between pt-2 border-t border-border-main">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${isPositive ? 'bg-emerald-500' : 'bg-red-500'}`} />
            <span className="text-[10px] text-dynamic font-medium">Net Friction</span>
          </div>
          <span className={`text-xs font-mono font-bold ${netColor}`}>
            {snapshot.net_friction_hours > 0 ? '+' : ''}{snapshot.net_friction_hours.toFixed(1)}h
          </span>
        </div>

        {/* ROI bar */}
        <div className="mt-3">
          <div className="flex justify-between text-[9px] mb-1">
            <span className="text-secondary-dynamic">ROI</span>
            <span className={`font-mono font-bold ${netColor}`}>{snapshot.roi_percent.toFixed(0)}%</span>
          </div>
          <div className="w-full h-2 bg-black/5 dark:bg-white/5 rounded-full overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${Math.min(Math.abs(snapshot.roi_percent), 100)}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
              className={`h-full rounded-full ${isPositive ? 'bg-emerald-500' : 'bg-red-500'}`}
            />
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main flex justify-between text-[9px] text-secondary-dynamic font-mono">
        <span>Monthly gate economics</span>
        {isPositive ? (
          <TrendingUp className="w-3 h-3 text-emerald-400" aria-hidden="true" />
        ) : (
          <TrendingDown className="w-3 h-3 text-red-400" aria-hidden="true" />
        )}
      </div>
    </div>
  );
};
