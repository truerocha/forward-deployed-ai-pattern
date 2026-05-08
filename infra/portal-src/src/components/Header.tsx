import React from 'react';
import factoryConfig from '../factory-config.json';
import { useTranslation } from 'react-i18next';

interface HeaderProps {
  isProcessing: boolean;
}

export const Header: React.FC<HeaderProps> = ({ isProcessing }) => {
  const { t } = useTranslation();

  return (
    <header className="flex items-center justify-between mb-8 pb-4 shrink-0 transition-colors duration-300">
      <div className="flex items-center gap-3">
        <img src="/img/AWS_ProServe_logo_v2.svg" alt="AWS Professional Services" className="h-10 w-auto hidden lg:block" />
        <div className="h-8 w-[1px] bg-border-main hidden lg:block"></div>
        <h1 className="text-2xl font-bold tracking-tight text-dynamic">
          CODE_<span className="text-aws-orange">FACTORY</span> 
          <span className="text-slate-500 font-light mx-3">/</span> 
          <span className="text-xs uppercase tracking-[0.2em] text-secondary-dynamic font-bold">{t('app.title')}</span>
        </h1>
      </div>
      <div className="flex gap-6 items-center">
        <div className="flex flex-col items-end">
          <div className="flex items-center gap-2" aria-label={`System Status: ${isProcessing ? t('pipeline.processing') : t('pipeline.nominal')}`}>
            <span className={`w-2 h-2 rounded-full ${isProcessing ? 'bg-aws-orange animate-pulse shadow-[0_0_8px_#FF9900]' : 'bg-emerald-400 shadow-[0_0_8px_#10b981]'}`} aria-hidden="true"></span>
            <span className="text-[10px] uppercase text-dynamic font-bold tracking-widest">{isProcessing ? t('pipeline.processing') : t('pipeline.nominal')}</span>
          </div>
          <span className="text-[10px] text-secondary-dynamic uppercase tracking-widest font-bold">{t('nav.health')}</span>
        </div>
        <div className="h-8 w-[1px] bg-border-main"></div>
        <div className="hidden lg:flex flex-col items-end">
          <span className="text-sm font-bold text-aws-orange font-mono">us-east-1 / {factoryConfig.environment}</span>
          <span className="text-[10px] text-secondary-dynamic uppercase font-bold">{t('app.context')}</span>
        </div>
      </div>
    </header>
  );
};
