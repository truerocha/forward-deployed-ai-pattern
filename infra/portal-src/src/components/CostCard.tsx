import React from 'react';
import { motion } from 'motion/react';
import { DollarSign, AlertTriangle, TrendingUp } from 'lucide-react';

interface CostByAgent {
  agent: string;
  cost_usd: number;
  invocations: number;
}

interface CostByTier {
  tier: string;
  cost_usd: number;
  percentage: number;
}

interface CostSummary {
  total_cost_usd: number;
  cost_by_agent: CostByAgent[];
  cost_by_tier: CostByTier[];
  threshold_exceeded: boolean;
  threshold_usd?: number;
  period?: string;
}

interface CostCardProps {
  summary?: CostSummary | null;
}

const TIER_COLORS: Record<string, string> = {
  frontier: 'bg-purple-500',
  standard: 'bg-aws-orange',
  fast: 'bg-emerald-500',
  mini: 'bg-sky-500',
};

const CostBar: React.FC<{ agent: string; cost_usd: number; maxCost: number }> = ({ agent, cost_usd, maxCost }) => {
  const percent = maxCost > 0 ? (cost_usd / maxCost) * 100 : 0;

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px]">
        <span className="text-secondary-dynamic font-medium truncate">{agent}</span>
        <span className="text-aws-orange/80 font-mono font-bold">${cost_usd.toFixed(4)}</span>
      </div>
      <div className="w-full h-1.5 bg-black/5 dark:bg-white/5 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${percent}%` }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
          className="h-full bg-aws-orange rounded-full"
        />
      </div>
    </div>
  );
};

export const CostCard: React.FC<CostCardProps> = ({ summary }) => {
  if (!summary) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <DollarSign className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Cost Breakdown</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No cost data available
        </p>
      </div>
    );
  }

  const maxAgentCost = Math.max(...summary.cost_by_agent.map((a) => a.cost_usd), 0.001);

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div>
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest mb-1">
            Cost Breakdown
          </h2>
          {summary.period && (
            <p className="text-[10px] text-slate-500 font-mono">{summary.period}</p>
          )}
        </div>
        {summary.threshold_exceeded && (
          <div className="flex items-center gap-1 px-2 py-1 rounded bg-red-500/10 border border-red-500/20">
            <AlertTriangle className="w-3 h-3 text-red-400" aria-hidden="true" />
            <span className="text-[9px] font-bold text-red-400 uppercase">Over Budget</span>
          </div>
        )}
      </div>

      {/* Total cost */}
      <div className="flex items-baseline gap-2 mb-4 pb-4 border-b border-border-main">
        <DollarSign className="w-5 h-5 text-aws-orange" aria-hidden="true" />
        <span className="text-3xl font-mono font-bold text-dynamic">
          {summary.total_cost_usd.toFixed(4)}
        </span>
        <span className="text-[10px] text-secondary-dynamic uppercase">USD</span>
        {summary.threshold_usd && (
          <span className="text-[10px] text-secondary-dynamic font-mono ml-auto">
            / ${summary.threshold_usd.toFixed(2)} limit
          </span>
        )}
      </div>

      {/* Tier breakdown - stacked bar */}
      <div className="mb-4">
        <p className="text-[10px] text-secondary-dynamic uppercase mb-2 font-medium">By Model Tier</p>
        <div className="w-full h-3 rounded-full overflow-hidden flex">
          {summary.cost_by_tier.map((tier) => (
            <motion.div
              key={tier.tier}
              initial={{ width: 0 }}
              animate={{ width: `${tier.percentage}%` }}
              transition={{ duration: 0.6, ease: 'easeOut' }}
              className={`h-full ${TIER_COLORS[tier.tier] || 'bg-slate-500'}`}
              title={`${tier.tier}: $${tier.cost_usd.toFixed(4)} (${tier.percentage.toFixed(0)}%)`}
            />
          ))}
        </div>
        <div className="flex flex-wrap gap-3 mt-2">
          {summary.cost_by_tier.map((tier) => (
            <div key={tier.tier} className="flex items-center gap-1">
              <div className={`w-2 h-2 rounded-full ${TIER_COLORS[tier.tier] || 'bg-slate-500'}`} />
              <span className="text-[9px] text-secondary-dynamic font-mono">
                {tier.tier} ({tier.percentage.toFixed(0)}%)
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Per-agent breakdown */}
      <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin space-y-3">
        <p className="text-[10px] text-secondary-dynamic uppercase font-medium">By Agent</p>
        {summary.cost_by_agent.map((agent) => (
          <CostBar key={agent.agent} agent={agent.agent} cost_usd={agent.cost_usd} maxCost={maxAgentCost} />
        ))}
      </div>

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main flex justify-between text-[9px] text-secondary-dynamic font-mono">
        <span>{summary.cost_by_agent.reduce((sum, a) => sum + a.invocations, 0)} total invocations</span>
        <TrendingUp className="w-3 h-3" aria-hidden="true" />
      </div>
    </div>
  );
};
