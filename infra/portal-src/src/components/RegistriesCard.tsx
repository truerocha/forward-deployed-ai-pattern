import React, { useEffect, useState } from 'react';
import { Database, Box, FileText, Cpu, CheckCircle2, RefreshCw, AlertCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface RegistryItem {
  category: string;
  items: {
    name: string;
    version: string;
    status: 'ready' | 'stable' | 'deprecated' | 'degraded';
    details: string;
  }[];
  icon: any;
}

interface RegistriesApiResponse {
  models: { name: string; model_id: string; tier: string; usage: string; status: string }[];
  infrastructure: { name: string; version: string; status: string; details: string }[];
  data_plane: { name: string; version: string; status: string; details: string }[];
  squad_agents: { name: string; version: string; status: string; details: string }[];
  orchestration: { name: string; version: string; status: string; details: string }[];
  region: string;
  environment: string;
  timestamp: string;
}

export const RegistriesCard: React.FC = () => {
  const { t } = useTranslation();
  const [registries, setRegistries] = useState<RegistryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<string>('');
  const [error, setError] = useState<string>('');

  const API_URL = document.querySelector('meta[name="factory-api-url"]')?.getAttribute('content') || '';

  useEffect(() => {
    const fetchRegistries = async () => {
      if (!API_URL) {
        setError('No API URL configured');
        setLoading(false);
        return;
      }

      try {
        const res = await fetch(`${API_URL}/status/registries`, {
          headers: { Accept: 'application/json' },
        });

        if (!res.ok) {
          setError(`API returned ${res.status}`);
          setLoading(false);
          return;
        }

        const data: RegistriesApiResponse = await res.json();
        const items: RegistryItem[] = [];

        // Squad Agents — discovered from live task events
        if (data.squad_agents && data.squad_agents.length > 0) {
          items.push({
            category: `Squad Agents (${data.squad_agents.length})`,
            icon: Cpu,
            items: data.squad_agents.map((a) => ({
              name: a.name,
              version: a.version,
              status: (a.status as any) || 'stable',
              details: a.details,
            })),
          });
        }

        // Models — read from live ECS task definition env vars
        if (data.models && data.models.length > 0) {
          items.push({
            category: `Models (${data.models.length})`,
            icon: Database,
            items: data.models.map((m) => ({
              name: m.name,
              version: m.tier,
              status: (m.status as any) || 'ready',
              details: `${m.usage} / ${m.model_id.split('.').pop()?.split('-v')[0] || ''}`,
            })),
          });
        }

        // Infrastructure — from ECS task definitions
        if (data.infrastructure && data.infrastructure.length > 0) {
          items.push({
            category: 'Infrastructure',
            icon: Box,
            items: data.infrastructure.map((i) => ({
              name: i.name,
              version: i.version,
              status: (i.status as any) || 'ready',
              details: i.details,
            })),
          });
        }

        // Data Plane — live DynamoDB table status
        if (data.data_plane && data.data_plane.length > 0) {
          items.push({
            category: `Data Plane (${data.data_plane.length} tables)`,
            icon: Database,
            items: data.data_plane.map((d) => ({
              name: d.name,
              version: d.version,
              status: (d.status as any) || 'ready',
              details: d.details,
            })),
          });
        }

        // Orchestration — EventBridge rules
        if (data.orchestration && data.orchestration.length > 0) {
          items.push({
            category: 'Orchestration',
            icon: FileText,
            items: data.orchestration.map((o) => ({
              name: o.name,
              version: o.version,
              status: (o.status as any) || 'ready',
              details: o.details,
            })),
          });
        }

        setRegistries(items);
        setLastUpdated(data.timestamp ? new Date(data.timestamp).toLocaleTimeString() : '');
        setError('');
      } catch (err) {
        setError('Failed to fetch registries');
      } finally {
        setLoading(false);
      }
    };

    fetchRegistries();
    // Refresh every 60 seconds
    const interval = setInterval(fetchRegistries, 60000);
    return () => clearInterval(interval);
  }, [API_URL]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <RefreshCw className="w-6 h-6 animate-spin text-aws-orange" />
      </div>
    );
  }

  if (error && registries.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3">
        <AlertCircle className="w-8 h-8 text-red-400" />
        <p className="text-sm text-red-400 font-mono">{error}</p>
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
        {lastUpdated && (
          <span className="text-[9px] font-mono text-secondary-dynamic">
            Live data · Updated {lastUpdated}
          </span>
        )}
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
                        {item.status === 'degraded' ? (
                          <>
                            <AlertCircle className="w-3 h-3 text-amber-500" />
                            <span className="text-[9px] font-bold text-amber-500 uppercase">{item.status}</span>
                          </>
                        ) : (
                          <>
                            <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                            <span className="text-[9px] font-bold text-emerald-500 uppercase">{item.status}</span>
                          </>
                        )}
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
