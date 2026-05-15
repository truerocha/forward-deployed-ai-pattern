/**
 * DataQualityCard — Knowledge artifact quality using Cloudscape Container + StatusIndicator.
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Badge from '@cloudscape-design/components/badge';

interface DataQualityAssessment {
  name: string;
  composite_score: number;
  is_stale: boolean;
  alerts: string[];
}

interface DataQualityCardProps {
  assessments?: DataQualityAssessment[] | null;
}

function getHealthStatus(score: number, isStale: boolean): 'success' | 'warning' | 'error' {
  if (isStale || score < 40) return 'error';
  if (score < 70) return 'warning';
  return 'success';
}

export const DataQualityCard: React.FC<DataQualityCardProps> = ({ assessments }) => {
  if (!assessments || assessments.length === 0) {
    return (
      <Container header={<Header variant="h3">Data Quality</Header>}>
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">No artifacts assessed</StatusIndicator>
        </Box>
      </Container>
    );
  }

  const healthyCount = assessments.filter((a) => a.composite_score >= 70 && !a.is_stale).length;
  const warningCount = assessments.filter((a) => a.composite_score >= 40 && a.composite_score < 70 && !a.is_stale).length;
  const criticalCount = assessments.filter((a) => a.composite_score < 40 || a.is_stale).length;

  return (
    <Container
      header={
        <Header variant="h3" counter={`(${assessments.length})`} description={`${healthyCount} healthy • ${warningCount} warning • ${criticalCount} critical`}>
          Data Quality
        </Header>
      }
      footer={<Box fontSize="body-s" color="text-body-secondary">{assessments.length} knowledge artifacts assessed</Box>}
    >
      <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
        <SpaceBetween size="xs">
          {assessments.map((assessment) => (
            <div key={assessment.name} style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
              <StatusIndicator type={getHealthStatus(assessment.composite_score, assessment.is_stale)} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                  <Box fontSize="body-s" fontWeight="bold">{assessment.name}</Box>
                  {assessment.is_stale && <Badge color="red">Stale</Badge>}
                  <Box fontSize="body-s" color="text-body-secondary">{assessment.composite_score}/100</Box>
                </SpaceBetween>
                {assessment.alerts.length > 0 && (
                  <Box fontSize="body-s" color="text-body-secondary">
                    {assessment.alerts.slice(0, 2).join(' • ')}{assessment.alerts.length > 2 && ` (+${assessment.alerts.length - 2} more)`}
                  </Box>
                )}
              </div>
            </div>
          ))}
        </SpaceBetween>
      </div>
    </Container>
  );
};
