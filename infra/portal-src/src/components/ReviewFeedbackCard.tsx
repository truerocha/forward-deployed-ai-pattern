/**
 * ReviewFeedbackCard — ICRL Review Feedback Loop Observability.
 *
 * Displays the closed-loop learning metrics from human PR reviews:
 *   - Review classification breakdown (full_rework / partial_fix / approval)
 *   - Rework cycle count and circuit breaker status
 *   - ICRL episode count and pattern digest availability
 *   - Verification gate pass rate (pre-PR deterministic checks)
 *   - Conditional autonomy adjustments from review feedback
 *
 * Personas:
 *   - Staff Engineer: Full view (all metrics + ICRL episodes + autonomy adjustments)
 *   - SWE: Rework status, verification gate results, episode learning context
 *   - PM: Rework rate as DORA fifth metric, trust trend from reviews
 *   - SRE: Circuit breaker status, verification gate health
 *
 * Cloudscape alignment:
 *   - StatusIndicator pattern for classification badges
 *   - ProgressBar for verification gate confidence
 *   - KeyValuePairs for episode metrics
 *   - Alert for circuit breaker trips
 *
 * Ref: docs/adr/ADR-027-review-feedback-loop.md (V2: ICRL Enhancement)
 */

import React from 'react';
import { Brain, AlertTriangle, CheckCircle, XCircle, RotateCcw } from 'lucide-react';

// ─── Types ──────────────────────────────────────────────────────

interface ReviewFeedbackMetrics {
  total_reviews: number;
  full_rework_count: number;
  partial_fix_count: number;
  approval_count: number;
  informational_count: number;
  active_rework_tasks: number;
  circuit_breaker_trips: number;
  avg_rework_attempts: number;
  icrl_episode_count: number;
  pattern_digest_available: boolean;
  last_episode_timestamp: string;
  verification_pass_rate: number;
  avg_verification_iterations: number;
  verification_level: string;
  autonomy_reductions: number;
  autonomy_increases: number;
  current_autonomy_level: number;
}

interface ReviewFeedbackCardProps {
  metrics?: ReviewFeedbackMetrics | null;
}

// ─── Sub-components ─────────────────────────────────────────────

const ClassificationBadge: React.FC<{
  label: string;
  count: number;
  color: string;
  icon: React.ReactNode;
}> = ({ label, count, color, icon }) => (
  <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-black/5 dark:bg-white/5">
    <span className={color}>{icon}</span>
    <span className="text-[9px] text-secondary-dynamic uppercase">{label}</span>
    <span className={`text-xs font-mono font-bold ${color}`}>{count}</span>
  </div>
);

const MetricRow: React.FC<{
  label: string;
  value: string | number;
  status?: 'good' | 'warning' | 'critical';
}> = ({ label, value, status }) => {
  const statusColor = status === 'good'
    ? 'text-emerald-400'
    : status === 'warning'
      ? 'text-amber-400'
      : status === 'critical'
        ? 'text-red-400'
        : 'text-dynamic';

  return (
    <div className="flex justify-between items-center py-1">
      <span className="text-[9px] text-secondary-dynamic uppercase">{label}</span>
      <span className={`text-[10px] font-mono font-bold ${statusColor}`}>{value}</span>
    </div>
  );
};

const ProgressBar: React.FC<{
  value: number;
  label: string;
  color: string;
}> = ({ value, label, color }) => (
  <div className="w-full">
    <div className="flex justify-between items-center mb-1">
      <span className="text-[9px] text-secondary-dynamic uppercase">{label}</span>
      <span className="text-[9px] font-mono text-dynamic">{value.toFixed(0)}%</span>
    </div>
    <div className="w-full h-1.5 rounded-full bg-slate-200 dark:bg-slate-800">
      <div
        className={`h-full rounded-full transition-all duration-700 ${color}`}
        style={{ width: `${Math.min(value, 100)}%` }}
      />
    </div>
  </div>
);

// ─── Main Component ─────────────────────────────────────────────

export const ReviewFeedbackCard: React.FC<ReviewFeedbackCardProps> = ({ metrics }) => {
  if (!metrics) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <Brain className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Review Feedback Loop</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No ICRL data yet
        </p>
      </div>
    );
  }

  const reworkRate = metrics.total_reviews > 0
    ? ((metrics.full_rework_count / metrics.total_reviews) * 100)
    : 0;

  const hasCircuitBreaker = metrics.circuit_breaker_trips > 0;

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-start mb-3">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-aws-orange" aria-hidden="true" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">
            ICRL Feedback Loop
          </h2>
        </div>
        <div className="flex items-center gap-1">
          <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${
            metrics.pattern_digest_available
              ? 'bg-emerald-500/20 text-emerald-400'
              : 'bg-slate-500/20 text-secondary-dynamic'
          }`}>
            {metrics.icrl_episode_count} episodes
          </span>
        </div>
      </div>

      {/* Circuit Breaker Alert */}
      {hasCircuitBreaker && (
        <div className="mb-3 p-2 rounded-lg bg-red-500/10 border border-red-500/30 flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 text-red-400 flex-shrink-0" aria-hidden="true" />
          <span className="text-[9px] text-red-400 font-medium">
            Circuit breaker tripped ({metrics.circuit_breaker_trips}x) — Staff Engineer review required
          </span>
        </div>
      )}

      {/* Classification Breakdown */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        <ClassificationBadge
          label="Rework"
          count={metrics.full_rework_count}
          color="text-red-400"
          icon={<XCircle className="w-3 h-3" />}
        />
        <ClassificationBadge
          label="Fix"
          count={metrics.partial_fix_count}
          color="text-amber-400"
          icon={<RotateCcw className="w-3 h-3" />}
        />
        <ClassificationBadge
          label="Approved"
          count={metrics.approval_count}
          color="text-emerald-400"
          icon={<CheckCircle className="w-3 h-3" />}
        />
      </div>

      {/* Verification Gate */}
      <ProgressBar
        value={metrics.verification_pass_rate}
        label="Verification Gate Pass Rate"
        color={metrics.verification_pass_rate >= 80 ? 'bg-emerald-500' : metrics.verification_pass_rate >= 50 ? 'bg-amber-500' : 'bg-red-500'}
      />

      {/* Key Metrics */}
      <div className="mt-3 space-y-0.5 flex-1">
        <MetricRow
          label="Rework Rate (5th DORA)"
          value={`${reworkRate.toFixed(1)}%`}
          status={reworkRate <= 10 ? 'good' : reworkRate <= 25 ? 'warning' : 'critical'}
        />
        <MetricRow
          label="Avg Verification Iterations"
          value={metrics.avg_verification_iterations.toFixed(1)}
          status={metrics.avg_verification_iterations <= 1.5 ? 'good' : 'warning'}
        />
        <MetricRow
          label="Autonomy Level"
          value={`L${metrics.current_autonomy_level}`}
          status={metrics.current_autonomy_level >= 3 ? 'good' : 'warning'}
        />
        <MetricRow
          label="Verification Level"
          value={metrics.verification_level}
          status={metrics.verification_level === 'full' ? 'good' : metrics.verification_level === 'bypass' ? 'critical' : 'warning'}
        />
      </div>

      {/* Autonomy Adjustments */}
      <div className="mt-2 p-2 rounded-lg bg-black/5 dark:bg-white/5 border border-border-main">
        <div className="flex justify-between items-center">
          <span className="text-[9px] text-secondary-dynamic uppercase">Autonomy Adjustments (7d)</span>
          <div className="flex gap-2">
            <span className="text-[9px] font-mono text-red-400">
              -{metrics.autonomy_reductions}
            </span>
            <span className="text-[9px] font-mono text-emerald-400">
              +{metrics.autonomy_increases}
            </span>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-2 pt-2 border-t border-border-main text-[9px] text-secondary-dynamic font-mono">
        ICRL closed-loop learning • {metrics.pattern_digest_available ? 'Pattern digest active' : 'Accumulating episodes'}
      </div>
    </div>
  );
};
