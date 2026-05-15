/**
 * PipelineView — Task Pipeline using Cloudscape Table + Container pattern.
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Table, { TableProps } from '@cloudscape-design/components/table';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Link from '@cloudscape-design/components/link';
import Box from '@cloudscape-design/components/box';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import ColumnLayout from '@cloudscape-design/components/column-layout';

import { useTranslation } from 'react-i18next';

interface PipelineViewProps {
  tasks: any[];
  metrics: any;
}

function getTaskStatus(task: any): { type: 'success' | 'error' | 'warning' | 'in-progress' | 'stopped' | 'pending'; text: string } {
  if (task.pr_url) return { type: 'success', text: 'PR Delivered' };
  if (task.status === 'running' || task.status === 'IN_PROGRESS') return { type: 'in-progress', text: task.current_stage || 'Running' };
  if (task.status === 'completed' || task.status === 'COMPLETED') return { type: 'success', text: 'Complete' };
  if (task.status === 'completed_no_delivery') return { type: 'warning', text: 'Delivery Failed' };
  if (task.status === 'failed' || task.status === 'FAILED') return { type: 'error', text: 'Failed' };
  if (task.pr_error) return { type: 'warning', text: 'Push Failed' };
  return { type: 'pending', text: task.current_stage || task.status || 'Pending' };
}

const columnDefinitions: TableProps.ColumnDefinition<any>[] = [
  {
    id: 'title',
    header: 'Task',
    cell: (item) => <Box fontWeight="bold">{item.title}</Box>,
    sortingField: 'title',
    isRowHeader: true,
    minWidth: 200,
  },
  {
    id: 'status',
    header: 'Status',
    cell: (item) => {
      const s = getTaskStatus(item);
      return <StatusIndicator type={s.type}>{s.text}</StatusIndicator>;
    },
    sortingField: 'status',
    minWidth: 140,
  },
  {
    id: 'repo',
    header: 'Repository',
    cell: (item) => <Box variant="code">{item.repo || 'unknown'}</Box>,
    sortingField: 'repo',
    minWidth: 120,
  },
  {
    id: 'task_id',
    header: 'Task ID',
    cell: (item) => <Box variant="code" fontSize="body-s">{item.task_id}</Box>,
    minWidth: 100,
  },
  {
    id: 'progress',
    header: 'Progress',
    cell: (item) => (
      item.stage_progress ? (
        <ProgressBar
          value={item.stage_progress.percent || 0}
          variant="standalone"
          additionalInfo={`${item.stage_progress.current}/${item.stage_progress.total}`}
        />
      ) : <Box>—</Box>
    ),
    minWidth: 140,
  },
  {
    id: 'links',
    header: 'Links',
    cell: (item) => (
      <SpaceBetween direction="horizontal" size="xs">
        {item.pr_url && <Link href={item.pr_url} external>PR</Link>}
        {item.issue_url && <Link href={item.issue_url} external>Issue</Link>}
      </SpaceBetween>
    ),
    minWidth: 100,
  },
];

export const PipelineView: React.FC<PipelineViewProps> = ({ tasks, metrics }) => {
  const { t } = useTranslation();

  return (
    <SpaceBetween size="l">
      {/* Metrics summary */}
      <Container>
        <ColumnLayout columns={4} variant="text-grid">
          <div>
            <Box variant="awsui-key-label">Active</Box>
            <Box variant="awsui-value-large">
              <StatusIndicator type="in-progress">{metrics.active || 0}</StatusIndicator>
            </Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Completed (24h)</Box>
            <Box variant="awsui-value-large">
              <StatusIndicator type="success">{metrics.completed_24h || 0}</StatusIndicator>
            </Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Failed (24h)</Box>
            <Box variant="awsui-value-large">
              <StatusIndicator type="error">{metrics.failed_24h || 0}</StatusIndicator>
            </Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Agents Provisioned</Box>
            <Box variant="awsui-value-large">{metrics.total_agents_provisioned || 0}</Box>
          </div>
        </ColumnLayout>
      </Container>

      {/* Task table */}
      <Table
        columnDefinitions={columnDefinitions}
        items={tasks}
        variant="container"
        header={
          <Header
            variant="h2"
            counter={`(${tasks.length})`}
            description={t('pipeline.subtitle')}
          >
            {t('pipeline.title')}
          </Header>
        }
        empty={
          <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
            <SpaceBetween size="m">
              <b>{t('pipeline.awaiting_signal')}</b>
              <Box variant="p" color="inherit">
                No tasks in the pipeline. Submit a task via GitHub Issue or API.
              </Box>
            </SpaceBetween>
          </Box>
        }
        sortingDisabled
        enableKeyboardNavigation
      />
    </SpaceBetween>
  );
};
