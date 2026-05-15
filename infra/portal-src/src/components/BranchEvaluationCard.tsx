/**
 * BranchEvaluationCard — 7-Dimension Quality Gate.
 * Pattern: Cloudscape Container shell + ProgressBar for dimension scores.
 */
import React from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import Badge from '@cloudscape-design/components/badge';
import ColumnLayout from '@cloudscape-design/components/column-layout';
import { useTranslation } from 'react-i18next';

interface DimensionResult { score: number; weight: number; weighted: number; issues: string[]; }
interface EvaluationReport {
  branch: string; base: string; evaluated_at: string;
  verdict: 'PASS' | 'CONDITIONAL_PASS' | 'CONDITIONAL_FAIL' | 'FAIL';
  aggregate_score: number; merge_eligible: boolean; auto_merge_eligible: boolean;
  veto_triggered: boolean; veto_reason: string;
  dimensions: Record<string, DimensionResult>;
  files_evaluated: number; pipeline_edges_affected: string[];
}
interface BranchEvaluationCardProps { report?: EvaluationReport | null; }

function getVerdictBadgeColor(verdict: string): 'green' | 'blue' | 'red' | 'grey' {
  switch (verdict) { case 'PASS': return 'green'; case 'CONDITIONAL_PASS': return 'blue'; default: return 'red'; }
}

export const BranchEvaluationCard: React.FC<BranchEvaluationCardProps> = ({ report }) => {
  const { t } = useTranslation();
  if (!report) {
    return (<Container header={<Header variant="h3">{t('branch_eval.title')}</Header>}><Box textAlign="center" padding="l" color="inherit"><StatusIndicator type="pending">{t('branch_eval.awaiting')}</StatusIndicator></Box></Container>);
  }

  return (
    <Container
      header={<Header variant="h3" description={t('branch_eval.subtitle')} actions={<Badge color={getVerdictBadgeColor(report.verdict)}>{report.verdict}</Badge>}>{t('branch_eval.title')}</Header>}
      footer={<Box fontSize="body-s" color="text-body-secondary">{new Date(report.evaluated_at).toLocaleTimeString()} • {t('branch_eval.agent_label')}</Box>}
    >
      <SpaceBetween size="m">
        <ColumnLayout columns={2} variant="text-grid">
          <div><Box variant="awsui-key-label">Aggregate Score</Box><Box variant="awsui-value-large">{report.aggregate_score.toFixed(1)}/10</Box></div>
          <div><Box variant="awsui-key-label">Branch</Box><Box variant="code">{report.branch}</Box></div>
        </ColumnLayout>
        <SpaceBetween direction="horizontal" size="xs">
          <StatusIndicator type={report.merge_eligible ? 'success' : 'error'}>{report.merge_eligible ? t('branch_eval.merge_yes') : t('branch_eval.merge_no')}</StatusIndicator>
          {report.auto_merge_eligible && <Badge color="green">{t('branch_eval.auto_merge')}</Badge>}
        </SpaceBetween>
        <div style={{ maxHeight: '140px', overflowY: 'auto' }}>
          <SpaceBetween size="xs">
            {Object.entries(report.dimensions).map(([name, dim]) => {
              const d = dim as DimensionResult;
              return (<div key={name}><ProgressBar value={(d.score / 10) * 100} label={name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())} additionalInfo={`${d.score.toFixed(1)}/10 (${(d.weight * 100).toFixed(0)}%)`} variant="standalone" status={d.score < 6 ? 'error' : undefined} /></div>);
            })}
          </SpaceBetween>
        </div>
        {report.veto_triggered && <StatusIndicator type="error">{report.veto_reason}</StatusIndicator>}
        <Box fontSize="body-s" color="text-body-secondary">{report.files_evaluated} {t('branch_eval.files')} • Edges: {report.pipeline_edges_affected.join(', ') || 'none'}</Box>
      </SpaceBetween>
    </Container>
  );
};
