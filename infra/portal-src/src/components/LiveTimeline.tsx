import React, { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Activity, CheckCircle2, XCircle, Clock, Wifi, WifiOff, Loader2 } from 'lucide-react';

interface TimelineEvent {
  type: 'stage_start' | 'stage_complete' | 'stage_error' | 'info' | 'warning';
  timestamp: string;
  message: string;
  status: 'running' | 'success' | 'error' | 'pending' | 'skipped';
}

interface LiveTimelineProps {
  events: TimelineEvent[];
  autoScroll?: boolean;
  wsConnected?: boolean;
}

const STATUS_CONFIG = {
  running: { icon: Loader2, color: 'text-aws-orange', bg: 'bg-aws-orange/10', animate: true },
  success: { icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-500/10', animate: false },
  error: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/10', animate: false },
  pending: { icon: Clock, color: 'text-slate-400', bg: 'bg-slate-500/10', animate: false },
  skipped: { icon: Clock, color: 'text-slate-500', bg: 'bg-slate-500/5', animate: false },
};

const TimelineItem: React.FC<{ event: TimelineEvent; isLast: boolean }> = ({ event, isLast }) => {
  const config = STATUS_CONFIG[event.status] || STATUS_CONFIG.pending;
  const Icon = config.icon;

  return (
    <motion.div
      initial={{ opacity: 0, x: -12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.3 }}
      className="flex gap-3 relative"
    >
      {/* Vertical connector line */}
      {!isLast && (
        <div className="absolute left-[11px] top-6 bottom-0 w-px bg-border-main" />
      )}

      {/* Status icon */}
      <div className={`flex-shrink-0 w-6 h-6 rounded-full ${config.bg} flex items-center justify-center`}>
        <Icon
          className={`w-3 h-3 ${config.color} ${config.animate ? 'animate-spin' : ''}`}
          aria-hidden="true"
        />
      </div>

      {/* Content */}
      <div className="flex-1 pb-4">
        <p className="text-xs text-dynamic font-medium leading-tight">{event.message}</p>
        <p className="text-[9px] text-secondary-dynamic font-mono mt-0.5">
          {new Date(event.timestamp).toLocaleTimeString()}
          <span className="ml-2 uppercase opacity-60">{event.type.replace(/_/g, ' ')}</span>
        </p>
      </div>
    </motion.div>
  );
};

export const LiveTimeline: React.FC<LiveTimelineProps> = ({
  events,
  autoScroll = true,
  wsConnected = false,
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [events, autoScroll]);

  return (
    <div className="h-full bento-card flex flex-col transition-colors duration-300">
      {/* Header */}
      <div className="flex justify-between items-center mb-4">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-aws-orange" aria-hidden="true" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">
            Live Timeline
          </h2>
        </div>
        <div className="flex items-center gap-1.5">
          {wsConnected ? (
            <Wifi className="w-3 h-3 text-emerald-400" aria-hidden="true" />
          ) : (
            <WifiOff className="w-3 h-3 text-red-400" aria-hidden="true" />
          )}
          <span className={`text-[9px] font-mono ${wsConnected ? 'text-emerald-400' : 'text-red-400'}`}>
            {wsConnected ? 'POLLING' : 'DISCONNECTED'}
          </span>
        </div>
      </div>

      {/* Timeline */}
      {events.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center">
          <Clock className="w-10 h-10 text-slate-700 mb-3" aria-hidden="true" />
          <p className="text-xs text-secondary-dynamic">No events yet</p>
          <p className="text-[9px] text-secondary-dynamic font-mono mt-1">Waiting for pipeline execution…</p>
        </div>
      ) : (
        <div ref={scrollRef} className="flex-1 overflow-y-auto pr-2 scrollbar-thin">
          <AnimatePresence>
            {events.map((event, idx) => (
              <TimelineItem key={`${event.timestamp}-${idx}`} event={event} isLast={idx === events.length - 1} />
            ))}
          </AnimatePresence>
        </div>
      )}

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main flex justify-between text-[9px] text-secondary-dynamic font-mono">
        <span>{events.length} events</span>
        <span>{autoScroll ? 'Auto-scroll ON' : 'Auto-scroll OFF'}</span>
      </div>
    </div>
  );
};
