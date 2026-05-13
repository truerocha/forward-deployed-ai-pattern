import React from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Bot, CheckCircle2, CircleDashed, Hammer, Search, Cpu, Shield, Eye, FileText, Zap } from 'lucide-react';
import { Agent, AgentStatus } from '../types';
import { useTranslation } from 'react-i18next';

interface AgentCardProps {
  agent: Agent;
}

const StatusIcon = ({ status }: { status: AgentStatus }) => {
  switch (status) {
    case 'intake': return <div className="w-2 h-2 rounded-full bg-blue-500/50 animate-pulse" />;
    case 'provisioning': return <CircleDashed className="w-4 h-4 text-aws-orange animate-spin" />;
    case 'setup': return <div className="w-2 h-2 rounded-full bg-aws-orange animate-ping" />;
    case 'thinking': return <CircleDashed className="w-4 h-4 text-blue-400 animate-spin" />;
    case 'working': return <Hammer className="w-4 h-4 text-aws-orange animate-pulse" />;
    case 'complete': return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
    case 'error': return <div className="w-2 h-2 rounded-full bg-red-500 animate-ping" />;
    default: return <div className="w-2 h-2 rounded-full bg-zinc-600" />;
  }
};

const RoleIcon = ({ role }: { role: Agent['role'] }) => {
  switch (role) {
    case 'planner': return <Search className="w-4 h-4" />;
    case 'tech-lead': return <Search className="w-4 h-4" />;
    case 'coder': return <Cpu className="w-4 h-4" />;
    case 'architect': return <Zap className="w-4 h-4" />;
    case 'adversarial': return <Shield className="w-4 h-4" />;
    case 'fidelity': return <Eye className="w-4 h-4" />;
    case 'reviewer': return <CheckCircle2 className="w-4 h-4" />;
    case 'reporting': return <FileText className="w-4 h-4" />;
    default: return <Bot className="w-4 h-4" />;
  }
};

const TIER_BADGES: Record<string, string> = {
  deep: 'bg-purple-500/20 text-purple-400',
  reasoning: 'bg-sky-500/20 text-sky-400',
  fast: 'bg-emerald-500/20 text-emerald-400',
  frontier: 'bg-purple-500/20 text-purple-400',
  standard: 'bg-sky-500/20 text-sky-400',
};

const PARADIGM_BADGES: Record<string, string> = {
  rational: 'bg-blue-500/20 text-blue-400',
  hybrid: 'bg-amber-500/20 text-amber-400',
  alternative: 'bg-rose-500/20 text-rose-400',
};

const AgentCard: React.FC<AgentCardProps> = ({ agent }) => {
  const { t } = useTranslation();
  const isActive = agent.status !== 'idle';
  const isProvisioning = agent.status === 'provisioning' || agent.status === 'intake' || agent.status === 'setup';
  
  return (
    <motion.div 
      layout
      className={`p-3 border rounded-xl flex flex-col gap-2 transition-all duration-300 ${
        isActive 
          ? 'bg-aws-orange/5 border-aws-orange/20' 
          : 'bg-black/5 dark:bg-white/5 border-border-main opacity-60'
      }`}
    >
      {/* Header: Role icon + Name + Model tier badge */}
      <div className="flex items-center gap-3">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
          isActive ? 'bg-aws-orange/20 text-aws-orange font-bold' : 'bg-black/10 dark:bg-white/10 text-secondary-dynamic'
        }`}>
          <RoleIcon role={agent.role} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className={`text-xs font-semibold truncate ${isActive ? 'text-dynamic' : 'text-secondary-dynamic'}`}>
              {agent.name}
            </p>
            {agent.modelTier && (
              <span className={`text-[7px] font-mono px-1.5 py-0.5 rounded-full shrink-0 ${TIER_BADGES[agent.modelTier] || TIER_BADGES.standard}`}>
                {agent.modelTier}
              </span>
            )}
          </div>
          {/* Subtask: the focused instruction from the Conductor */}
          <AnimatePresence mode="wait">
            <motion.p 
              key={agent.subtask || agent.lastMessage}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className={`text-[10px] truncate ${isActive ? 'text-aws-orange/80' : 'text-secondary-dynamic'}`}
            >
              {agent.subtask || agent.lastMessage || (isActive ? (isProvisioning ? t('agents.onboarding') : t('agents.analyzing')) : t('agents.standby'))}
            </motion.p>
          </AnimatePresence>
        </div>
        {isActive && (
          <div className="shrink-0">
            <StatusIcon status={agent.status} />
          </div>
        )}
      </div>

      {/* Stage indicator + Topology badge */}
      {(agent.stageIndex || agent.topology) && (
        <div className="flex items-center gap-2 px-1">
          {agent.stageIndex && agent.totalStages && (
            <span className="text-[8px] font-mono text-secondary-dynamic">
              Stage {agent.stageIndex}/{agent.totalStages}
            </span>
          )}
          {agent.topology && (
            <span className="text-[7px] font-mono px-1.5 py-0.5 rounded bg-black/5 dark:bg-white/5 text-secondary-dynamic">
              {agent.topology}
            </span>
          )}
          {agent.paradigm && (
            <span className={`text-[7px] font-mono px-1.5 py-0.5 rounded-full ${PARADIGM_BADGES[agent.paradigm] || ''}`}>
              {agent.paradigm}
            </span>
          )}
        </div>
      )}

      {/* Progress bar for active agents */}
      {isProvisioning && (
        <div className="space-y-1">
          <div className="flex justify-between text-[8px] font-mono text-aws-orange/60 px-1">
            <span>FDE_INTAKE</span>
            <span>{agent.progress || 0}%</span>
          </div>
          <div className="h-1 bg-white/5 rounded-full overflow-hidden">
            <motion.div 
              className="h-full bg-aws-orange"
              initial={{ width: 0 }}
              animate={{ width: `${agent.progress || 0}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
        </div>
      )}
    </motion.div>
  );
};

export const AgentSidebar: React.FC<{ agents: Agent[] }> = ({ agents }) => {
  const { t } = useTranslation();

  // Extract synapse metadata from first agent (shared across squad)
  const firstWithSynapse = agents.find((a) => a.designQuality !== undefined);
  const designQuality = firstWithSynapse?.designQuality;

  return (
    <div className="h-full flex flex-col transition-colors duration-300">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-xl font-medium text-dynamic">{t('agents.title')}</h2>
          <p className="text-xs text-secondary-dynamic font-mono">{t('agents.subtitle')}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className="text-[10px] text-aws-orange font-bold tracking-widest">{t('agents.autonomy_level')}</span>
          <span className="text-[10px] text-secondary-dynamic">{t('agents.pipeline_mode')}</span>
          {designQuality !== undefined && (
            <span className={`text-[9px] font-mono px-2 py-0.5 rounded-full ${
              designQuality >= 0.7 ? 'bg-emerald-500/20 text-emerald-400' :
              designQuality >= 0.4 ? 'bg-amber-500/20 text-amber-400' :
              'bg-red-500/20 text-red-400'
            }`}>
              Design Quality: {(designQuality * 100).toFixed(0)}%
            </span>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto space-y-4 pr-2 scrollbar-thin">
        {agents.map(agent => (
          <AgentCard key={agent.id} agent={agent} />
        ))}
      </div>
    </div>
  );
};
