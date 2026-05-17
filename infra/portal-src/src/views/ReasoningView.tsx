/**
 * ReasoningView — Pipeline Reasoning using Cloudscape Steps + Table.
 *
 * Shows the pipeline execution as a step-by-step flow (Steps component)
 * with detailed reasoning events in an expandable table below.
 *
 * Steps represent pipeline phases: Intake → Workspace → Reconnaissance →
 * Engineering → Review → Completion. Each step shows its status
 * (completed, in-progress, error) derived from the task's events.
 *
 * Ref: https://cloudscape.design/components/steps/
 */
import React, { useMemo } from 'react';

import Steps from '@cloudscape-design/components/steps';
import Table, { TableProps } from '@cloudscape-design/components/table';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import Container from '@cloudscape-design/components/container';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import TreeView from '@cloudscape-design/components/tree-view';
import Icon from '@cloudscape-design/components/icon';

import { LogEntry } from '../types';
import { useTranslation } from 'react-i18next';
import { AgentAvatar } from '../components/AgentAvatar';

interface ReasoningViewProps {
  logs: LogEntry[];
  currentStage?: string;
}

// Pipeline phases in execution order
const PIPELINE_PHASES = [
  { id: 'ingestion', label: 'Ingestion', description: 'Webhook received, parsed, schema validated, dispatched' },
  { id: 'warming', label: 'Container Start', description: 'ECS container provisioning and booting' },
  { id: 'intake', label: 'Task Intake', description: 'Task claimed, routing decision, scope check' },
  { id: 'workspace', label: 'Workspace Setup', description: 'Repository cloned, branch created' },
  { id: 'reconnaissance', label: 'Reconnaissance', description: 'Spec analyzed, constraints extracted' },
  { id: 'engineering', label: 'Engineering', description: 'Code generation, implementation' },
  { id: 'review', label: 'Review & PR', description: 'Push branch, create pull request' },
  { id: 'completion', label: 'Completion', description: 'Task finalized, metrics emitted' },
];

function deriveStepsFromLogs(logs: LogEntry[], currentStage?: string): { steps: any[]; activeIndex: number } {
  // Primary: use currentStage from DynamoDB (authoritative, deterministic)
  // Fallback: derive from log keywords (legacy, heuristic)
  const STAGE_TO_PHASE_INDEX: Record<string, number> = {
    'ingested': 0,
    'ingestion': 0,
    'warming': 1,
    'container_start': 1,
    'intake': 2,
    'claimed': 2,
    'workspace': 3,
    'reconnaissance': 4,
    'swe': 5,
    'code': 5,
    'architect': 5,
    'reviewer': 5,
    'engineering': 5,
    'testing': 5,
    'task': 5,
    'reporting': 6,
    'review': 6,
    'completion': 7,
    'completed': 7,
    'failed': -1,
    'execution_error': -1,
    'dispatch_failed': -1,
  };

  let activePhaseIndex = -1;
  let hasError = false;
  let errorPhaseIndex = -1;

  // Use currentStage if available (authoritative from DynamoDB task record)
  if (currentStage) {
    const normalized = currentStage.toLowerCase().replace(/[- ]/g, '_');
    activePhaseIndex = STAGE_TO_PHASE_INDEX[normalized] ?? -1;

    // Check if it's an error state
    if (normalized.includes('error') || normalized.includes('failed')) {
      hasError = true;
      // Find the last known good phase from logs for error positioning
      errorPhaseIndex = activePhaseIndex >= 0 ? activePhaseIndex : 5; // default to engineering
    }
  }

  // Fallback: derive from logs if currentStage didn't resolve
  if (activePhaseIndex < 0 && !hasError) {
    let currentPhase = 'intake';

    for (const log of logs) {
      const phase = log.phase || '';
      const msg = log.message.toLowerCase();

      if (phase === 'ingestion' || msg.includes('ingestion') || msg.includes('dispatch')) {
        currentPhase = 'ingestion';
      }
      if (phase === 'warming' || msg.includes('warming') || msg.includes('container ack')) {
        currentPhase = 'warming';
      }
      if (phase === 'intake' || msg.includes('claimed') || msg.includes('routing')) {
        currentPhase = 'intake';
      }
      if (phase === 'workspace' || msg.includes('workspace') || msg.includes('cloned')) {
        currentPhase = 'workspace';
      }
      if (phase === 'reconnaissance' || msg.includes('reconnaissance') || msg.includes('constraint')) {
        currentPhase = 'reconnaissance';
      }
      if (phase === 'engineering' || phase.includes('swe-') || msg.includes('engineering') || msg.includes('executing')) {
        currentPhase = 'engineering';
      }
      if (phase === 'review' || phase.includes('commiter') || msg.includes('push') || msg.includes('pull request')) {
        currentPhase = 'review';
      }
      if (phase === 'completion' || msg.includes('complete') || msg.includes('finished')) {
        currentPhase = 'completion';
      }
      if (log.type === 'error') {
        hasError = true;
      }
    }

    activePhaseIndex = PIPELINE_PHASES.findIndex(p => p.id === currentPhase);
    if (hasError) errorPhaseIndex = activePhaseIndex;
  }

  // If still no resolution and we have logs, default to intake
  if (activePhaseIndex < 0 && logs.length > 0) {
    activePhaseIndex = 0;
  }

  const isCompleted = currentStage === 'completion' || currentStage === 'completed';

  const steps = PIPELINE_PHASES.map((phase, idx) => {
    let status: 'loading' | 'finished' | 'error' | 'disabled' = 'disabled';

    if (hasError && idx === errorPhaseIndex) {
      status = 'error';
    } else if (idx < activePhaseIndex) {
      status = 'finished';
    } else if (idx === activePhaseIndex) {
      status = isCompleted ? 'finished' : 'loading';
    }

    return {
      title: phase.label,
      description: phase.description,
      status,
    };
  });

  return { steps, activeIndex: activePhaseIndex };
}

function getLogType(type: string): 'success' | 'error' | 'warning' | 'in-progress' | 'info' | 'stopped' {
  switch (type) {
    case 'action': case 'complete': return 'success';
    case 'error': return 'error';
    case 'working': return 'in-progress';
    case 'thought': return 'info';
    default: return 'stopped';
  }
}

function getLogBadgeColor(type: string): 'blue' | 'red' | 'green' | 'grey' {
  switch (type) {
    case 'action': case 'complete': return 'green';
    case 'error': return 'red';
    case 'working': case 'thought': return 'blue';
    default: return 'grey';
  }
}

const columnDefinitions: TableProps.ColumnDefinition<LogEntry>[] = [
  {
    id: 'timestamp',
    header: 'Time',
    cell: (item) => <Box variant="code" fontSize="body-s">{item.timestamp}</Box>,
    width: 90,
  },
  {
    id: 'type',
    header: 'Type',
    cell: (item) => <Badge color={getLogBadgeColor(item.type)}>{item.type}</Badge>,
    width: 90,
  },
  {
    id: 'agent',
    header: 'Agent',
    cell: (item) => (
      <SpaceBetween direction="horizontal" size="xs" alignItems="center">
        <AgentAvatar agentName={item.agentName} size="s" />
        <Box fontWeight="bold" fontSize="body-s">{item.agentName}</Box>
      </SpaceBetween>
    ),
    width: 180,
  },
  {
    id: 'message',
    header: 'Message',
    cell: (item) => (
      <StatusIndicator type={getLogType(item.type)}>
        {item.message}
      </StatusIndicator>
    ),
  },
];

function buildTreeData(logs: LogEntry[]) {
  // Group logs by phase field (deterministic) with keyword fallback
  const phases: Record<string, LogEntry[]> = {};
  const phaseOrder = ['Ingestion', 'Intake', 'Workspace', 'Reconnaissance', 'Engineering', 'Review', 'Completion', 'Other'];

  for (const phase of phaseOrder) phases[phase] = [];

  for (const log of logs) {
    // Primary: use the structured phase field (deterministic, no guessing)
    const rawPhase = log.phase || '';

    if (rawPhase === 'ingestion') {
      phases['Ingestion'].push(log);
    } else if (rawPhase === 'intake') {
      phases['Intake'].push(log);
    } else if (rawPhase === 'workspace') {
      phases['Workspace'].push(log);
    } else if (rawPhase === 'reconnaissance' || rawPhase.includes('code-reader')) {
      phases['Reconnaissance'].push(log);
    } else if (rawPhase === 'engineering' || rawPhase.includes('developer') || rawPhase.includes('swe-') || rawPhase.includes('code-quality')) {
      phases['Engineering'].push(log);
    } else if (rawPhase === 'review' || rawPhase.includes('commiter') || rawPhase.includes('committer') || rawPhase.includes('fidelity')) {
      phases['Review'].push(log);
    } else if (rawPhase === 'completion' || rawPhase.includes('reporting')) {
      phases['Completion'].push(log);
    } else if (rawPhase) {
      // Has a phase but doesn't match known categories — use as-is in Engineering (most common)
      phases['Engineering'].push(log);
    } else {
      // No phase field — fallback to keyword matching (legacy events)
      const msg = log.message.toLowerCase();
      if (msg.includes('ingestion') || msg.includes('parsed') || msg.includes('schema')) {
        phases['Ingestion'].push(log);
      } else if (msg.includes('workspace') || msg.includes('clone')) {
        phases['Workspace'].push(log);
      } else if (msg.includes('reconnaissance') || msg.includes('constraint') || msg.includes('scope')) {
        phases['Reconnaissance'].push(log);
      } else if (msg.includes('engineering') || msg.includes('step_') || msg.includes('executing')) {
        phases['Engineering'].push(log);
      } else if (msg.includes('push') || msg.includes('pr ') || msg.includes('pull request')) {
        phases['Review'].push(log);
      } else if (msg.includes('complete') || msg.includes('finished') || msg.includes('metrics')) {
        phases['Completion'].push(log);
      } else if (msg.includes('starting') || msg.includes('dispatch') || msg.includes('ingest') || msg.includes('claimed')) {
        phases['Intake'].push(log);
      } else {
        phases['Other'].push(log);
      }
    }
  }

  // Build tree items with nestedItems
  return phaseOrder
    .filter(phase => phases[phase].length > 0)
    .map(phase => {
      const events = phases[phase];
      const hasError = events.some(e => e.type === 'error');
      return {
        id: phase,
        content: `${hasError ? '❌' : '✅'} ${phase} (${events.length})`,
        iconName: 'folder' as const,
        nestedItems: events.slice(0, 20).map((event, idx) => ({
          id: `${phase}-${idx}`,
          content: `[${event.agentName}] ${event.message}`,
          iconName: (event.type === 'error' ? 'status-negative' : event.type === 'working' ? 'status-in-progress' : 'status-positive') as any,
          timestamp: event.timestamp,
        })),
      };
    });
}

export const ReasoningView: React.FC<ReasoningViewProps> = ({ logs, currentStage }) => {
  const { t } = useTranslation();
  const [expandedItems, setExpandedItems] = React.useState<string[]>([]);

  const { steps, activeIndex } = useMemo(() => deriveStepsFromLogs(logs, currentStage), [logs, currentStage]);
  const treeData = useMemo(() => buildTreeData(logs), [logs]);

  const totalSteps = PIPELINE_PHASES.length;
  const currentStepNumber = activeIndex >= 0 ? activeIndex + 1 : 0;
  const isComplete = currentStage === 'completion' || currentStage === 'completed';
  const hasError = currentStage?.includes('error') || currentStage?.includes('failed');

  return (
    <SpaceBetween size="l">
      {/* Pipeline Steps — visual flow of execution phases */}
      <Container
        header={
          <Header
            variant="h2"
            description={
              isComplete
                ? `All ${totalSteps} stages completed`
                : hasError
                  ? `Failed at stage ${currentStepNumber} of ${totalSteps}`
                  : currentStepNumber > 0
                    ? `Stage ${currentStepNumber} of ${totalSteps} — ${PIPELINE_PHASES[activeIndex]?.label || 'Processing'}`
                    : 'Awaiting pipeline start'
            }
            counter={currentStepNumber > 0 ? `(${currentStepNumber}/${totalSteps})` : undefined}
          >
            Pipeline Flow
          </Header>
        }
      >
        {logs.length > 0 || currentStage ? (
          <Steps steps={steps} />
        ) : (
          <Box textAlign="center" padding="l" color="inherit">
            <StatusIndicator type="pending">
              Awaiting pipeline execution…
            </StatusIndicator>
          </Box>
        )}
      </Container>

      {/* Reasoning Tree — events grouped by pipeline phase */}
      <ExpandableSection
        variant="container"
        headerText={`Reasoning Tree (${logs.length} events)`}
        headerDescription="Events grouped by pipeline phase — expand to see details"
        defaultExpanded={logs.length > 0 && logs.length <= 30}
      >
        {logs.length > 0 ? (
          <TreeView
            items={treeData}
            expandedItems={expandedItems}
            renderItem={(item) => ({
              icon: <Icon name={item.iconName} />,
              content: item.content,
            })}
            getItemId={(item) => item.id}
            getItemChildren={(item) => item.nestedItems}
            onItemToggle={({ detail }) =>
              setExpandedItems(prev =>
                detail.expanded
                  ? [...prev, detail.item.id]
                  : prev.filter(id => id !== detail.item.id)
              )
            }
            ariaLabel="Reasoning events tree"
          />
        ) : (
          <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
            <SpaceBetween size="m">
              <b>{t('terminal.awaiting')}</b>
              <Box variant="p" color="inherit">
                Reasoning events will appear here when tasks are executing.
              </Box>
            </SpaceBetween>
          </Box>
        )}
      </ExpandableSection>
    </SpaceBetween>
  );
};
