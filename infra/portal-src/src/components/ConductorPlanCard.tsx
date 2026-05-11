import React from 'react';
import { motion } from 'motion/react';
import { Network, RefreshCw, Eye, EyeOff, Zap } from 'lucide-react';

interface WorkflowStep {
  step_index: number;
  subtask: string;
  agent_role: string;
  model_tier: string;
  access_list: (number | string)[];
  status?: 'pending' | 'running' | 'complete' | 'failed';
}

interface ConductorPlanCardProps {
  topology?: string | null;
  steps?: WorkflowStep[] | null;
  rationale?: string | null;
  recursive_depth?: number;
  confidence_threshold?: number;
  estimated_tokens?: number;
}

const TOPOLOGY_CONFIG: Record<string, { label: string; color: string; icon: string }> = {
  sequential: { label: 'Sequential', color: 'text-sky-400', icon: '\u2192' },
  parallel: { label: 'Parallel', color: 'text-emerald-400', icon: '\u21C9' },
  tree: { label: 'Tree', color: 'text-purple-400', icon: '\u2442' },
  debate: { label: 'Debate', color: 'text-amber-400', icon: '\u21CC' },
  recursive: { label: 'Recursive', color: 'text-red-400', icon: '\u21BB' },
};

const TIER_COLORS: Record<string, string> = {
  fast: 'bg-emerald-500/20 text-emerald-400',
  reasoning: 'bg-sky-500/20 text-sky-400',
  deep: 'bg-purple-500/20 text-purple-400',
};

const STATUS_DOTS: Record<string, string> = {
  pending: 'bg-slate-500',
  running: 'bg-aws-orange animate-pulse',
  complete: 'bg-emerald-500',
  failed: 'bg-red-500',
};

const formatAccessList = (accessList: (number | string)[]): string => {
  if (!accessList || accessList.length === 0) return 'independent';
  if (accessList.includes('all')) return 'full access';
  return `steps [${accessList.join(', ')}]`;
};

export const ConductorPlanCard: React.FC<ConductorPlanCardProps> = ({
  topology,
  steps,
  rationale,
  recursive_depth = 0,
  confidence_threshold = 0.7,
  estimated_tokens = 0,
}) => {
  if (!steps || steps.length === 0) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <Network className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Conductor Plan</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No active plan
        </p>
      </div>
    );
  }

  const topoConfig = TOPOLOGY_CONFIG[topology || 'sequential'] || TOPOLOGY_CONFIG.sequential;
  const completedSteps = steps.filter((s) => s.status === 'complete').length;

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-2">
          <Network className="w-4 h-4 text-aws-orange" aria-hidden="true" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">
            Conductor Plan
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[9px] font-mono ${topoConfig.color}`}>
            {topoConfig.icon} {topoConfig.label}
          </span>
          {recursive_depth > 0 && (
            <div className="flex items-center gap-1">
              <RefreshCw className="w-3 h-3 text-amber-400" aria-hidden="true" />
              <span className="text-[8px] font-mono text-amber-400">
                depth {recursive_depth}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Topology visualization */}
      <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin space-y-2">
        {steps.map((step, idx) => {
          const statusDot = STATUS_DOTS[step.status || 'pending'];
          const tierColor = TIER_COLORS[step.model_tier] || TIER_COLORS.reasoning;
          const hasAccess = step.access_list && step.access_list.length > 0;

          return (
            <motion.div
              key={step.step_index}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: idx * 0.1 }}
              className="relative"
            >
              {/* Connection line */}
              {idx > 0 && (
                <div className="absolute -top-1 left-[7px] w-px h-2 bg-slate-600" />
              )}

              <div className="flex items-start gap-2 p-2 rounded-lg bg-black/5 dark:bg-white/5">
                {/* Status dot */}
                <div className={`w-3.5 h-3.5 rounded-full ${statusDot} mt-0.5 flex-shrink-0`} />

                {/* Step content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-medium text-dynamic truncate">
                      {step.agent_role}
                    </span>
                    <span className={`text-[8px] font-mono px-1.5 py-0.5 rounded ${tierColor}`}>
                      {step.model_tier}
                    </span>
                  </div>

                  {/* Subtask instruction */}
                  <p className="text-[9px] text-secondary-dynamic line-clamp-2 mb-1">
                    {step.subtask}
                  </p>

                  {/* Access list indicator */}
                  <div className="flex items-center gap-1">
                    {hasAccess ? (
                      <Eye className="w-2.5 h-2.5 text-sky-400" aria-hidden="true" />
                    ) : (
                      <EyeOff className="w-2.5 h-2.5 text-slate-500" aria-hidden="true" />
                    )}
                    <span className="text-[8px] font-mono text-secondary-dynamic">
                      {formatAccessList(step.access_list)}
                    </span>
                  </div>
                </div>

                {/* Step number */}
                <span className="text-[8px] font-mono text-secondary-dynamic flex-shrink-0">
                  #{step.step_index}
                </span>
              </div>
            </motion.div>
          );
        })}
      </div>

      {/* Rationale */}
      {rationale && (
        <div className="mt-3 pt-2 border-t border-border-main">
          <p className="text-[9px] text-secondary-dynamic italic line-clamp-2">
            {rationale}
          </p>
        </div>
      )}

      {/* Footer metrics */}
      <div className="mt-2 pt-2 border-t border-border-main flex justify-between text-[8px] text-secondary-dynamic font-mono">
        <span>{completedSteps}/{steps.length} steps</span>
        <span className="flex items-center gap-1">
          <Zap className="w-2.5 h-2.5" aria-hidden="true" />
          ~{estimated_tokens.toLocaleString()} tokens
        </span>
        <span>threshold: {(confidence_threshold * 100).toFixed(0)}%</span>
      </div>
    </div>
  );
};
