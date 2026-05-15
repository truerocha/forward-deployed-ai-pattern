/**
 * GateHistoryCard — Gate interaction history using Cloudscape Container + StatusIndicator.
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';

interface GateHistoryEntry {
  gate_name: string;
  status: 'pass' | 'fail' | 'warn' | 'pending';
  timestamp: string;
  feedback?: string;
}

interface GateHistoryCardProps {
  history?: GateHistoryEntry[] | null;
  taskId?: string;
}

function mapGateStatus(status: string): 'success' | 'error' | 'warning' | 'pending' {
  switch (status) { case 'pass': return 'success'; case 'fail': return 'error'; case 'warn': return 'warning'; default: return 'pending'; }
}

export const GateHistoryCard: React.FC<GateHistoryCardProps> = ({ history, taskId }) => {
  if (!history || history.length === 0) {
    return (
      <Container header={<Header variant="h3">Gate History</Header>}>
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">No gate interactions</StatusIndicator>
        </Box>
      </Container>
    );
  }

  const passCount = history.filter((h) => h.status === 'pass').length;
  const failCount = history.filter((h) => h.status === 'fail').length;

  return (
    <Container
      header={<Header variant="h3" counter={`(${history.length})`} description={`${passCount} passed • ${failCount} failed`}>Gate History</Header>}
      footer={<Box fontSize="body-s" color="text-body-secondary">{history.length} gate interactions • Unified timeline view</Box>}
    >
      <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
        <SpaceBetween size="xs">
          {history.map((entry, idx) => (
            <div key={`${entry.gate_name}-${entry.timestamp}-${idx}`} style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
              <StatusIndicator type={mapGateStatus(entry.status)} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <Box fontSize="body-s" fontWeight="bold">{entry.gate_name}</Box>
                {entry.feedback && <Box fontSize="body-s" color="text-body-secondary">{entry.feedback}</Box>}
                <Box fontSize="body-s" color="text-body-secondary">{new Date(entry.timestamp).toLocaleTimeString()}</Box>
              </div>
            </div>
          ))}
        </SpaceBetween>
      </div>
    </Container>
  );
};
