/**
 * LiveTimeline — Pipeline event timeline using Cloudscape Container + StatusIndicator.
 */
import React, { useEffect, useRef } from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Badge from '@cloudscape-design/components/badge';

interface TimelineEvent {
  type: 'stage_start' | 'stage_complete' | 'stage_error' | 'info' | 'warning';
  timestamp: string;
  message: string;
  status: 'running' | 'success' | 'error' | 'pending' | 'skipped';
}

interface LiveTimelineProps {
  events: TimelineEvent[];
  autoScroll?: boolean;
  wsConnected?: boolean;
}

function mapStatus(status: string): 'success' | 'error' | 'warning' | 'in-progress' | 'stopped' | 'pending' {
  switch (status) {
    case 'running': return 'in-progress';
    case 'success': return 'success';
    case 'error': return 'error';
    case 'pending': return 'pending';
    default: return 'stopped';
  }
}

export const LiveTimeline: React.FC<LiveTimelineProps> = ({
  events,
  autoScroll = true,
  wsConnected = false,
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [events, autoScroll]);

  return (
    <Container
      header={
        <Header
          variant="h3"
          counter={`(${events.length})`}
          actions={
            <Badge color={wsConnected ? 'green' : 'red'}>
              {wsConnected ? 'POLLING' : 'DISCONNECTED'}
            </Badge>
          }
        >
          Live Timeline
        </Header>
      }
      footer={
        <Box fontSize="body-s" color="text-body-secondary">
          {events.length} events • {autoScroll ? 'Auto-scroll ON' : 'Auto-scroll OFF'}
        </Box>
      }
    >
      {events.length === 0 ? (
        <Box textAlign="center" padding="l" color="inherit">
          <StatusIndicator type="pending">Waiting for pipeline execution…</StatusIndicator>
        </Box>
      ) : (
        <div ref={scrollRef} style={{ maxHeight: '220px', overflowY: 'auto' }}>
          <SpaceBetween size="xs">
            {events.map((event, idx) => (
              <div key={`${event.timestamp}-${idx}`} style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                <StatusIndicator type={mapStatus(event.status)} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Box fontSize="body-s">{event.message}</Box>
                  <Box fontSize="body-s" color="text-body-secondary">
                    {new Date(event.timestamp).toLocaleTimeString()} • {event.type.replace(/_/g, ' ')}
                  </Box>
                </div>
              </div>
            ))}
          </SpaceBetween>
        </div>
      )}
    </Container>
  );
};
