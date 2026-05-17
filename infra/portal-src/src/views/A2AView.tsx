/**
 * A2AView — Agent-to-Agent Protocol Observability Dashboard.
 *
 * Persona-filtered view showing A2A workflow health, topology,
 * resilience, and cost metrics. Uses the same Tabs + Card Registry
 * pattern as ObservabilityView for consistency.
 *
 * Personas:
 *   - SRE: Infrastructure health, DLQ, container status, error rates
 *   - Engineer: Contract validation, payload inspection, tool usage
 *   - Architect: Topology, latency distribution, graph dependencies
 *   - PM: Cost per workflow, approval rates, business impact
 */
import React from 'react';

import Tabs from '@cloudscape-design/components/tabs';
import Grid from '@cloudscape-design/components/grid';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';

import { A2ATopologyCard } from '../components/A2ATopologyCard';
import { A2AResilienceCard } from '../components/A2AResilienceCard';
import { A2AWorkflowCostCard } from '../components/A2AWorkflowCostCard';
import { A2AContractInspectorCard } from '../components/A2AContractInspectorCard';
import { A2ASquadCommunicationCard } from '../components/A2ASquadCommunicationCard';
import { GoldenSignalsCard } from '../components/GoldenSignalsCard';
import { PipelineHealthCard } from '../components/PipelineHealthCard';
import { CognitiveAutonomyCard } from '../components/CognitiveAutonomyCard';

interface A2AViewProps {
  factoryData?: any;
}

/** Persona → visible cards mapping */
const A2A_PERSONA_CARDS: Record<string, string[]> = {
  SRE: [
    'A2AResilienceCard',
    'A2ATopologyCard',
    'GoldenSignalsCard',
    'PipelineHealthCard',
  ],
  Engineer: [
    'A2ASquadCommunicationCard',
    'A2AContractInspectorCard',
    'A2ATopologyCard',
    'A2AResilienceCard',
  ],
  Architect: [
    'A2ASquadCommunicationCard',
    'A2ATopologyCard',
    'A2AWorkflowCostCard',
    'CognitiveAutonomyCard',
  ],
  PM: [
    'A2AWorkflowCostCard',
    'A2ASquadCommunicationCard',
    'A2AResilienceCard',
    'CognitiveAutonomyCard',
  ],
};

export const A2AView: React.FC<A2AViewProps> = ({ factoryData }) => {
  const [activePersona, setActivePersona] = React.useState('SRE');

  const a2aData = factoryData?.a2a || {};
  const metricsData = factoryData?.metrics_data || {};

  const cardRegistry: Record<string, React.ReactNode> = {
    A2ATopologyCard: (
      <A2ATopologyCard
        agents={a2aData.agents}
        workflowActive={a2aData.workflowActive}
        totalWorkflows24h={a2aData.totalWorkflows24h}
      />
    ),
    A2AResilienceCard: (
      <A2AResilienceCard
        dlqMetrics={a2aData.dlqMetrics}
        retryDistribution={a2aData.retryDistribution}
        activeWorkflows={a2aData.activeWorkflows}
        failedWorkflows24h={a2aData.failedWorkflows24h}
        circuitBreakerOpen={a2aData.circuitBreakerOpen}
      />
    ),
    A2AWorkflowCostCard: (
      <A2AWorkflowCostCard
        totalCostUsd={a2aData.totalCostUsd}
        agentCosts={a2aData.agentCosts}
        reworkCostUsd={a2aData.reworkCostUsd}
        approvalRate={a2aData.approvalRate}
        totalWorkflows={a2aData.totalWorkflows}
        avgCostPerWorkflow={a2aData.avgCostPerWorkflow}
      />
    ),
    A2ASquadCommunicationCard: (
      <A2ASquadCommunicationCard
        messages={a2aData.devFlowMessages}
        reviewCycles={a2aData.reviewCycles}
        workflowId={a2aData.latestWorkflow?.workflowId}
        currentPhase={a2aData.latestWorkflow?.noAtual}
        specTitle={a2aData.latestWorkflow?.specTitle}
        totalDurationMs={a2aData.latestWorkflow?.totalDurationMs}
        approvedAtAttempt={a2aData.latestWorkflow?.approvedAtAttempt}
        maxAttempts={a2aData.latestWorkflow?.maxRetries || 3}
      />
    ),
    GoldenSignalsCard: (
      <GoldenSignalsCard
        metrics={factoryData?.metrics ? { ...factoryData.metrics, dora: factoryData.dora } : null}
        health={null}
        routingHealth={factoryData?.routing_health || null}
      />
    ),
    A2AContractInspectorCard: (
      <A2AContractInspectorCard
        apiUrl={document.querySelector('meta[name="factory-api-url"]')?.getAttribute('content') || ''}
        initialData={a2aData.latestWorkflow}
      />
    ),
    PipelineHealthCard: <PipelineHealthCard />,
    CognitiveAutonomyCard: <CognitiveAutonomyCard />,
  };

  const renderCards = (persona: string) => {
    const visibleCards = A2A_PERSONA_CARDS[persona] || A2A_PERSONA_CARDS['SRE'];

    if (visibleCards.length === 0) {
      return (
        <Box textAlign="center" padding="xl" color="text-status-inactive">
          No A2A data available. Deploy A2A agents to see metrics.
        </Box>
      );
    }

    return (
      <Grid
        gridDefinition={visibleCards.map(() => ({ colspan: { l: 6, m: 6, default: 12 } }))}
      >
        {visibleCards.map((cardName) => {
          const card = cardRegistry[cardName];
          if (!card) return <div key={cardName} />;
          return <div key={cardName}>{card}</div>;
        })}
      </Grid>
    );
  };

  return (
    <SpaceBetween size="l">
      <Header
        variant="h2"
        description="Agent-to-Agent protocol monitoring — topology, resilience, and cost"
        info={<Badge color="blue">A2A</Badge>}
      >
        A2A Protocol
      </Header>

      <Tabs
        activeTabId={activePersona}
        onChange={({ detail }) => setActivePersona(detail.activeTabId)}
        tabs={[
          { id: 'SRE', label: 'Site Reliability', content: renderCards('SRE') },
          { id: 'Engineer', label: 'Engineer', content: renderCards('Engineer') },
          { id: 'Architect', label: 'Architect', content: renderCards('Architect') },
          { id: 'PM', label: 'Product Manager', content: renderCards('PM') },
        ]}
      />
    </SpaceBetween>
  );
};
