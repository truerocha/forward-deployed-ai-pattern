import React from 'react';
import { CheckCircle2, AlertCircle, ExternalLink } from 'lucide-react';
import factoryConfig from '../factory-config.json';
import { useTranslation } from 'react-i18next';

interface ServiceStatus {
  name: string;
  endpoint: string;
  status: 'active' | 'degraded' | 'maintenance';
}

interface ComponentHealthCardProps {
  status?: any;
}

export const ComponentHealthCard: React.FC<ComponentHealthCardProps> = ({ status }) => {
  const { t } = useTranslation();
  const services: ServiceStatus[] = status?.checks ? status.checks.map((c: any) => ({
    name: c.name?.replace(/_/g, ' ').replace(/\b\w/g, (l: string) => l.toUpperCase()) || 'Unknown',
    endpoint: c.detail || 'Internal',
    status: c.status === 'pass' ? 'active' : c.status === 'warn' ? 'degraded' : c.status === 'fail' ? 'maintenance' : 'active'
  })) : [
    { name: 'Awaiting Health Check', endpoint: 'GET /status/health', status: 'maintenance' as const },
  ];

  return (
    <div className="h-full bento-card flex flex-col overflow-hidden transition-colors duration-300">
      <div className="mb-6 flex justify-between items-center">
        <div>
          <h2 className="text-sm font-bold text-secondary-dynamic uppercase tracking-widest mb-1">{t('health.title')}</h2>
          <p className="text-[10px] text-slate-500 font-mono">{t('health.subtitle')}</p>
        </div>
        {status && (
          <div className="px-2 py-1 rounded bg-emerald-500/10 border border-emerald-500/20 text-[10px] text-emerald-400 font-mono font-bold">
            {t('health.resynced')}
          </div>
        )}
      </div>
      
      <div className="flex-1 overflow-y-auto space-y-3 pr-2 scrollbar-thin">
        {services.map((service, idx) => (
          <div key={idx} className="bg-black/5 dark:bg-black/30 border border-border-main rounded-xl p-3 flex items-center justify-between group hover:border-aws-orange/30 transition-all">
            <div className="flex items-center gap-3">
              <div 
                className={`p-1.5 rounded-lg ${
                  service.status === 'active' ? 'bg-emerald-500/10 text-emerald-400' : 
                  service.status === 'degraded' ? 'bg-amber-500/10 text-amber-400' : 'bg-red-500/10 text-red-400'
                }`}
                aria-label={`Status: ${t(`health.${service.status}`)}`}
              >
                {service.status === 'active' ? <CheckCircle2 className="w-4 h-4" aria-hidden="true" /> : <AlertCircle className="w-4 h-4" aria-hidden="true" />}
              </div>
              <div>
                <p className="text-xs font-bold text-dynamic mb-0.5">{service.name}</p>
                <div className="flex items-center gap-1.5">
                  <span className="text-[9px] text-secondary-dynamic font-mono truncate max-w-[150px]">{service.endpoint}</span>
                  <ExternalLink className="w-2.5 h-2.5 text-slate-600 transition-colors" aria-hidden="true" />
                </div>
              </div>
            </div>
            <div className="text-right" aria-hidden="true">
              <span className={`text-[9px] font-bold uppercase tracking-tighter ${
                service.status === 'active' ? 'text-emerald-400' : 
                service.status === 'degraded' ? 'text-amber-400' : 'text-red-400'
              }`}>
                {t(`health.${service.status}`)}
              </span>
              <div className="w-12 h-1 bg-white/5 rounded-full mt-1 overflow-hidden">
                <div className={`h-full ${service.status === 'active' ? 'bg-emerald-500' : 'bg-amber-500'} w-full`}></div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
