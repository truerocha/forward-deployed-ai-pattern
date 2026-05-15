/**
 * ReasoningView — Chain-of-Thought Timeline using Cloudscape Table.
 */
import React from 'react';

import Table, { TableProps } from '@cloudscape-design/components/table';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';

import { LogEntry } from '../types';
import { useTranslation } from 'react-i18next';

interface ReasoningViewProps {
  logs: LogEntry[];
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
    cell: (item) => <Box fontWeight="bold" fontSize="body-s">{item.agentName}</Box>,
    width: 140,
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

export const ReasoningView: React.FC<ReasoningViewProps> = ({ logs }) => {
  const { t } = useTranslation();

  return (
    <Table
      columnDefinitions={columnDefinitions}
      items={logs.slice(0, 100)}
      variant="container"
      header={
        <Header
          variant="h2"
          counter={`(${logs.length})`}
          description={t('terminal.subtitle')}
        >
          {t('terminal.title')}
        </Header>
      }
      empty={
        <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
          <SpaceBetween size="m">
            <b>{t('terminal.awaiting')}</b>
            <Box variant="p" color="inherit">
              Reasoning events will appear here when tasks are executing.
            </Box>
          </SpaceBetween>
        </Box>
      }
      stickyHeader
      stripedRows
      enableKeyboardNavigation
    />
  );
};
