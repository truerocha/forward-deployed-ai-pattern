/**
 * AgentsView — Squad Agents using Cloudscape Cards pattern.
 */
import React from 'react';

import Cards from '@cloudscape-design/components/cards';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Box from '@cloudscape-design/components/box';
import Badge from '@cloudscape-design/components/badge';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';

import { Agent } from '../types';
import { useTranslation } from 'react-i18next';

interface AgentsViewProps {
  agents: Agent[];
}

function getAgentStatusType(status: string): 'success' | 'error' | 'warning' | 'in-progress' | 'stopped' | 'pending' {
  switch (status) {
    case 'working': case 'thinking': return 'in-progress';
    case 'complete': return 'success';
    case 'error': return 'error';
    case 'idle': case 'setup': return 'pending';
    default: return 'stopped';
  }
}

function getRoleBadgeColor(role: string): 'blue' | 'red' | 'green' | 'grey' {
  switch (role) {
    case 'planner': case 'architect': return 'blue';
    case 'adversarial': return 'red';
    case 'coder': case 'reviewer': return 'green';
    default: return 'grey';
  }
}

export const AgentsView: React.FC<AgentsViewProps> = ({ agents }) => {
  const { t } = useTranslation();

  return (
    <Cards<Agent>
      cardDefinition={{
        header: (item) => (
          <SpaceBetween direction="horizontal" size="xs" alignItems="center">
            <Box fontWeight="bold">{item.name}</Box>
            <Badge color={getRoleBadgeColor(item.role)}>{item.role}</Badge>
          </SpaceBetween>
        ),
        sections: [
          {
            id: 'status',
            header: 'Status',
            content: (item) => (
              <StatusIndicator type={getAgentStatusType(item.status)}>
                {item.status}
              </StatusIndicator>
            ),
          },
          {
            id: 'details',
            content: (item) => (
              <KeyValuePairs
                columns={2}
                items={[
                  { label: 'Model Tier', value: item.modelTier || '—' },
                  { label: 'Topology', value: item.topology || '—' },
                  ...(item.stageIndex ? [{ label: 'Stage', value: `${item.stageIndex}/${item.totalStages || '?'}` }] : []),
                  ...(item.subtask ? [{ label: 'Subtask', value: item.subtask }] : []),
                ]}
              />
            ),
          },
          {
            id: 'progress',
            content: (item) => (
              item.progress !== undefined ? (
                <ProgressBar
                  value={item.progress}
                  variant="standalone"
                  label="Execution progress"
                />
              ) : null
            ),
          },
        ],
      }}
      items={agents}
      header={
        <Header
          variant="h2"
          counter={`(${agents.length})`}
          description={t('agents.subtitle')}
        >
          {t('agents.title')}
        </Header>
      }
      empty={
        <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
          <SpaceBetween size="m">
            <b>{t('agents.standby')}</b>
            <Box variant="p" color="inherit">
              No agents currently provisioned.
            </Box>
          </SpaceBetween>
        </Box>
      }
      cardsPerRow={[{ cards: 1 }, { minWidth: 500, cards: 2 }, { minWidth: 900, cards: 3 }]}
    />
  );
};
