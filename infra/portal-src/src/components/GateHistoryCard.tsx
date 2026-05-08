import React from 'react';
import { motion } from 'motion/react';
import { History, CheckCircle2, XCircle, AlertTriangle, Clock } from 'lucide-react';

interface GateHistoryEntry {
  gate_name: string;
  status: 'pass' | 'fail' | 'warn' | 'pending';
  timestamp: string;
  feedback?: string;
}

interface GateHistoryCardProps {
  history?: GateHistoryEntry[] | null;
  taskId?: string;
}

const STATUS_CONFIG = {
  pass: { icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-500/10', dot: 'bg-emerald-500' },
  fail: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/10', dot: 'bg-red-500' },
  warn: { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/10', dot: 'bg-amber-500' },
  pending: { icon: Clock, color: 'text-slate-400', bg: 'bg-slate-500/10', dot: 'bg-slate-500' },
};

export const GateHistoryCard: React.FC<GateHistoryCardProps> = ({ history, taskId }) => {
  if (!history || history.length === 0) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <History className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Gate History</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No gate interactions
        </p>
      </div>
    );
  }

  const passCount = history.filter((h) => h.status === 'pass').length;
  const failCount = history.filter((h) => h.status === 'fail').length;

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-aws-orange" aria-hidden="true" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">
            Gate History
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[9px] font-mono text-emerald-400">{passCount}✓</span>
          <span className="text-[9px] font-mono text-red-400">{failCount}✗</span>
        </div>
      </div>

      {/* Task ID */}
      {taskId && (
        <div className="mb-3 px-2 py-1 rounded bg-black/5 dark:bg-white/5">
          <span className="text-[9px] text-secondary-dynamic font-mono">Task: {taskId}</span>
        </div>
      )}

      {/* Timeline */}
      <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin">
        {history.map((entry, idx) => {
          const config = STATUS_CONFIG[entry.status] || STATUS_CONFIG.pending;
          const Icon = config.icon;
          const isLast = idx === history.length - 1;

          return (
            <motion.div
              key={`${entry.gate_name}-${entry.timestamp}-${idx}`}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2, delay: idx * 0.05 }}
              className="flex gap-3 relative"
            >
              {/* Connector line */}
              {!isLast && (
                <div className="absolute left-[11px] top-6 bottom-0 w-px bg-border-main" />
              )}

              {/* Status dot */}
              <div className={`flex-shrink-0 w-6 h-6 rounded-full ${config.bg} flex items-center justify-center`}>
                <Icon className={`w-3 h-3 ${config.color}`} aria-hidden="true" />
              </div>

              {/* Content */}
              <div className="flex-1 pb-4">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-medium text-dynamic">{entry.gate_name}</span>
                  <span className="text-[9px] font-mono text-secondary-dynamic">
                    {new Date(entry.timestamp).toLocaleTimeString()}
                  </span>
                </div>
                {entry.feedback && (
                  <p className="text-[9px] text-secondary-dynamic mt-0.5 leading-relaxed">
                    {entry.feedback}
                  </p>
                )}
              </div>
            </motion.div>
          );
        })}
      </div>

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main flex justify-between text-[9px] text-secondary-dynamic font-mono">
        <span>{history.length} gate interactions</span>
        <span>Unified timeline view</span>
      </div>
    </div>
  );
};
