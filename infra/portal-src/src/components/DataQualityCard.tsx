import React from 'react';
import { Database, AlertCircle, CheckCircle2, AlertTriangle } from 'lucide-react';

interface DataQualityAssessment {
  name: string;
  composite_score: number;
  is_stale: boolean;
  alerts: string[];
}

interface DataQualityCardProps {
  assessments?: DataQualityAssessment[] | null;
}

const getHealthColor = (score: number, isStale: boolean): { bg: string; text: string; dot: string; label: string } => {
  if (isStale || score < 40) {
    return { bg: 'bg-red-500/10', text: 'text-red-400', dot: 'bg-red-500', label: 'Critical' };
  }
  if (score < 70) {
    return { bg: 'bg-amber-500/10', text: 'text-amber-400', dot: 'bg-amber-500', label: 'Warning' };
  }
  return { bg: 'bg-emerald-500/10', text: 'text-emerald-400', dot: 'bg-emerald-500', label: 'Healthy' };
};

const HealthIcon: React.FC<{ score: number; isStale: boolean }> = ({ score, isStale }) => {
  if (isStale || score < 40) {
    return <AlertCircle className="w-3.5 h-3.5 text-red-400" aria-hidden="true" />;
  }
  if (score < 70) {
    return <AlertTriangle className="w-3.5 h-3.5 text-amber-400" aria-hidden="true" />;
  }
  return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" aria-hidden="true" />;
};

export const DataQualityCard: React.FC<DataQualityCardProps> = ({ assessments }) => {
  if (!assessments || assessments.length === 0) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <Database className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Data Quality</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No artifacts assessed
        </p>
      </div>
    );
  }

  const healthyCount = assessments.filter((a) => a.composite_score >= 70 && !a.is_stale).length;
  const warningCount = assessments.filter((a) => a.composite_score >= 40 && a.composite_score < 70 && !a.is_stale).length;
  const criticalCount = assessments.filter((a) => a.composite_score < 40 || a.is_stale).length;

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-aws-orange" aria-hidden="true" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">
            Data Quality
          </h2>
        </div>
      </div>

      {/* Summary traffic lights */}
      <div className="flex gap-4 mb-4 pb-4 border-b border-border-main">
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
          <span className="text-[10px] font-mono text-secondary-dynamic">{healthyCount}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-amber-500" />
          <span className="text-[10px] font-mono text-secondary-dynamic">{warningCount}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-red-500" />
          <span className="text-[10px] font-mono text-secondary-dynamic">{criticalCount}</span>
        </div>
      </div>

      {/* Artifact list */}
      <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin space-y-2">
        {assessments.map((assessment) => {
          const health = getHealthColor(assessment.composite_score, assessment.is_stale);
          return (
            <div
              key={assessment.name}
              className={`p-2.5 rounded-lg ${health.bg} border border-current/10`}
              style={{ borderColor: 'transparent' }}
            >
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <HealthIcon score={assessment.composite_score} isStale={assessment.is_stale} />
                  <span className="text-[10px] font-medium text-dynamic truncate">{assessment.name}</span>
                </div>
                <div className="flex items-center gap-2">
                  {assessment.is_stale && (
                    <span className="text-[8px] font-mono text-red-400 uppercase px-1 py-0.5 rounded bg-red-500/10">
                      Stale
                    </span>
                  )}
                  <span className={`text-[10px] font-mono font-bold ${health.text}`}>
                    {assessment.composite_score}
                  </span>
                </div>
              </div>
              {assessment.alerts.length > 0 && (
                <div className="mt-1.5 space-y-0.5">
                  {assessment.alerts.slice(0, 2).map((alert, idx) => (
                    <p key={idx} className="text-[9px] text-secondary-dynamic leading-tight pl-5">
                      • {alert}
                    </p>
                  ))}
                  {assessment.alerts.length > 2 && (
                    <p className="text-[9px] text-secondary-dynamic pl-5 opacity-60">
                      +{assessment.alerts.length - 2} more
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main text-[9px] text-secondary-dynamic font-mono">
        {assessments.length} knowledge artifacts assessed
      </div>
    </div>
  );
};
