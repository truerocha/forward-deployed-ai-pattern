import React, { useState } from 'react';
import { User, Code, Server, Compass, Star, LayoutGrid } from 'lucide-react';

type Persona = 'PM' | 'SWE' | 'SRE' | 'Architect' | 'Staff';

interface PersonaRouterProps {
  persona?: Persona;
  onPersonaChange?: (persona: Persona) => void;
  children?: React.ReactNode;
}

interface PersonaConfig {
  label: string;
  icon: React.FC<{ className?: string; 'aria-hidden'?: string }>;
  color: string;
  bg: string;
  border: string;
  description: string;
  cards: string[];
}

const PERSONA_CONFIG: Record<Persona, PersonaConfig> = {
  PM: {
    label: 'Product Manager',
    icon: User,
    color: 'text-purple-400',
    bg: 'bg-purple-500/10',
    border: 'border-purple-500/20',
    description: 'Value stream, DORA metrics, cost tracking',
    cards: ['ValueStreamCard', 'DoraCard', 'CostCard', 'TrustCard', 'NetFrictionCard'],
  },
  SWE: {
    label: 'Software Engineer',
    icon: Code,
    color: 'text-sky-400',
    bg: 'bg-sky-500/10',
    border: 'border-sky-500/20',
    description: 'Live timeline, gate feedback, squad execution',
    cards: ['LiveTimeline', 'GateFeedbackCard', 'SquadExecutionCard', 'BranchEvaluationCard', 'HumanInputCard'],
  },
  SRE: {
    label: 'Site Reliability Engineer',
    icon: Server,
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/20',
    description: 'Data quality, metrics, gate history',
    cards: ['DataQualityCard', 'MetricsCard', 'GateHistoryCard', 'DoraCard', 'CostCard'],
  },
  Architect: {
    label: 'Architect',
    icon: Compass,
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/20',
    description: 'Maturity radar, brain simulation, value stream',
    cards: ['MaturityRadar', 'BrainSimCard', 'ValueStreamCard', 'DataQualityCard', 'NetFrictionCard'],
  },
  Staff: {
    label: 'Staff Engineer',
    icon: Star,
    color: 'text-aws-orange',
    bg: 'bg-aws-orange/10',
    border: 'border-aws-orange/20',
    description: 'Full observability across all dimensions',
    cards: ['DoraCard', 'MaturityRadar', 'TrustCard', 'CostCard', 'BrainSimCard', 'ValueStreamCard'],
  },
};

const PERSONAS: Persona[] = ['PM', 'SWE', 'SRE', 'Architect', 'Staff'];

export const PersonaRouter: React.FC<PersonaRouterProps> = ({
  persona: controlledPersona,
  onPersonaChange,
  children,
}) => {
  const [internalPersona, setInternalPersona] = useState<Persona>('SWE');
  const activePersona = controlledPersona || internalPersona;

  const handlePersonaChange = (p: Persona) => {
    setInternalPersona(p);
    onPersonaChange?.(p);
  };

  const config = PERSONA_CONFIG[activePersona];

  return (
    <div className="flex flex-col h-full">
      {/* Persona tab navigation */}
      <div className="flex items-center gap-1 p-1 mb-4 rounded-lg bg-black/5 dark:bg-white/5 overflow-x-auto">
        {PERSONAS.map((p) => {
          const pConfig = PERSONA_CONFIG[p];
          const Icon = pConfig.icon;
          const isActive = activePersona === p;

          return (
            <button
              key={p}
              onClick={() => handlePersonaChange(p)}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all whitespace-nowrap ${
                isActive
                  ? `${pConfig.bg} ${pConfig.color} border ${pConfig.border}`
                  : 'text-secondary-dynamic hover:text-dynamic border border-transparent'
              }`}
              aria-pressed={isActive}
            >
              <Icon className="w-3.5 h-3.5" aria-hidden="true" />
              <span className="hidden sm:inline">{p}</span>
            </button>
          );
        })}
      </div>

      {/* Active persona info */}
      <div className={`flex items-center gap-3 px-3 py-2 rounded-lg ${config.bg} border ${config.border} mb-4`}>
        <LayoutGrid className={`w-4 h-4 ${config.color}`} aria-hidden="true" />
        <div>
          <p className={`text-[10px] font-bold uppercase ${config.color}`}>{config.label} View</p>
          <p className="text-[9px] text-secondary-dynamic">{config.description}</p>
        </div>
        <div className="ml-auto flex gap-1">
          {config.cards.slice(0, 3).map((card) => (
            <div
              key={card}
              className="w-4 h-4 rounded bg-black/5 dark:bg-white/5 border border-border-main"
              title={card}
            />
          ))}
          {config.cards.length > 3 && (
            <span className="text-[8px] text-secondary-dynamic font-mono self-center">
              +{config.cards.length - 3}
            </span>
          )}
        </div>
      </div>

      {/* Routed content */}
      <div className="flex-1 min-h-0 relative">
        {children}
      </div>
    </div>
  );
};
