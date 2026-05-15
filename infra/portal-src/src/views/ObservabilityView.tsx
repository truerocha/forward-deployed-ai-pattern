/**
 * ObservabilityView — Persona-filtered cards using Cloudscape Tabs + Grid.
 */
import React from 'react';

import Tabs from '@cloudscape-design/components/tabs';
import Grid from '@cloudscape-design/components/grid';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';

import { DoraCard } from '../components/DoraCard';
import { CostCard } from '../components/CostCard';
import { ValueStreamCard } from '../components/ValueStreamCard';
import { MaturityRadar } from '../components/MaturityRadar';
import { BrainSimCard } from '../components/BrainSimCard';
import { TrustCard } from '../components/TrustCard';
import { NetFrictionCard } from '../components/NetFrictionCard';
import { GateFeedbackCard } from '../components/GateFeedbackCard';
import { GateHistoryCard } from '../components/GateHistoryCard';
import { DataQualityCard } from '../components/DataQualityCard';
import { SquadExecutionCard } from '../components/SquadExecutionCard';
import { LiveTimeline } from '../components/LiveTimeline';
import { HumanInputCard } from '../components/HumanInputCard';
import { BranchEvaluationCard } from '../components/BranchEvaluationCard';
import { ConductorPlanCard } from '../components/ConductorPlanCard';
import { DoraSunCard } from '../components/DoraSunCard';
import { ReviewFeedbackCard } from '../components/ReviewFeedbackCard';
import { CognitiveAutonomyCard } from '../components/CognitiveAutonomyCard';
import {
  mapDoraMetrics,
  mapCostMetrics,
  mapGateHistory,
  mapLiveTimeline,
  mapSquadExecution,
} from '../mappers/factoryDataMapper';

interface ObservabilityViewProps {
  activePersona: string;
  onPersonaChange: (persona: string) => void;
  factoryData: any;
}

/** Persona card visibility matrix */
const PERSONA_CARDS: Record<string, string[]> = {
  PM: ['DoraSunCard', 'ValueStreamCard', 'DoraCard', 'CostCard', 'TrustCard', 'NetFrictionCard', 'ReviewFeedbackCard', 'CognitiveAutonomyCard'],
  SWE: ['LiveTimeline', 'GateFeedbackCard', 'SquadExecutionCard', 'BranchEvaluationCard', 'HumanInputCard', 'ConductorPlanCard', 'ReviewFeedbackCard', 'CognitiveAutonomyCard'],
  SRE: ['DoraSunCard', 'DataQualityCard', 'GateHistoryCard', 'DoraCard', 'CostCard', 'ReviewFeedbackCard', 'CognitiveAutonomyCard'],
  Architect: ['MaturityRadar', 'BrainSimCard', 'ConductorPlanCard', 'ValueStreamCard', 'DataQualityCard', 'NetFrictionCard'],
  Staff: ['DoraSunCard', 'DoraCard', 'MaturityRadar', 'TrustCard', 'CostCard', 'BrainSimCard', 'ValueStreamCard', 'SquadExecutionCard', 'ReviewFeedbackCard', 'CognitiveAutonomyCard'],
};

export const ObservabilityView: React.FC<ObservabilityViewProps> = ({
  activePersona,
  onPersonaChange,
  factoryData,
}) => {
  const visibleCards = PERSONA_CARDS[activePersona] || PERSONA_CARDS['SWE'];

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
    ReviewFeedbackCard: <ReviewFeedbackCard />,
    CognitiveAutonomyCard: <CognitiveAutonomyCard />,
  };

  const renderCards = () => (
    <Grid
      gridDefinition={visibleCards.map(() => ({ colspan: { l: 6, m: 6, default: 12 } }))}
    >
      {visibleCards.map((cardName) => {
        const card = cardRegistry[cardName];
        if (!card) return <div key={cardName} />;
        return (
          <div key={cardName}>
            {card}
          </div>
        );
      })}
    </Grid>
  );

  return (
    <SpaceBetween size="l">
      <Header variant="h2" description="Role-based observability dashboards">
        Observability
      </Header>

      <Tabs
        activeTabId={activePersona}
        onChange={({ detail }) => onPersonaChange(detail.activeTabId)}
        tabs={[
          { id: 'PM', label: 'Product Manager', content: renderCards() },
          { id: 'SWE', label: 'Software Engineer', content: renderCards() },
          { id: 'SRE', label: 'Site Reliability', content: renderCards() },
          { id: 'Architect', label: 'Architect', content: renderCards() },
          { id: 'Staff', label: 'Staff Engineer', content: renderCards() },
        ]}
      />
    </SpaceBetween>
  );
};
