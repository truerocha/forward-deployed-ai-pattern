/**
 * App.tsx — Cloudscape Design System Shell
 *
 * Replaces the custom Tailwind rail navigation with Cloudscape's
 * AppLayout + TopNavigation + SideNavigation pattern.
 *
 * Preserves: data layer, i18n, persona routing, all card components.
 * Changes: layout structure, navigation, theming approach.
 */
import React, { useState, useCallback, useRef, useEffect } from 'react';

import AppLayout from '@cloudscape-design/components/app-layout';
import TopNavigation from '@cloudscape-design/components/top-navigation';
import SideNavigation, { SideNavigationProps } from '@cloudscape-design/components/side-navigation';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Badge from '@cloudscape-design/components/badge';
import { I18nProvider } from '@cloudscape-design/components/i18n';
import enMessages from '@cloudscape-design/components/i18n/messages/all.en.json';

import '@cloudscape-design/global-styles/index.css';

import { Agent, LogEntry, AppView } from './types';
import { useTranslation } from 'react-i18next';
import factoryConfig from './factory-config.json';

// Views
import { PipelineView } from './views/PipelineView';
import { AgentsView } from './views/AgentsView';
import { ReasoningView } from './views/ReasoningView';
import { GatesView } from './views/GatesView';
import { HealthView } from './views/HealthView';
import { RegistriesView } from './views/RegistriesView';
import { ObservabilityView } from './views/ObservabilityView';

export default function App() {
  const { t, i18n } = useTranslation();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [activeView, setActiveView] = useState<AppView>('pipeline');
  const [darkMode, setDarkMode] = useState<boolean>(() => {
    const stored = typeof window !== 'undefined' ? localStorage.getItem('fde-theme') : null;
    if (stored === 'light') return false;
    if (stored === 'dark') return true;
    if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: light)').matches) return false;
    return true;
  });
  const [apiStatus, setApiStatus] = useState<any>(null);
  const [factoryData, setFactoryData] = useState<any>(null);
  const [activePersona, setActivePersona] = useState<string>('SWE');
  const [navigationOpen, setNavigationOpen] = useState(true);

  const isTabActive = useRef(true);
  const API_URL = document.querySelector('meta[name="factory-api-url"]')?.getAttribute('content') || '';

  // ─── Dark Mode ─────────────────────────────────────────────────────────────
  useEffect(() => {
    if (darkMode) {
      document.body.classList.add('awsui-dark-mode');
      localStorage.setItem('fde-theme', 'dark');
    } else {
      document.body.classList.remove('awsui-dark-mode');
      localStorage.setItem('fde-theme', 'light');
    }
  }, [darkMode]);

  // ─── Data Fetching ─────────────────────────────────────────────────────────
  const fetchHealth = useCallback(async () => {
    if (!API_URL) return;
    try {
      const res = await fetch(`${API_URL}/status/health`);
      if (res.ok) setApiStatus(await res.json());
    } catch (err) {
      console.error('Failed to fetch factory health:', err);
    }
  }, [API_URL]);

  const fetchFactoryData = useCallback(async () => {
    if (!API_URL) return;
    try {
      const res = await fetch(`${API_URL}/status/tasks`);
      if (res.ok) {
        const data = await res.json();
        setFactoryData(data);

        if (data.agents && data.agents.length > 0) {
          const { mapAgentsWithConductorPlan } = await import('./mappers/factoryDataMapper');
          setAgents(mapAgentsWithConductorPlan(data));
        }

        if (data.tasks && data.tasks.length > 0) {
          const apiLogs: LogEntry[] = [];
          const sortedTasks = [...data.tasks].sort((a: any, b: any) =>
            (b.updated_at || '').localeCompare(a.updated_at || '')
          );
          const activeTasks = sortedTasks
            .filter((t: any) => t.status === 'running' || t.events?.length > 0)
            .slice(0, 3);

          for (const task of activeTasks) {
            if (task.events && task.events.length > 0) {
              for (const ev of task.events) {
                let agentName = 'System';
                if (ev.phase && ev.phase !== 'intake' && ev.phase !== 'workspace') {
                  agentName = ev.phase;
                } else if (ev.msg?.includes('Squad agent:')) {
                  const match = ev.msg.match(/Squad agent: (.+)/);
                  if (match) agentName = match[1];
                } else if (task.agent?.name) {
                  agentName = task.agent.name;
                }

                apiLogs.push({
                  id: `${task.task_id}-${ev.ts}-${apiLogs.length}`,
                  timestamp: ev.ts ? new Date(ev.ts).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '',
                  agentId: task.task_id,
                  agentName,
                  message: `[${task.task_id.slice(-8)}] ${ev.msg || ''}`,
                  type: ev.type === 'gate' ? (ev.gate_result === 'pass' ? 'action' : 'error') :
                        ev.type === 'error' ? 'error' :
                        ev.type === 'agent' ? 'working' :
                        ev.type === 'tool' ? 'thought' : 'system',
                  _sortKey: ev.ts || '',
                });
              }
            }
          }
          apiLogs.sort((a: any, b: any) => (b._sortKey || '').localeCompare(a._sortKey || ''));
          setLogs(apiLogs);
        }
      }
    } catch (err) {
      console.error('Failed to fetch factory data:', err);
    }
  }, [API_URL]);

  // ─── Lifecycle ─────────────────────────────────────────────────────────────
  useEffect(() => { fetchHealth(); fetchFactoryData(); }, [fetchHealth, fetchFactoryData]);

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

  useEffect(() => {
    let pollingInterval: NodeJS.Timeout;
    const startPolling = () => {
      pollingInterval = setInterval(() => { fetchHealth(); fetchFactoryData(); }, 5000);
    };
    const handleVisibility = () => {
      isTabActive.current = !document.hidden;
      if (document.hidden) clearInterval(pollingInterval);
      else startPolling();
    };
    document.addEventListener('visibilitychange', handleVisibility);
    startPolling();
    return () => { document.removeEventListener('visibilitychange', handleVisibility); clearInterval(pollingInterval); };
  }, [fetchHealth, fetchFactoryData]);

  // ─── Navigation ────────────────────────────────────────────────────────────
  const changeView = (view: AppView) => {
    window.location.hash = view;
    setActiveView(view);
  };

  const metrics = factoryData?.metrics || {};
  const tasks = factoryData?.tasks || [];
  const isProcessing = metrics.active > 0;

  const navItems: SideNavigationProps.Item[] = [
    { type: 'link', text: t('nav.flow'), href: '#pipeline' },
    { type: 'link', text: t('nav.units'), href: '#agents' },
    { type: 'link', text: t('nav.reason'), href: '#reasoning' },
    { type: 'link', text: t('nav.gates'), href: '#gates' },
    { type: 'link', text: t('nav.health'), href: '#health' },
    { type: 'link', text: t('nav.catalog'), href: '#registries' },
    { type: 'divider' },
    { type: 'link', text: 'Observability', href: '#observability', info: <Badge color="blue">METRICS</Badge> },
  ];

  const handleNavFollow = (event: CustomEvent<SideNavigationProps.FollowDetail>) => {
    event.preventDefault();
    const href = event.detail.href || '';
    const view = href.replace('#', '') as AppView;
    if (['pipeline', 'agents', 'reasoning', 'gates', 'health', 'registries', 'observability'].includes(view)) {
      changeView(view);
    }
  };

  // ─── Language Cycling ──────────────────────────────────────────────────────
  const cycleLanguage = () => {
    const langs = ['en-US', 'pt-BR', 'es'];
    const currentIndex = langs.indexOf(i18n.language);
    const nextIndex = (currentIndex + 1) % langs.length;
    i18n.changeLanguage(langs[nextIndex]);
  };

  // ─── View Content ──────────────────────────────────────────────────────────
  const renderContent = () => {
    switch (activeView) {
      case 'pipeline':
        return <PipelineView tasks={tasks} metrics={metrics} />;
      case 'agents':
        return <AgentsView agents={agents} />;
      case 'reasoning':
        return <ReasoningView logs={logs} />;
      case 'gates':
        return <GatesView tasks={tasks} />;
      case 'health':
        return <HealthView factoryData={factoryData} apiStatus={apiStatus} />;
      case 'registries':
        return <RegistriesView />;
      case 'observability':
        return (
          <ObservabilityView
            activePersona={activePersona}
            onPersonaChange={setActivePersona}
            factoryData={factoryData}
          />
        );
      default:
        return <PipelineView tasks={tasks} metrics={metrics} />;
    }
  };

  // ─── Breadcrumbs ───────────────────────────────────────────────────────────
  const viewLabels: Record<AppView, string> = {
    pipeline: t('nav.flow'),
    agents: t('nav.units'),
    reasoning: t('nav.reason'),
    gates: t('nav.gates'),
    health: t('nav.health'),
    registries: t('nav.catalog'),
    observability: 'Observability',
  };

  return (
    <I18nProvider locale="en" messages={[enMessages]}>
      <div id="top-nav">
        <TopNavigation
          identity={{
            href: '#pipeline',
            title: `CODE_FACTORY`,
            logo: { src: darkMode ? '/img/factory-logo-dark.svg' : '/img/factory-logo-light.svg', alt: 'Code Factory' },
          }}
          utilities={[
            {
              type: 'button',
              text: isProcessing ? t('pipeline.processing') : t('pipeline.nominal'),
              iconName: isProcessing ? 'status-in-progress' : 'status-positive',
              disableUtilityCollapse: true,
            },
            {
              type: 'button',
              text: `${factoryConfig.region} / ${factoryConfig.environment}`,
              iconName: 'status-info',
            },
            {
              type: 'button',
              text: i18n.language === 'en-US' ? 'EN' : i18n.language === 'pt-BR' ? 'PT' : 'ES',
              iconName: 'gen-ai',
              onClick: cycleLanguage,
            },
            {
              type: 'button',
              iconName: darkMode ? 'thumbs-up' : 'thumbs-down',
              text: darkMode ? 'Dark' : 'Light',
              onClick: () => setDarkMode(!darkMode),
            },
          ]}
          i18nStrings={{
            searchIconAriaLabel: 'Search',
            searchDismissIconAriaLabel: 'Close search',
            overflowMenuTriggerText: 'More',
            overflowMenuTitleText: 'All',
            overflowMenuBackIconAriaLabel: 'Back',
            overflowMenuDismissIconAriaLabel: 'Close menu',
          }}
        />
      </div>
      <AppLayout
        navigation={
          <SideNavigation
            header={{ text: t('app.title'), href: '#pipeline' }}
            activeHref={`#${activeView}`}
            items={navItems}
            onFollow={handleNavFollow}
          />
        }
        navigationOpen={navigationOpen}
        onNavigationChange={({ detail }) => setNavigationOpen(detail.open)}
        breadcrumbs={
          <BreadcrumbGroup
            items={[
              { text: t('app.title'), href: '#pipeline' },
              { text: viewLabels[activeView], href: `#${activeView}` },
            ]}
          />
        }
        content={renderContent()}
        toolsHide={true}
        headerSelector="#top-nav"
        ariaLabels={{
          navigation: 'Side navigation',
          navigationToggle: 'Open navigation',
          navigationClose: 'Close navigation',
        }}
      />
    </I18nProvider>
  );
}
