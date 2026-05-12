import React, { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Hash } from 'lucide-react';
import DOMPurify from 'dompurify';
import { LogEntry } from '../types';
import { useTranslation } from 'react-i18next';

export const Terminal = ({ logs }: { logs: LogEntry[] }) => {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [logs]);

  return (
    <div className="flex-1 flex flex-col overflow-hidden transition-colors duration-300">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-xl font-medium text-dynamic">{t('terminal.title')}</h2>
          <p className="text-xs text-secondary-dynamic font-mono">{t('terminal.subtitle')}</p>
        </div>
      </div>
      <div 
        ref={scrollRef}
        role="log"
        aria-live="polite"
        aria-label="Agent reasoning logs"
        className="flex-1 bg-black/10 dark:bg-black/40 rounded-2xl border border-border-color p-6 font-mono text-[13px] overflow-y-auto scrollbar-thin"
      >
        <AnimatePresence mode="popLayout">
          {logs.map((log) => (
            <motion.div 
              key={log.id}
              initial={{ opacity: 0, x: 5 }}
              animate={{ opacity: 1, x: 0 }}
              className="flex gap-4 mb-4 items-start group"
            >
              <span className="text-[10px] font-mono opacity-30 shrink-0 mt-1">[{log.timestamp}]</span>
              <div className={`w-1 self-stretch rounded-full shrink-0 ${
                log.type === 'thought' ? 'bg-aws-orange/40' : 
                log.type === 'action' ? 'bg-blue-400' :
                log.type === 'working' ? 'bg-aws-orange' :
                log.type === 'complete' ? 'bg-emerald-500' :
                log.type === 'system' ? 'bg-zinc-700' :
                log.type === 'error' ? 'bg-red-500' : 'bg-slate-300'
              }`} />
              <div className="flex-1 min-w-0">
                <span className={`font-bold inline-block mr-3 ${
                  log.type === 'thought' ? 'text-aws-orange/70' : 
                  log.type === 'action' ? 'text-blue-400' :
                  log.type === 'working' ? 'text-aws-orange' :
                  log.type === 'complete' ? 'text-emerald-500' :
                  log.type === 'system' ? 'text-zinc-500' :
                  log.type === 'error' ? 'text-red-400' : 'text-slate-300'
                }`}>
                  {log.agentName}
                </span>
                <p 
                  className="opacity-80 inline leading-relaxed"
                  dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(log.message) }}
                />
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
        {logs.length === 0 && (
          <div className="h-full flex items-center justify-center opacity-10 flex-col gap-2">
            <Hash className="w-8 h-8" aria-hidden="true" />
            <p className="font-mono text-[10px] uppercase tracking-widest">{t('terminal.awaiting')}</p>
          </div>
        )}
      </div>
    </div>
  );
};
