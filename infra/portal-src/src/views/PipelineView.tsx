/**
 * PipelineView — Task Pipeline using Cloudscape Table + Container pattern.
 */
import React, { useState, useCallback } from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Table, { TableProps } from '@cloudscape-design/components/table';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Link from '@cloudscape-design/components/link';
import Box from '@cloudscape-design/components/box';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import Pagination from '@cloudscape-design/components/pagination';
import Select from '@cloudscape-design/components/select';

import { useTranslation } from 'react-i18next';

interface PipelineViewProps {
  tasks: any[];
  metrics: any;
  pagination?: {
    page_size: number;
    total_count: number;
    has_more: boolean;
    next_token: string | null;
  };
  onPageChange?: (pageSize: number, nextToken?: string) => void;
}

function getTaskStatus(task: any): { type: 'success' | 'error' | 'warning' | 'in-progress' | 'stopped' | 'pending'; text: string } {
  if (task.pr_url) return { type: 'success', text: 'PR Delivered' };
  if (task.status === 'running' || task.status === 'IN_PROGRESS') return { type: 'in-progress', text: 'Running' };
  if (task.status === 'completed' || task.status === 'COMPLETED') return { type: 'success', text: 'Completed' };
  if (task.status === 'completed_no_delivery') return { type: 'warning', text: 'Delivery Failed' };
  if (task.status === 'failed' || task.status === 'FAILED') return { type: 'error', text: 'Failed' };
  if (task.status === 'REJECTED') return { type: 'error', text: 'Rejected' };
  if (task.status === 'DUPLICATE') return { type: 'stopped', text: `Duplicate → ${task.canonical_task_id?.slice(-8) || '?'}` };
  if (task.pr_error) return { type: 'warning', text: 'Push Failed' };
  if (task.current_stage === 'warming') return { type: 'pending', text: 'Starting' };
  if (task.current_stage === 'claimed') return { type: 'in-progress', text: 'Claimed' };
  if (task.status === 'DISPATCHED' && !task.started_at) return { type: 'pending', text: 'Queued' };
  if (task.status === 'DISPATCHED') return { type: 'in-progress', text: 'Dispatched' };
  return { type: 'pending', text: task.status || 'Pending' };
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
          additionalInfo={item.stage_progress.phase_label || undefined}
        />
      ) : item.current_stage ? (
        <ProgressBar
          value={item.status === 'COMPLETED' || item.status === 'completed' ? 100 : 50}
          variant="standalone"
          additionalInfo={item.current_stage.replace(/_/g, ' ')}
          status={item.status === 'FAILED' || item.status === 'failed' ? 'error' : undefined}
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

export const PipelineView: React.FC<PipelineViewProps> = ({ tasks, metrics, pagination, onPageChange }) => {
  const { t } = useTranslation();
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(pagination?.page_size || 20);

  // Track pagination tokens per page for back-navigation
  const [pageTokens, setPageTokens] = useState<Record<number, string | undefined>>({ 1: undefined });

  const handlePageChange = useCallback((detail: { currentPageIndex: number }) => {
    const newPage = detail.currentPageIndex;
    setCurrentPage(newPage);

    if (onPageChange) {
      const token = pageTokens[newPage];
      onPageChange(pageSize, token);
    }
  }, [onPageChange, pageSize, pageTokens]);

  // Store next_token for the next page when pagination data arrives
  React.useEffect(() => {
    if (pagination?.next_token && pagination.has_more) {
      setPageTokens(prev => ({ ...prev, [currentPage + 1]: pagination.next_token! }));
    }
  }, [pagination, currentPage]);

  const handlePageSizeChange = useCallback((newSize: number) => {
    setPageSize(newSize);
    setCurrentPage(1);
    setPageTokens({ 1: undefined });
    if (onPageChange) {
      onPageChange(newSize, undefined);
    }
  }, [onPageChange]);

  const totalPages = pagination
    ? Math.ceil(pagination.total_count / pagination.page_size) || 1
    : 1;

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
            <Box variant="awsui-key-label">Blocked</Box>
            <Box variant="awsui-value-large">{metrics.dispatch_stuck || 0}</Box>
          </div>
        </ColumnLayout>
      </Container>

      {/* Task table with pagination */}
      <Table
        columnDefinitions={columnDefinitions}
        items={tasks}
        variant="container"
        header={
          <Header
            variant="h2"
            counter={pagination ? `(${pagination.total_count})` : `(${tasks.length})`}
            description={t('pipeline.subtitle')}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Select
                  selectedOption={{ label: `${pageSize} per page`, value: String(pageSize) }}
                  onChange={({ detail }) => handlePageSizeChange(Number(detail.selectedOption.value))}
                  options={[
                    { label: '10 per page', value: '10' },
                    { label: '20 per page', value: '20' },
                    { label: '50 per page', value: '50' },
                    { label: '100 per page', value: '100' },
                  ]}
                />
              </SpaceBetween>
            }
          >
            {t('pipeline.title')}
          </Header>
        }
        pagination={
          pagination ? (
            <Pagination
              currentPageIndex={currentPage}
              pagesCount={totalPages}
              openEnd={pagination.has_more}
              onChange={({ detail }) => handlePageChange(detail)}
            />
          ) : undefined
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
