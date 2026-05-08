import React from 'react';
import { motion } from 'motion/react';
import { Users, Loader2, CheckCircle2, XCircle, Clock, Pause } from 'lucide-react';

interface AgentExecution {
  role: string;
  status: 'running' | 'complete' | 'error' | 'waiting' | 'paused';
  model_tier: string;
  stage: string;
  duration_seconds: number;
}

interface SquadExecutionCardProps {
  agents?: AgentExecution[] | null;
}

const STATUS_CONFIG = {
  running: { icon: Loader2, color: 'text-aws-orange', bg: 'bg-aws-orange', barBg: 'bg-aws-orange/20', animate: true },
  complete: { icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-500', barBg: 'bg-emerald-500/20', animate: false },
  error: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500', barBg: 'bg-red-500/20', animate: false },
  waiting: { icon: Clock, color: 'text-slate-400', bg: 'bg-slate-500', barBg: 'bg-slate-500/20', animate: false },
  paused: { icon: Pause, color: 'text-amber-400', bg: 'bg-amber-500', barBg: 'bg-amber-500/20', animate: false },
};

const TIER_BADGES: Record<string, string> = {
  frontier: 'bg-purple-500/20 text-purple-400',
  standard: 'bg-sky-500/20 text-sky-400',
  fast: 'bg-emerald-500/20 text-emerald-400',
  mini: 'bg-slate-500/20 text-slate-400',
};

const formatDuration = (seconds: number): string => {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`;
};

export const SquadExecutionCard: React.FC<SquadExecutionCardProps> = ({ agents }) => {
  if (!agents || agents.length === 0) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <Users className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Squad Execution</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No active agents
        </p>
      </div>
    );
  }

  const runningCount = agents.filter((a) => a.status === 'running').length;
  const completeCount = agents.filter((a) => a.status === 'complete').length;
  const maxDuration = Math.max(...agents.map((a) => a.duration_seconds), 1);

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-2">
          <Users className="w-4 h-4 text-aws-orange" aria-hidden="true" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">
            Squad Execution
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {runningCount > 0 && (
            <div className="flex items-center gap-1">
              <div className="w-2 h-2 rounded-full bg-aws-orange animate-pulse" />
              <span className="text-[9px] font-mono text-aws-orange">{runningCount} active</span>
            </div>
          )}
          <span className="text-[9px] font-mono text-secondary-dynamic">
            {completeCount}/{agents.length} done
          </span>
        </div>
      </div>

      {/* Agent list */}
      <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin space-y-3">
        {agents.map((agent, idx) => {
          const config = STATUS_CONFIG[agent.status] || STATUS_CONFIG.waiting;
          const Icon = config.icon;
          const progressPercent = agent.status === 'complete' ? 100 : (agent.duration_seconds / maxDuration) * 80;

          return (
            <div key={`${agent.role}-${idx}`} className="space-y-1.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Icon
                    className={`w-3.5 h-3.5 ${config.color} ${config.animate ? 'animate-spin' : ''}`}
                    aria-hidden="true"
                  />
                  <span className="text-[10px] font-medium text-dynamic">{agent.role}</span>
                  <span className={`text-[8px] font-mono px-1.5 py-0.5 rounded ${TIER_BADGES[agent.model_tier] || TIER_BADGES.standard}`}>
                    {agent.model_tier}
                  </span>
                </div>
                <span className="text-[9px] font-mono text-secondary-dynamic">
                  {formatDuration(agent.duration_seconds)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1.5 bg-black/5 dark:bg-white/5 rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${progressPercent}%` }}
                    transition={{ duration: 0.6, ease: 'easeOut' }}
                    className={`h-full ${config.bg} rounded-full ${agent.status === 'running' ? 'animate-pulse' : ''}`}
                  />
                </div>
                <span className="text-[8px] font-mono text-secondary-dynamic truncate max-w-[80px]">
                  {agent.stage}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main text-[9px] text-secondary-dynamic font-mono">
        {agents.length} agents in squad
      </div>
    </div>
  );
};
