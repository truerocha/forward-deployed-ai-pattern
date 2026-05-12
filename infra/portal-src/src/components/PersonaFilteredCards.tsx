/**
 * PersonaFilteredCards — Renders only the cards relevant to the active persona.
 *
 * Implements PEC Blueprint Chapter 12 (Filtragem Cognitiva e UX por Persona):
 *   "Visões específicas para Staff Engineer (Código), SRE (Estabilidade) e TPM (FinOps)."
 *
 * Each persona sees a curated subset of cards, reducing cognitive load and
 * ensuring the right information reaches the right role at the right time.
 */

import React from 'react';
import { DoraCard } from './DoraCard';
import { CostCard } from './CostCard';
import { ValueStreamCard } from './ValueStreamCard';
import { MaturityRadar } from './MaturityRadar';
import { BrainSimCard } from './BrainSimCard';
import { TrustCard } from './TrustCard';
import { NetFrictionCard } from './NetFrictionCard';
import { GateFeedbackCard } from './GateFeedbackCard';
import { GateHistoryCard } from './GateHistoryCard';
import { DataQualityCard } from './DataQualityCard';
import { SquadExecutionCard } from './SquadExecutionCard';
import { LiveTimeline } from './LiveTimeline';
import { HumanInputCard } from './HumanInputCard';
import { BranchEvaluationCard } from './BranchEvaluationCard';
import { ConductorPlanCard } from './ConductorPlanCard';
import { DoraSunCard } from './DoraSunCard';
import {
  mapDoraMetrics,
  mapCostMetrics,
  mapGateHistory,
  mapLiveTimeline,
  mapSquadExecution,
} from '../mappers/factoryDataMapper';

/** Persona card visibility matrix — single source of truth for role-based filtering. */
const PERSONA_CARDS: Record<string, string[]> = {
  PM: ['DoraSunCard', 'ValueStreamCard', 'DoraCard', 'CostCard', 'TrustCard', 'NetFrictionCard'],
  SWE: ['LiveTimeline', 'GateFeedbackCard', 'SquadExecutionCard', 'BranchEvaluationCard', 'HumanInputCard', 'ConductorPlanCard'],
  SRE: ['DoraSunCard', 'DataQualityCard', 'GateHistoryCard', 'DoraCard', 'CostCard'],
  Architect: ['MaturityRadar', 'BrainSimCard', 'ConductorPlanCard', 'ValueStreamCard', 'DataQualityCard', 'NetFrictionCard'],
  Staff: ['DoraSunCard', 'DoraCard', 'MaturityRadar', 'TrustCard', 'CostCard', 'BrainSimCard', 'ValueStreamCard', 'SquadExecutionCard'],
};

interface PersonaFilteredCardsProps {
  persona: string;
  factoryData: any;
}

export const PersonaFilteredCards: React.FC<PersonaFilteredCardsProps> = ({
  persona,
  factoryData,
}) => {
  const visibleCards = PERSONA_CARDS[persona] || PERSONA_CARDS['SWE'];

  const cardRegistry: Record<string, React.ReactNode> = {
    DoraSunCard: <DoraSunCard forecast={factoryData?.forecast} />,
    DoraCard: <DoraCard metrics={mapDoraMetrics(factoryData)} />,
    CostCard: <CostCard summary={mapCostMetrics(factoryData)} />,
    ValueStreamCard: <ValueStreamCard />,
    MaturityRadar: <MaturityRadar />,
    BrainSimCard: <BrainSimCard />,
    TrustCard: <TrustCard />,
    NetFrictionCard: <NetFrictionCard />,
    GateFeedbackCard: <GateFeedbackCard />,
    GateHistoryCard: <GateHistoryCard history={mapGateHistory(factoryData)} />,
    DataQualityCard: <DataQualityCard />,
    SquadExecutionCard: <SquadExecutionCard agents={mapSquadExecution(factoryData)} />,
    LiveTimeline: <LiveTimeline events={mapLiveTimeline(factoryData)} wsConnected={!!factoryData} />,
    HumanInputCard: <HumanInputCard onRespond={() => {}} />,
    BranchEvaluationCard: <BranchEvaluationCard />,
    ConductorPlanCard: <ConductorPlanCard />,
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 pb-4 flex-1 min-h-0 overflow-y-auto auto-rows-[minmax(200px,1fr)]">
      {visibleCards.map((cardName) => {
        const card = cardRegistry[cardName];
        if (!card) return null;
        return (
          <div key={cardName} className="overflow-hidden">
            {card}
          </div>
        );
      })}
    </div>
  );
};
