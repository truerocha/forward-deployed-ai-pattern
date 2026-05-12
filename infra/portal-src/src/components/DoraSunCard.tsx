/**
 * DoraSunCard — The pulsing DORA health indicator.
 *
 * Implements PEC Blueprint Chapter 11 ("DORA Sun"):
 *   "O componente central que pulsa com a saúde da Squad."
 *
 * Displays:
 *   - Health pulse (0-100) as a radial gauge with pulsing animation
 *   - Current DORA level (Elite/High/Medium/Low)
 *   - Projected level at T+7d
 *   - Weakest metric identification
 *   - Trend arrows per metric
 */

import React from 'react';
import { Sun, TrendingUp, TrendingDown, Minus, AlertTriangle } from 'lucide-react';

interface ForecastData {
  health_pulse?: number;
  current_level?: string;
  projected_level_7d?: string;
  projected_level_30d?: string;
  weakest_metric?: string;
  weakest_reason?: string;
  risk_adjusted_cfr?: number;
  metrics?: {
    lead_time?: { trend_direction: string; current_value: number };
    deploy_frequency?: { trend_direction: string; current_value: number };
    change_fail_rate?: { trend_direction: string; current_value: number };
    mttr?: { trend_direction: string; current_value: number };
  };
}

interface DoraSunCardProps {
  forecast?: ForecastData | null;
}

const LEVEL_COLORS: Record<string, string> = {
  Elite: 'text-emerald-400',
  High: 'text-sky-400',
  Medium: 'text-amber-400',
  Low: 'text-red-400',
};

const LEVEL_BG: Record<string, string> = {
  Elite: 'bg-emerald-500/10 border-emerald-500/20',
  High: 'bg-sky-500/10 border-sky-500/20',
  Medium: 'bg-amber-500/10 border-amber-500/20',
  Low: 'bg-red-500/10 border-red-500/20',
};

const TrendArrow: React.FC<{ direction: string }> = ({ direction }) => {
  if (direction === 'improving') return <TrendingUp className="w-3 h-3 text-emerald-400" aria-label="Improving" />;
  if (direction === 'degrading') return <TrendingDown className="w-3 h-3 text-red-400" aria-label="Degrading" />;
  return <Minus className="w-3 h-3 text-slate-400" aria-label="Stable" />;
};

export const DoraSunCard: React.FC<DoraSunCardProps> = ({ forecast }) => {
  const pulse = forecast?.health_pulse ?? 50;
  const level = forecast?.current_level || 'Medium';
  const projected = forecast?.projected_level_7d || level;
  const weakest = forecast?.weakest_metric || '';
  const weakestReason = forecast?.weakest_reason || '';
  const metrics = forecast?.metrics;

  const pulseSpeed = pulse >= 80 ? '2s' : pulse >= 50 ? '3s' : '4s';
  const arcDegrees = (pulse / 100) * 270;

  return (
    <div className="bg-bg-card border border-border-main rounded-xl p-4 relative overflow-hidden">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Sun
            className={`w-5 h-5 ${LEVEL_COLORS[level] || 'text-amber-400'}`}
            style={{ animation: `pulse ${pulseSpeed} ease-in-out infinite` }}
            aria-hidden="true"
          />
          <h3 className="text-xs font-bold text-dynamic uppercase tracking-wider">DORA Sun</h3>
        </div>
        <div className={`px-2 py-0.5 rounded text-[9px] font-bold uppercase border ${LEVEL_BG[level] || LEVEL_BG['Medium']}`}>
          <span className={LEVEL_COLORS[level] || 'text-amber-400'}>{level}</span>
        </div>
      </div>

      <div className="flex items-center justify-center my-4">
        <div className="relative w-24 h-24">
          <svg className="w-full h-full -rotate-[135deg]" viewBox="0 0 100 100" aria-hidden="true">
            <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" strokeWidth="8" strokeDasharray="198" strokeDashoffset="0" strokeLinecap="round" className="text-white/5" />
            <circle cx="50" cy="50" r="42" fill="none" stroke="currentColor" strokeWidth="8" strokeDasharray="198" strokeDashoffset={198 - (198 * (arcDegrees / 270))} strokeLinecap="round" className={pulse >= 80 ? 'text-emerald-400' : pulse >= 50 ? 'text-amber-400' : 'text-red-400'} />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-2xl font-mono font-bold text-dynamic">{pulse}</span>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-center gap-2 mb-3">
        <span className="text-[9px] text-secondary-dynamic">7d forecast:</span>
        <span className={`text-[10px] font-bold ${LEVEL_COLORS[projected] || 'text-amber-400'}`}>
          {level !== projected ? `${level} → ${projected}` : `${level} (stable)`}
        </span>
      </div>

      {metrics && (
        <div className="grid grid-cols-4 gap-2 mb-3">
          {[
            { key: 'lead_time', label: 'LT' },
            { key: 'deploy_frequency', label: 'DF' },
            { key: 'change_fail_rate', label: 'CFR' },
            { key: 'mttr', label: 'MTTR' },
          ].map(({ key, label }) => {
            const metric = metrics[key as keyof typeof metrics];
            return (
              <div key={key} className="flex flex-col items-center gap-0.5">
                <span className="text-[8px] text-secondary-dynamic font-mono">{label}</span>
                {metric ? <TrendArrow direction={metric.trend_direction} /> : <Minus className="w-3 h-3 text-slate-500" />}
              </div>
            );
          })}
        </div>
      )}

      {weakest && (
        <div className="flex items-center gap-2 p-2 rounded-lg bg-red-500/5 border border-red-500/10">
          <AlertTriangle className="w-3 h-3 text-red-400 shrink-0" aria-hidden="true" />
          <div className="min-w-0">
            <p className="text-[9px] font-bold text-red-400 uppercase">Weakest: {weakest.replace('_', ' ')}</p>
            {weakestReason && <p className="text-[8px] text-secondary-dynamic truncate">{weakestReason}</p>}
          </div>
        </div>
      )}

      {!forecast && (
        <div className="flex flex-col items-center justify-center py-4 opacity-40">
          <Sun className="w-8 h-8 mb-2" />
          <p className="text-[9px] font-mono uppercase">Awaiting forecast data</p>
          <p className="text-[8px] text-secondary-dynamic">Requires 3+ weekly snapshots</p>
        </div>
      )}
    </div>
  );
};
