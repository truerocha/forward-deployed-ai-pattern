/**
 * ObservabilityView — Persona-filtered cards using Cloudscape Tabs + Grid.
 */
import React from 'react';

import Tabs from '@cloudscape-design/components/tabs';
import Grid from '@cloudscape-design/components/grid';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';

import { DoraCard } from '../components/DoraCard';
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
import { QualityGateCard } from '../components/QualityGateCard';
import { PipelineHealthCard } from '../components/PipelineHealthCard';
import { EvidenceConfidenceCard } from '../components/EvidenceConfidenceCard';
import { GoldenSignalsCard } from '../components/GoldenSignalsCard';
import CapacityCard from '../components/CapacityCard';
import ReadinessCard from '../components/ReadinessCard';
import {
  mapDoraMetrics,
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
  PM: ['ValueStreamCard', 'TrustCard', 'NetFrictionCard', 'ReviewFeedbackCard', 'CognitiveAutonomyCard'],
  SWE: ['LiveTimeline', 'GateFeedbackCard', 'SquadExecutionCard', 'BranchEvaluationCard', 'HumanInputCard', 'ConductorPlanCard', 'ReviewFeedbackCard', 'CognitiveAutonomyCard', 'QualityGateCard'],
  SRE: ['GoldenSignalsCard', 'ReadinessCard', 'CapacityCard', 'DataQualityCard', 'GateHistoryCard', 'ReviewFeedbackCard', 'CognitiveAutonomyCard', 'PipelineHealthCard'],
  Architect: ['MaturityRadar', 'BrainSimCard', 'ConductorPlanCard', 'ValueStreamCard', 'DataQualityCard', 'NetFrictionCard', 'EvidenceConfidenceCard'],
  Staff: ['MaturityRadar', 'TrustCard', 'BrainSimCard', 'ValueStreamCard', 'SquadExecutionCard', 'ReviewFeedbackCard', 'CognitiveAutonomyCard', 'QualityGateCard', 'PipelineHealthCard', 'EvidenceConfidenceCard', 'CapacityCard', 'ReadinessCard'],
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
    QualityGateCard: <QualityGateCard />,
    PipelineHealthCard: <PipelineHealthCard />,
    EvidenceConfidenceCard: <EvidenceConfidenceCard />,
    GoldenSignalsCard: <GoldenSignalsCard metrics={factoryData?.metrics ? { ...factoryData.metrics, dora: factoryData.dora } : null} health={null} routingHealth={factoryData?.routing_health || null} />,
    CapacityCard: <CapacityCard />,
    ReadinessCard: <ReadinessCard />,
  };

  /** Determine if a card has data worth showing (suppress empty states) */
  const hasData = (cardName: string): boolean => {
    switch (cardName) {
      case 'LiveTimeline': return !!(factoryData?.tasks?.length > 0);
      case 'GateFeedbackCard': return !!(factoryData?.tasks?.some((t: any) => t.events?.some((e: any) => e.type === 'gate')));
      case 'GateHistoryCard': return !!(mapGateHistory(factoryData)?.length > 0);
      case 'SquadExecutionCard': return !!(mapSquadExecution(factoryData)?.length > 0);
      case 'ConductorPlanCard': return !!(factoryData?.conductor?.steps?.length > 0);
      case 'ReviewFeedbackCard': return !!(factoryData?.metrics_data?.review_feedback);
      case 'CognitiveAutonomyCard': return !!(factoryData?.metrics_data?.cognitive_autonomy);
      case 'BranchEvaluationCard': return !!(factoryData?.branch_evaluation);
      case 'HumanInputCard': return !!(factoryData?.human_input?.pending);
      case 'ValueStreamCard': return !!(factoryData?.metrics_data?.vsm);
      case 'MaturityRadar': return !!(factoryData?.metrics_data?.maturity);
      case 'BrainSimCard': return !!(factoryData?.metrics_data?.brain_sim || factoryData?.metrics_data?.fidelity);
      case 'TrustCard': return !!(factoryData?.metrics_data?.trust);
      case 'NetFrictionCard': return !!(factoryData?.metrics_data?.friction);
      case 'DataQualityCard': return !!(factoryData?.metrics_data?.data_quality);
      case 'EvidenceConfidenceCard': return !!(factoryData?.metrics_data?.evidence_confidence);
      case 'PipelineHealthCard': return !!(factoryData?.metrics_data?.pipeline_health);
      case 'QualityGateCard': return !!(factoryData?.tasks?.some((t: any) => t.events?.some((e: any) => e.type === 'gate')));
      case 'GoldenSignalsCard': return !!(factoryData?.metrics && factoryData?.dora);
      case 'CapacityCard': return true; // Self-fetching, always render
      case 'ReadinessCard': return true; // Self-fetching, always render
      default: return true;
    }
  };

  const renderCards = () => {
    // Filter to only cards that have data to display
    const cardsWithData = visibleCards.filter((cardName) => hasData(cardName));

    if (cardsWithData.length === 0) {
      return (
        <Box textAlign="center" padding="xl" color="text-status-inactive">
          No observability data available yet. Data will appear once tasks execute.
        </Box>
      );
    }

    return (
      <Grid
        gridDefinition={cardsWithData.map(() => ({ colspan: { l: 6, m: 6, default: 12 } }))}
      >
        {cardsWithData.map((cardName) => {
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
  };

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
