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

function deriveStepsFromLogs(logs: LogEntry[]): { steps: any[]; activeIndex: number } {
  // Determine which phases have been reached based on log messages
  const phasesSeen = new Set<string>();
  let currentPhase = 'intake';
  let hasError = false;
  let errorPhase = '';

  for (const log of logs) {
    const msg = log.message.toLowerCase();
    if (msg.includes('ingestion') || msg.includes('parsed') || msg.includes('schema validation') || msg.includes('dispatch')) {
      phasesSeen.add('ingestion');
      currentPhase = 'ingestion';
    }
    if (msg.includes('warming') || msg.includes('container ack') || msg.includes('container start') || msg.includes('provisioning')) {
      phasesSeen.add('warming');
      currentPhase = 'warming';
    }
    if (msg.includes('claimed') || msg.includes('scope') || msg.includes('routing') || msg.includes('autonomy')) {
      phasesSeen.add('intake');
      currentPhase = 'intake';
    }
    if (msg.includes('workspace') || msg.includes('cloned') || msg.includes('branch')) {
      phasesSeen.add('workspace');
      currentPhase = 'workspace';
    }
    if (msg.includes('reconnaissance') || msg.includes('constraint')) {
      phasesSeen.add('reconnaissance');
      currentPhase = 'reconnaissance';
    }
    if (msg.includes('engineering') || msg.includes('step_') || msg.includes('erp') || msg.includes('executing')) {
      phasesSeen.add('engineering');
      currentPhase = 'engineering';
    }
    if (msg.includes('push') || msg.includes('pr created') || msg.includes('pull request') || msg.includes('review')) {
      phasesSeen.add('review');
      currentPhase = 'review';
    }
    if (msg.includes('complete') || msg.includes('finished') || msg.includes('done')) {
      phasesSeen.add('completion');
      currentPhase = 'completion';
    }
    if (log.type === 'error') {
      hasError = true;
      errorPhase = currentPhase;
    }
    // Always mark ingestion as seen (first event implies ingestion happened)
    phasesSeen.add('ingestion');
  }

  const activePhaseIndex = PIPELINE_PHASES.findIndex(p => p.id === currentPhase);

  const steps = PIPELINE_PHASES.map((phase, idx) => {
    let status: 'loading' | 'finished' | 'error' | 'disabled' = 'disabled';

    if (hasError && phase.id === errorPhase) {
      status = 'error';
    } else if (idx < activePhaseIndex) {
      status = 'finished';
    } else if (idx === activePhaseIndex) {
      status = phasesSeen.has('completion') && phase.id === 'completion' ? 'finished' : 'loading';
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

export const ReasoningView: React.FC<ReasoningViewProps> = ({ logs }) => {
  const { t } = useTranslation();
  const [expandedItems, setExpandedItems] = React.useState<string[]>([]);

  const { steps } = useMemo(() => deriveStepsFromLogs(logs), [logs]);
  const treeData = useMemo(() => buildTreeData(logs), [logs]);

  return (
    <SpaceBetween size="l">
      {/* Pipeline Steps — visual flow of execution phases */}
      <Container
        header={
          <Header
            variant="h2"
            description="Current pipeline execution phase"
          >
            Pipeline Flow
          </Header>
        }
      >
        {logs.length > 0 ? (
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
