import React, { useState, useCallback, useRef, useEffect } from 'react';
import { 
  Play, 
  Cpu, 
  Eye, 
  ShieldCheck, 
  HeartPulse,
  Sun,
  Moon,
  Database,
  GitBranch,
  CheckCircle2,
  Clock,
  AlertCircle,
  BarChart3
} from 'lucide-react';
import { AgentSidebar } from './components/AgentSidebar';
import { Terminal } from './components/Terminal';
import { Header } from './components/Header';
import { MetricsCard } from './components/MetricsCard';
import { ComponentHealthCard } from './components/ComponentHealthCard';
import { RegistriesCard } from './components/RegistriesCard';
import { BranchEvaluationCard } from './components/BranchEvaluationCard';
import { Agent, LogEntry, AppView } from './types';
import { PersonaRouter } from './components/PersonaRouter';
import { PersonaFilteredCards } from './components/PersonaFilteredCards';
import { DoraCard } from './components/DoraCard';
import { CostCard } from './components/CostCard';
import { ValueStreamCard } from './components/ValueStreamCard';
import { MaturityRadar } from './components/MaturityRadar';
import { BrainSimCard } from './components/BrainSimCard';
import { TrustCard } from './components/TrustCard';
import { NetFrictionCard } from './components/NetFrictionCard';
import { GateFeedbackCard } from './components/GateFeedbackCard';
import { GateHistoryCard } from './components/GateHistoryCard';
import { DataQualityCard } from './components/DataQualityCard';
import { SquadExecutionCard } from './components/SquadExecutionCard';
import { LiveTimeline } from './components/LiveTimeline';
import { HumanInputCard } from './components/HumanInputCard';
import factoryConfig from './factory-config.json';
import { useTranslation } from 'react-i18next';
import {
  mapDoraMetrics,
  mapCostMetrics,
  mapGateHistory,
  mapLiveTimeline,
  mapSquadExecution,
} from './mappers/factoryDataMapper';

export default function App() {
  const { t, i18n } = useTranslation();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [activeView, setActiveView] = useState<AppView>('pipeline');
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [apiStatus, setApiStatus] = useState<any>(null);
  const [factoryData, setFactoryData] = useState<any>(null);
  const [activePersona, setActivePersona] = useState<string>('SWE');
  
  const isTabActive = useRef(true);

  const API_URL = document.querySelector('meta[name="factory-api-url"]')?.getAttribute('content') || '';

  // Fetch real health status
  const fetchHealth = useCallback(async () => {
    if (!API_URL) return;
    try {
      const res = await fetch(`${API_URL}/status/health`);
      if (res.ok) {
        const data = await res.json();
        setApiStatus(data);
      }
    } catch (err) {
      console.error('Failed to fetch factory health:', err);
    }
  }, [API_URL]);

  // Fetch real factory data (tasks, metrics, agents, events)
  const fetchFactoryData = useCallback(async () => {
    if (!API_URL) return;
    try {
      const res = await fetch(`${API_URL}/status/tasks`);
      if (res.ok) {
        const data = await res.json();
        setFactoryData(data);

        // Hydrate agents from API data
        if (data.agents && data.agents.length > 0) {
          const realAgents: Agent[] = data.agents.slice(0, 10).map((a: any) => ({
            id: a.instance_id,
            name: a.name || 'fde-pipeline',
            role: 'coder' as const,
            status: a.status === 'RUNNING' ? 'working' :
                    a.status === 'COMPLETED' ? 'complete' :
                    a.status === 'CREATED' ? 'idle' : 'idle',
            lastMessage: a.task_id ? `Task: ${a.task_id}` : undefined,
            progress: a.status === 'RUNNING' ? 50 : a.status === 'COMPLETED' ? 100 : 0,
          }));
          setAgents(realAgents);
        }

        // Hydrate reasoning logs from API events (survives page refresh)
        if (data.tasks && data.tasks.length > 0) {
          const apiLogs: LogEntry[] = [];

          // Sort tasks by updated_at (most recent first) and only show events
          // from the most recently active task (not all 15 tasks mixed together)
          const sortedTasks = [...data.tasks].sort((a: any, b: any) => 
            (b.updated_at || '').localeCompare(a.updated_at || '')
          );

          // Find the most recently active task (running or most recently completed)
          const activeTasks = sortedTasks.filter((t: any) => 
            t.status === 'running' || t.events?.length > 0
          ).slice(0, 3); // Show events from top 3 most recent tasks

          for (const task of activeTasks) {
            if (task.events && task.events.length > 0) {
              for (const ev of task.events) {
                // Extract agent name from event message or phase (squad mode)
                let agentName = 'System';
                if (ev.phase && ev.phase !== 'intake' && ev.phase !== 'workspace') {
                  agentName = ev.phase;
                } else if (ev.msg?.includes('Squad agent:')) {
                  const match = ev.msg.match(/Squad agent: (.+)/);
                  if (match) agentName = match[1];
                } else if (ev.msg?.includes('Stage started:') || ev.msg?.includes('Stage complete:')) {
                  const match = ev.msg.match(/(?:started|complete): (.+?)(?:\s*\(|$)/);
                  if (match) agentName = match[1];
                } else if (task.agent?.name) {
                  agentName = task.agent.name;
                }

                apiLogs.push({
                  id: `${task.task_id}-${ev.ts}-${apiLogs.length}`,
                  timestamp: ev.ts ? new Date(ev.ts).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '',
                  agentId: task.task_id,
                  agentName: agentName,
                  message: `[${task.task_id.slice(-8)}] ${ev.msg || ''}`,
                  type: ev.type === 'gate' ? (ev.gate_result === 'pass' ? 'action' : 'error') :
                        ev.type === 'error' ? 'error' :
                        ev.type === 'agent' ? 'working' :
                        ev.type === 'tool' ? 'thought' :
                        'system',
                  _sortKey: ev.ts || '',
                });
              }
            }
          }

          // Sort ALL events by timestamp (newest first — fresh info at top)
          apiLogs.sort((a: any, b: any) => (b._sortKey || '').localeCompare(a._sortKey || ''));
          setLogs(apiLogs);
        }
      }
    } catch (err) {
      console.error('Failed to fetch factory data:', err);
    }
  }, [API_URL]);

  // Sync theme with document
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // Initial load
  useEffect(() => {
    fetchHealth();
    fetchFactoryData();
  }, [fetchHealth, fetchFactoryData]);

  // Sync state view with URL hash
  useEffect(() => {
    const handleHash = () => {
      const hash = window.location.hash.replace('#', '') as AppView;
      if (['pipeline', 'agents', 'reasoning', 'gates', 'health', 'registries', 'observability'].includes(hash)) {
        setActiveView(hash);
      }
    };
    window.addEventListener('hashchange', handleHash);
    handleHash();
    return () => window.removeEventListener('hashchange', handleHash);
  }, []);

  const changeView = (view: AppView) => {
    window.location.hash = view;
    setActiveView(view);
  };

  // Polling: real API data — 5s interval for near-real-time observability
  // Matches the stream_callback flush interval (5s) for minimal delay
  useEffect(() => {
    let pollingInterval: NodeJS.Timeout;
    const startPolling = () => {
      pollingInterval = setInterval(() => {
        fetchHealth();
        fetchFactoryData();
      }, 5000);
    };
    const handleVisibility = () => {
      isTabActive.current = !document.hidden;
      if (document.hidden) {
        clearInterval(pollingInterval);
      } else {
        startPolling();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    startPolling();
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      clearInterval(pollingInterval);
    };
  }, [fetchHealth, fetchFactoryData]);

  const RailItem = ({ view, icon: Icon, label }: { view: AppView, icon: any, label: string }) => (
    <button 
      type="button"
      onClick={() => changeView(view)}
      aria-label={label}
      aria-current={activeView === view ? 'page' : undefined}
      className={`rail-item ${activeView === view ? 'rail-item-active' : ''}`}
    >
      <Icon className="rail-icon" aria-hidden="true" />
      <span className="rail-label">{label}</span>
    </button>
  );

  // Pipeline view: real task cards from API
  const tasks = factoryData?.tasks || [];
  const metrics = factoryData?.metrics || {};
  const isProcessing = metrics.active > 0;

  return (
    <div className="h-screen w-screen bg-bg-main flex overflow-hidden font-sans transition-colors duration-300">
      <a 
        href="#main-content" 
        className="fixed top-4 left-20 z-50 bg-aws-orange text-white px-4 py-2 rounded-lg -translate-y-20 focus:translate-y-0 transition-transform font-bold text-sm shadow-xl"
      >
        Skip to main content
      </a>
      {/* Rail Navigation */}
      <aside 
        role="navigation"
        aria-label="Side navigation"
        className="w-16 bg-bg-card border-r border-border-main flex flex-col items-center py-6 shrink-0 relative transition-colors duration-300"
      >
        <div className="mb-8" aria-hidden="true">
          <div className="w-10 h-[1px] bg-border-main"></div>
        </div>
        
        <nav className="flex-1 flex flex-col gap-2">
          <RailItem view="pipeline" icon={Play} label={t('nav.flow')} />
          <RailItem view="agents" icon={Cpu} label={t('nav.units')} />
          <RailItem view="reasoning" icon={Eye} label={t('nav.reason')} />
          <RailItem view="gates" icon={ShieldCheck} label={t('nav.gates')} />
          <RailItem view="health" icon={HeartPulse} label={t('nav.health')} />
          <RailItem view="registries" icon={Database} label={t('nav.catalog')} />
          <RailItem view="observability" icon={BarChart3} label="METRICS" />
        </nav>

        <div className="flex flex-col gap-2 mt-auto mb-4">
          <button 
            onClick={() => {
              const langs = ['en-US', 'pt-BR', 'es'];
              const currentIndex = langs.indexOf(i18n.language);
              const nextIndex = (currentIndex + 1) % langs.length;
              i18n.changeLanguage(langs[nextIndex]);
            }}
            className="w-10 h-10 rounded-xl border border-border-main flex items-center justify-center text-[9px] font-bold text-slate-500 hover:text-aws-orange hover:bg-black/5 dark:hover:bg-white/5 transition-all"
            aria-label="Toggle language"
          >
            {i18n.language === 'en-US' ? 'EN' : i18n.language === 'pt-BR' ? 'PT' : 'ES'}
          </button>
          
          <button 
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            className="w-10 h-10 rounded-xl border border-border-main flex items-center justify-center text-slate-500 hover:text-aws-orange hover:bg-black/5 dark:hover:bg-white/5 transition-all"
          >
            {theme === 'dark' ? <Sun className="w-5 h-5" aria-hidden="true" /> : <Moon className="w-5 h-5" aria-hidden="true" />}
          </button>
        </div>
      </aside>

      {/* Content Area */}
      <div className="flex-1 flex flex-col p-6 overflow-hidden">
        <Header isProcessing={isProcessing} />

        <main id="main-content" className="flex-1 flex flex-col overflow-hidden">
          {activeView === 'pipeline' && (
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="flex justify-between items-center mb-6">
                <div>
                  <h2 className="text-xl font-medium text-dynamic">{t('pipeline.title')}</h2>
                  <p className="text-xs text-secondary-dynamic font-mono">{t('pipeline.subtitle')}</p>
                </div>
                <div className="flex gap-3 text-[10px] font-mono">
                  <span className="px-2 py-1 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    Active: {metrics.active || 0}
                  </span>
                  <span className="px-2 py-1 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                    Completed 24h: {metrics.completed_24h || 0}
                  </span>
                  <span className="px-2 py-1 rounded bg-red-500/10 text-red-400 border border-red-500/20">
                    Failed 24h: {metrics.failed_24h || 0}
                  </span>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin space-y-3">
                {tasks.length === 0 && (
                  <div className="h-full flex items-center justify-center flex-col gap-3 opacity-40">
                    <Play className="w-10 h-10" />
                    <p className="text-sm font-mono uppercase tracking-widest">{t('pipeline.awaiting_signal')}</p>
                  </div>
                )}
                {tasks.map((task: any) => (
                  <div key={task.task_id} className="bg-bg-card border border-border-main rounded-xl p-4 hover:border-aws-orange/30 transition-all">
                    <div className="flex justify-between items-start mb-2">
                      <div className="flex items-center gap-2">
                        {task.status === 'running' || task.status === 'IN_PROGRESS' ? (
                          <div className="w-2 h-2 rounded-full bg-aws-orange animate-pulse" />
                        ) : task.status === 'completed' || task.status === 'COMPLETED' ? (
                          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                        ) : task.status === 'completed_no_delivery' ? (
                          <AlertCircle className="w-4 h-4 text-amber-400" />
                        ) : task.status === 'failed' || task.status === 'FAILED' ? (
                          <AlertCircle className="w-4 h-4 text-red-400" />
                        ) : (
                          <Clock className="w-4 h-4 text-slate-500" />
                        )}
                        <span className="text-xs font-bold text-dynamic">{task.title}</span>
                      </div>
                      <span className={`text-[9px] font-mono font-bold uppercase px-2 py-0.5 rounded ${
                        task.pr_url ? 'bg-emerald-500/20 text-emerald-400' :
                        task.status === 'running' || task.status === 'IN_PROGRESS' ? 'bg-aws-orange/20 text-aws-orange' :
                        task.status === 'completed' || task.status === 'COMPLETED' ? 'bg-emerald-500/20 text-emerald-400' :
                        task.status === 'completed_no_delivery' || task.pr_error ? 'bg-amber-500/20 text-amber-400' :
                        task.status === 'failed' || task.status === 'FAILED' ? 'bg-red-500/20 text-red-400' :
                        'bg-slate-500/20 text-slate-400'
                      }`}>{
                        task.pr_url ? 'PR Delivered' :
                        task.status === 'completed_no_delivery' ? 'Delivery Failed' :
                        task.pr_error ? 'Push Failed' :
                        task.status === 'running' || task.status === 'IN_PROGRESS' ? (task.current_stage || 'running') :
                        task.status === 'completed' || task.status === 'COMPLETED' ? 'Complete' :
                        (task.current_stage || task.status)
                      }</span>
                    </div>
                    <div className="flex items-center gap-4 text-[10px] text-secondary-dynamic font-mono">
                      <span className="flex items-center gap-1">
                        <GitBranch className="w-3 h-3" /> {task.repo || 'unknown'}
                      </span>
                      <span>{task.task_id}</span>
                      {task.pr_url && (
                        <a href={task.pr_url} target="_blank" rel="noopener noreferrer" className="text-aws-orange hover:underline">PR</a>
                      )}
                      {task.pr_error && !task.pr_url && (
                        <span className="text-amber-400" title={task.pr_error}>⚠️ Push failed</span>
                      )}
                      {task.issue_url && (
                        <a href={task.issue_url} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">Issue</a>
                      )}
                    </div>
                    {task.stage_progress && (
                      <div className="mt-2">
                        <div className="h-1 bg-white/5 rounded-full overflow-hidden">
                          <div className="h-full bg-aws-orange rounded-full transition-all" style={{ width: `${task.stage_progress.percent || 0}%` }} />
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeView === 'agents' && (
            <div className="flex-1 flex flex-col overflow-hidden">
              <AgentSidebar agents={agents} />
            </div>
          )}

          {activeView === 'reasoning' && (
            <div className="flex-1 flex flex-col overflow-hidden">
              <Terminal logs={logs} />
            </div>
          )}

          {activeView === 'gates' && (
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="flex justify-between items-center mb-6">
                <div>
                  <h2 className="text-xl font-medium text-dynamic">Quality Gates</h2>
                  <p className="text-xs text-secondary-dynamic font-mono">Pipeline Gate Results (Real-Time)</p>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin space-y-3">
                {tasks.filter((t: any) => t.events?.some((e: any) => e.type === 'gate')).length === 0 && (
                  <div className="h-full flex items-center justify-center flex-col gap-3 opacity-40">
                    <ShieldCheck className="w-10 h-10" />
                    <p className="text-sm font-mono uppercase tracking-widest">Awaiting Gate Events</p>
                    <p className="text-[10px] text-secondary-dynamic">Gates fire during task execution (DoR, Concurrency, Adversarial, Ship Readiness)</p>
                  </div>
                )}
                {tasks.filter((t: any) => t.events?.some((e: any) => e.type === 'gate')).map((task: any) => (
                  <div key={task.task_id} className="bg-bg-card border border-border-main rounded-xl p-4">
                    <div className="flex justify-between items-center mb-3">
                      <span className="text-xs font-bold text-dynamic">{task.title}</span>
                      <span className="text-[9px] font-mono text-secondary-dynamic">{task.task_id}</span>
                    </div>
                    <div className="space-y-2">
                      {task.events.filter((e: any) => e.type === 'gate').map((gate: any, idx: number) => (
                        <div key={idx} className={`flex items-center gap-3 p-2 rounded-lg border ${
                          gate.gate_result === 'pass' ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-red-500/5 border-red-500/20'
                        }`}>
                          {gate.gate_result === 'pass' ? (
                            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                          ) : (
                            <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
                          )}
                          <div className="flex-1 min-w-0">
                            <span className="text-[10px] font-bold text-dynamic">{gate.gate_name || 'gate'}</span>
                            <p className="text-[9px] text-secondary-dynamic truncate">{gate.msg}</p>
                          </div>
                          <span className={`text-[9px] font-mono font-bold uppercase ${
                            gate.gate_result === 'pass' ? 'text-emerald-400' : 'text-red-400'
                          }`}>{gate.gate_result}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeView === 'health' && (
            <div className="flex-1 grid grid-cols-2 gap-4 overflow-hidden">
              <MetricsCard data={factoryData?.dora || factoryData?.metrics} />
              <ComponentHealthCard status={apiStatus} />
            </div>
          )}

          {activeView === 'registries' && (
            <div className="flex-1 flex flex-col overflow-hidden">
              <RegistriesCard />
            </div>
          )}

          {activeView === 'observability' && (
            <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
              <PersonaRouter onPersonaChange={(p) => setActivePersona(p)}>
                <PersonaFilteredCards
                  persona={activePersona}
                  factoryData={factoryData}
                />
              </PersonaRouter>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
