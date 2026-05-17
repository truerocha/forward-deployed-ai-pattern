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
import TreeView, { TreeViewProps } from '@cloudscape-design/components/tree-view';

import { LogEntry } from '../types';
import { useTranslation } from 'react-i18next';
import { AgentAvatar } from '../components/AgentAvatar';

interface ReasoningViewProps {
  logs: LogEntry[];
}

// Pipeline phases in execution order
const PIPELINE_PHASES = [
  { id: 'intake', label: 'Task Intake', description: 'Webhook received, task classified and dispatched' },
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
    if (msg.includes('workspace') || msg.includes('cloned') || msg.includes('branch')) {
      phasesSeen.add('workspace');
      currentPhase = 'workspace';
    }
    if (msg.includes('reconnaissance') || msg.includes('constraint') || msg.includes('scope')) {
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
    // Always mark intake as seen
    phasesSeen.add('intake');
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

function buildTreeItems(logs: LogEntry[]): TreeViewProps.Item[] {
  // Group logs by detected phase
  const phases: Record<string, LogEntry[]> = {
    'Intake': [],
    'Workspace': [],
    'Reconnaissance': [],
    'Engineering': [],
    'Review': [],
    'Completion': [],
    'Other': [],
  };

  for (const log of logs) {
    const msg = log.message.toLowerCase();
    if (msg.includes('workspace') || msg.includes('clone') || msg.includes('branch')) {
      phases['Workspace'].push(log);
    } else if (msg.includes('reconnaissance') || msg.includes('constraint') || msg.includes('scope') || msg.includes('intake')) {
      phases['Reconnaissance'].push(log);
    } else if (msg.includes('engineering') || msg.includes('step_') || msg.includes('erp') || msg.includes('executing') || msg.includes('code')) {
      phases['Engineering'].push(log);
    } else if (msg.includes('push') || msg.includes('pr ') || msg.includes('pull request') || msg.includes('review')) {
      phases['Review'].push(log);
    } else if (msg.includes('complete') || msg.includes('finished') || msg.includes('metrics')) {
      phases['Completion'].push(log);
    } else if (msg.includes('starting') || msg.includes('dispatch') || msg.includes('ingest')) {
      phases['Intake'].push(log);
    } else {
      phases['Other'].push(log);
    }
  }

  // Build tree items — only include phases that have events
  const treeItems: TreeViewProps.Item[] = [];

  for (const [phase, events] of Object.entries(phases)) {
    if (events.length === 0) continue;

    const hasError = events.some(e => e.type === 'error');
    const phaseIcon = hasError ? '❌' : '✅';

    treeItems.push({
      id: phase,
      text: `${phaseIcon} ${phase} (${events.length})`,
      items: events.slice(0, 20).map((event, idx) => ({
        id: `${phase}-${idx}`,
        text: `${event.timestamp} [${event.agentName}] ${event.message}`,
      })),
    });
  }

  return treeItems;
}

export const ReasoningView: React.FC<ReasoningViewProps> = ({ logs }) => {
  const { t } = useTranslation();

  const { steps } = useMemo(() => deriveStepsFromLogs(logs), [logs]);

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
            items={buildTreeItems(logs)}
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
