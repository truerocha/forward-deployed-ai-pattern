import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'motion/react';
import { MessageSquare, Clock, Send, AlertTriangle } from 'lucide-react';

interface HumanInputRequest {
  question: string;
  context: string;
  options?: string[];
  timeout_seconds: number;
  request_id: string;
}

interface HumanInputCardProps {
  request?: HumanInputRequest | null;
  onRespond: (requestId: string, response: string) => void;
}

export const HumanInputCard: React.FC<HumanInputCardProps> = ({ request, onRespond }) => {
  const [selectedOption, setSelectedOption] = useState<string>('');
  const [freeText, setFreeText] = useState('');
  const [remainingSeconds, setRemainingSeconds] = useState(0);

  useEffect(() => {
    if (!request) return;
    setRemainingSeconds(request.timeout_seconds);
    setSelectedOption('');
    setFreeText('');

    const interval = setInterval(() => {
      setRemainingSeconds((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [request]);

  const handleSubmit = useCallback(() => {
    if (!request) return;
    const response = selectedOption || freeText;
    if (response.trim()) {
      onRespond(request.request_id, response.trim());
    }
  }, [request, selectedOption, freeText, onRespond]);

  const timeoutPercent = request ? (remainingSeconds / request.timeout_seconds) * 100 : 0;
  const isUrgent = remainingSeconds > 0 && remainingSeconds <= 30;
  const isExpired = remainingSeconds === 0 && request !== null && request !== undefined;

  if (!request) {
    return (
      <div className="h-full bento-card flex flex-col items-center justify-center transition-colors duration-300">
        <MessageSquare className="w-12 h-12 text-slate-700 mb-4" aria-hidden="true" />
        <p className="text-sm font-medium text-dynamic mb-1">Human-in-the-Loop</p>
        <p className="text-[10px] text-secondary-dynamic font-mono uppercase tracking-widest">
          No pending requests
        </p>
      </div>
    );
  }

  return (
    <div className={`h-full bento-card flex flex-col transition-colors duration-300 ${isUrgent ? 'ring-1 ring-amber-500/40' : ''}`}>
      {/* Header */}
      <div className="flex justify-between items-start mb-3">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest">
            Agent Needs Input
          </h2>
        </div>
        <div className={`flex items-center gap-1 px-2 py-0.5 rounded ${isUrgent ? 'bg-red-500/10' : 'bg-slate-500/10'}`}>
          <Clock className={`w-3 h-3 ${isUrgent ? 'text-red-400' : 'text-secondary-dynamic'}`} aria-hidden="true" />
          <span className={`text-[10px] font-mono font-bold ${isUrgent ? 'text-red-400' : 'text-secondary-dynamic'}`}>
            {Math.floor(remainingSeconds / 60)}:{(remainingSeconds % 60).toString().padStart(2, '0')}
          </span>
        </div>
      </div>

      {/* Timeout progress bar */}
      <div className="w-full h-1 bg-black/5 dark:bg-white/5 rounded-full overflow-hidden mb-4">
        <motion.div
          animate={{ width: `${timeoutPercent}%` }}
          transition={{ duration: 1 }}
          className={`h-full rounded-full ${isUrgent ? 'bg-red-500' : 'bg-aws-orange'}`}
        />
      </div>

      {/* Question */}
      <div className="mb-3">
        <p className="text-xs text-dynamic font-medium">{request.question}</p>
        {request.context && (
          <p className="text-[10px] text-secondary-dynamic mt-1 leading-relaxed">{request.context}</p>
        )}
      </div>

      {/* Options */}
      {request.options && request.options.length > 0 && (
        <div className="space-y-1.5 mb-3 flex-1 overflow-y-auto">
          {request.options.map((option) => (
            <button
              key={option}
              onClick={() => setSelectedOption(option)}
              disabled={isExpired}
              className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-all ${
                selectedOption === option
                  ? 'bg-aws-orange/20 border border-aws-orange/40 text-dynamic'
                  : 'bg-black/5 dark:bg-white/5 border border-transparent text-secondary-dynamic hover:bg-black/10 dark:hover:bg-white/10'
              } ${isExpired ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
            >
              {option}
            </button>
          ))}
        </div>
      )}

      {/* Free text input */}
      {(!request.options || request.options.length === 0) && (
        <div className="flex-1 mb-3">
          <textarea
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            disabled={isExpired}
            placeholder="Type your response…"
            className="w-full h-full min-h-[60px] px-3 py-2 rounded-lg bg-black/5 dark:bg-white/5 border border-border-main text-xs text-dynamic placeholder:text-secondary-dynamic resize-none focus:outline-none focus:ring-1 focus:ring-aws-orange/40 disabled:opacity-50"
          />
        </div>
      )}

      {/* Expired warning */}
      {isExpired && (
        <div className="flex items-center gap-2 p-2 rounded-lg bg-red-500/10 border border-red-500/20 mb-3">
          <AlertTriangle className="w-3 h-3 text-red-400" aria-hidden="true" />
          <span className="text-[10px] text-red-400 font-mono">Request timed out — agent will use default</span>
        </div>
      )}

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={isExpired || (!selectedOption && !freeText.trim())}
        className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-aws-orange text-white text-xs font-bold uppercase tracking-wider hover:bg-aws-orange/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        <Send className="w-3 h-3" aria-hidden="true" />
        Respond
      </button>

      {/* Footer */}
      <div className="mt-3 pt-3 border-t border-border-main text-[9px] text-secondary-dynamic font-mono">
        Request ID: {request.request_id}
      </div>
    </div>
  );
};
