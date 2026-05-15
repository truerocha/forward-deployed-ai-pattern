/**
 * GateFeedbackCard — Gate evaluation result using Cloudscape Container.
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Badge from '@cloudscape-design/components/badge';

interface GateFeedback {
  gate_name: string;
  status: 'pass' | 'fail' | 'warn';
  reason: string;
  violated_rule?: string;
  suggestion?: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
}

interface GateFeedbackCardProps {
  feedback?: GateFeedback | null;
}

function mapFeedbackStatus(status: string): 'success' | 'error' | 'warning' {
  switch (status) { case 'pass': return 'success'; case 'fail': return 'error'; default: return 'warning'; }
}

function getSeverityColor(severity: string): 'red' | 'blue' | 'grey' | 'green' {
  switch (severity) { case 'critical': case 'high': return 'red'; case 'medium': return 'blue'; default: return 'grey'; }
}

export const GateFeedbackCard: React.FC<GateFeedbackCardProps> = ({ feedback }) => {
  if (!feedback) {
    return (
      <Container header={<Header variant="h3">Gate Feedback</Header>}>
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">No gate results</StatusIndicator>
        </Box>
      </Container>
    );
  }

  return (
    <Container
      header={<Header variant="h3" description={feedback.gate_name} actions={<Badge color={getSeverityColor(feedback.severity)}>{feedback.severity}</Badge>}>Gate Feedback</Header>}
      footer={<Box fontSize="body-s" color="text-body-secondary">Quality gate evaluation result</Box>}
    >
      <SpaceBetween size="m">
        <StatusIndicator type={mapFeedbackStatus(feedback.status)}>
          {feedback.status === 'pass' ? 'PASSED' : feedback.status === 'fail' ? 'REJECTED' : 'WARNING'}
        </StatusIndicator>
        <div><Box variant="awsui-key-label">What Failed</Box><Box>{feedback.reason}</Box></div>
        {feedback.violated_rule && (<div><Box variant="awsui-key-label">Violated Rule</Box><Box variant="code">{feedback.violated_rule}</Box></div>)}
        {feedback.suggestion && (<div><Box variant="awsui-key-label">What To Do Next</Box><StatusIndicator type="success">{feedback.suggestion}</StatusIndicator></div>)}
      </SpaceBetween>
    </Container>
  );
};
