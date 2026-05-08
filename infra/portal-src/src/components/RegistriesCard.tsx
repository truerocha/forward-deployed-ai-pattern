import React, { useEffect, useState } from 'react';
import { Database, Box, FileText, Cpu, CheckCircle2, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface RegistryItem {
  category: string;
  items: {
    name: string;
    version: string;
    status: 'ready' | 'stable' | 'deprecated';
    details: string;
  }[];
  icon: any;
}

export const RegistriesCard: React.FC = () => {
  const { t } = useTranslation();
  const [registries, setRegistries] = useState<RegistryItem[]>([]);
  const [loading, setLoading] = useState(true);

  const API_URL = document.querySelector('meta[name="factory-api-url"]')?.getAttribute('content') || '';

  useEffect(() => {
    const buildRegistries = async () => {
      const items: RegistryItem[] = [];

      // Detect active squad agents from real task events
      let detectedAgents: string[] = [];
      if (API_URL) {
        try {
          const res = await fetch(`${API_URL}/status/tasks`);
          if (res.ok) {
            const data = await res.json();
            const agentSet = new Set<string>();
            for (const task of (data.tasks || [])) {
              for (const ev of (task.events || [])) {
                const match = ev.msg?.match(/Squad agent: (.+)/);
                if (match) agentSet.add(match[1]);
              }
            }
            detectedAgents = Array.from(agentSet);
          }
        } catch { /* fallback below */ }
      }

      // Squad Agents — from ADR-019 capability registry (20 agents)
      const allSquadAgents = [
        { name: 'task-intake-eval-agent', layer: 'Quarteto' },
        { name: 'architect-standard-agent', layer: 'Quarteto' },
        { name: 'reviewer-security-agent', layer: 'Quarteto' },
        { name: 'fde-code-reasoning', layer: 'Quarteto' },
        { name: 'code-ops-agent', layer: 'WAF/OPS' },
        { name: 'code-sec-agent', layer: 'WAF/SEC' },
        { name: 'code-rel-agent', layer: 'WAF/REL' },
        { name: 'code-perf-agent', layer: 'WAF/PERF' },
        { name: 'code-cost-agent', layer: 'WAF/COST' },
        { name: 'code-sus-agent', layer: 'WAF/SUS' },
        { name: 'swe-issue-code-reader-agent', layer: 'SWE' },
        { name: 'swe-code-context-agent', layer: 'SWE' },
        { name: 'swe-developer-agent', layer: 'SWE' },
        { name: 'swe-architect-agent', layer: 'SWE' },
        { name: 'swe-code-quality-agent', layer: 'SWE' },
        { name: 'swe-adversarial-agent', layer: 'SWE' },
        { name: 'swe-redteam-agent', layer: 'SWE' },
        { name: 'swe-tech-writer-agent', layer: 'Delivery' },
        { name: 'swe-dtl-commiter-agent', layer: 'Delivery' },
        { name: 'reporting-agent', layer: 'Reporting' },
      ];

      items.push({
        category: `Squad Agents (${allSquadAgents.length})`,
        icon: Cpu,
        items: allSquadAgents.map(a => ({
          name: a.name,
          version: 'v1',
          status: detectedAgents.includes(a.name) ? 'ready' : 'stable',
          details: a.layer,
        })),
      });

      items.push({
        category: 'Infrastructure',
        icon: Box,
        items: [
          { name: 'fde-dev-strands-agent', version: 'v8', status: 'ready', details: 'ECS Fargate / SQUAD_MODE=dynamic' },
          { name: 'fde-dev-squad-agent', version: 'v1', status: 'ready', details: 'ECS Fargate / Parametrized' },
          { name: 'fde-dev-orchestrator', version: 'v1', status: 'ready', details: 'ECS Fargate / 512MB dispatcher' },
          { name: 'fde-dev-fidelity-agent', version: 'v1', status: 'ready', details: 'ECS Fargate / Haiku fast-tier' },
          { name: 'adot-collector', version: 'v0.40', status: 'ready', details: 'Sidecar / X-Ray' },
          { name: 'fde-dev-agent-workspaces', version: 'v1', status: 'ready', details: 'EFS / General Purpose' },
          { name: 'dashboard-status', version: 'v2', status: 'ready', details: 'Lambda / API Gateway' },
          { name: 'ws-api', version: 'v1', status: 'ready', details: 'API Gateway WebSocket / HITL' },
        ]
      });

      items.push({
        category: 'Data Plane (DynamoDB)',
        icon: Database,
        items: [
          { name: 'fde-dev-scd', version: 'v1', status: 'ready', details: 'Shared Context Document / TTL 7d' },
          { name: 'fde-dev-context-hierarchy', version: 'v1', status: 'ready', details: 'Cross-session context / L1-L5' },
          { name: 'fde-dev-metrics', version: 'v1', status: 'ready', details: 'Unified metrics / DORA+Cost+VSM' },
          { name: 'fde-dev-memory', version: 'v1', status: 'ready', details: 'Structured memory / decisions' },
          { name: 'fde-dev-organism', version: 'v1', status: 'ready', details: 'Organism ladder / O1-O5' },
          { name: 'fde-dev-knowledge', version: 'v1', status: 'ready', details: 'Annotations + quality scores' },
          { name: 'fde-dev-task-queue', version: 'v1', status: 'ready', details: 'Task queue / DAG fan-out' },
          { name: 'fde-dev-prompt-registry', version: 'v1', status: 'ready', details: 'Prompt versioning' },
        ]
      });

      items.push({
        category: 'Orchestration',
        icon: FileText,
        items: [
          { name: 'github-factory-ready', version: 'EB-1', status: 'ready', details: 'EventBridge → ECS' },
          { name: 'webhook-ingest', version: 'v1', status: 'ready', details: 'Lambda → DynamoDB' },
          { name: 'dag-fanout', version: 'v1', status: 'ready', details: 'Stream → ECS' },
        ]
      });

      items.push({
        category: 'Models',
        icon: Database,
        items: [
          { name: 'Claude Sonnet 4.5', version: '2025-09', status: 'ready', details: 'Bedrock / us-east-1' },
        ]
      });

      setRegistries(items);
      setLoading(false);
    };

    buildRegistries();
  }, [API_URL]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <RefreshCw className="w-6 h-6 animate-spin text-aws-orange" />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden transition-colors duration-300">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-xl font-medium text-dynamic">{t('registries.title')}</h2>
          <p className="text-xs text-secondary-dynamic font-mono">{t('registries.subtitle')}</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {registries.map((reg, idx) => (
            <div key={idx} className="bento-card flex flex-col h-full">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2 rounded-xl bg-aws-orange/10 text-aws-orange">
                  <reg.icon className="w-5 h-5" />
                </div>
                <h3 className="text-sm font-bold text-dynamic uppercase tracking-widest">{reg.category}</h3>
              </div>
              
              <div className="space-y-3 flex-1 max-h-[300px] overflow-y-auto scrollbar-thin">
                {reg.items.map((item, iIdx) => (
                  <div key={iIdx} className="bg-black/5 dark:bg-black/30 border border-border-main rounded-xl p-3 group hover:border-aws-orange/30 transition-all">
                    <div className="flex justify-between items-start mb-1">
                      <span className="text-xs font-bold text-dynamic">{item.name}</span>
                      <span className="text-[9px] font-mono bg-aws-orange/20 text-aws-orange px-1.5 py-0.5 rounded uppercase">{item.version}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-[10px] text-secondary-dynamic font-mono">{item.details}</span>
                      <div className="flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                        <span className="text-[9px] font-bold text-emerald-500 uppercase">{item.status}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
