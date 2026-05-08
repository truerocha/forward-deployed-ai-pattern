import React from 'react';
import { ShieldAlert, CheckCircle2, XCircle, AlertTriangle, Lightbulb } from 'lucide-react';

interface GateFeedback {
  gate_name: string;
  status: 'pass' | 'fail' | 'warn';
  reason: string;
  violated_rule?: string;
  suggestion?: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
}

interface GateFeedbackCardProps {
  feedback?: GateFeedback | null;
}

const STATUS_CONFIG = {
  pass: { icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', label: 'PASSED' },
  fail: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/20', label: 'REJECTED' },
  warn: { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20', label: 'WARNING' },
};

const SEVERITY_CONFIG = {
  critical: { color: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/20' },
  high: { color: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/20' },
  medium: { color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20' },
  low: { color: 'text-sky-400', bg: 'bg-sky-500/10', border: 'border-sky-500/20' },
};

export const GateFeedbackCard: React.FC<GateFeedbackCardProps> = ({ feedback }) => {
  if (!feedback) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <ShieldAlert className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Gate Feedback</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No gate results
        </p>
      </div>
    );
  }

  const statusConfig = STATUS_CONFIG[feedback.status] || STATUS_CONFIG.fail;
  const severityConfig = SEVERITY_CONFIG[feedback.severity] || SEVERITY_CONFIG.medium;
  const StatusIcon = statusConfig.icon;

  return (
    <div className={`h-full bento-card flex flex-col transition-colors duration-300 border-l-2 ${statusConfig.border.replace('border-', 'border-l-')}`}>
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div>
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest mb-1">
            Gate Feedback
          </h2>
          <p className="text-[10px] text-dynamic font-mono">{feedback.gate_name}</p>
        </div>
        <div className={`flex items-center gap-1.5 px-2 py-1 rounded ${statusConfig.bg} border ${statusConfig.border}`}>
          <StatusIcon className={`w-3 h-3 ${statusConfig.color}`} aria-hidden="true" />
          <span className={`text-[9px] font-bold uppercase ${statusConfig.color}`}>
            {statusConfig.label}
          </span>
        </div>
      </div>

      {/* Severity badge */}
      <div className="mb-4">
        <span className={`text-[9px] font-mono font-bold uppercase px-2 py-0.5 rounded ${severityConfig.bg} border ${severityConfig.border} ${severityConfig.color}`}>
          {feedback.severity} severity
        </span>
      </div>

      {/* Reason */}
      <div className="mb-4">
        <p className="text-[9px] text-secondary-dynamic uppercase font-medium mb-1">What Failed</p>
        <p className="text-xs text-dynamic leading-relaxed">{feedback.reason}</p>
      </div>

      {/* Violated rule */}
      {feedback.violated_rule && (
        <div className="mb-4 p-2.5 rounded-lg bg-black/5 dark:bg-white/5 border border-border-main">
          <p className="text-[9px] text-secondary-dynamic uppercase font-medium mb-1">Violated Rule</p>
          <p className="text-[10px] text-dynamic font-mono">{feedback.violated_rule}</p>
        </div>
      )}

      {/* Suggestion */}
      {feedback.suggestion && (
        <div className="flex-1 p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
          <div className="flex items-start gap-2">
            <Lightbulb className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0 mt-0.5" aria-hidden="true" />
            <div>
              <p className="text-[9px] text-emerald-400 uppercase font-medium mb-1">What To Do Next</p>
              <p className="text-[10px] text-emerald-300 leading-relaxed">{feedback.suggestion}</p>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main text-[9px] text-secondary-dynamic font-mono">
        Quality gate evaluation result
      </div>
    </div>
  );
};
