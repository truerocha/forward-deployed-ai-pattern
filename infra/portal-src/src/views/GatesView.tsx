/**
 * GatesView — Quality Gate Results using Cloudscape ExpandableSection + StatusIndicator.
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Box from '@cloudscape-design/components/box';
import ExpandableSection from '@cloudscape-design/components/expandable-section';

interface GatesViewProps {
  tasks: any[];
}

export const GatesView: React.FC<GatesViewProps> = ({ tasks }) => {
  const tasksWithGates = tasks.filter((t: any) => t.events?.some((e: any) => e.type === 'gate'));

  return (
    <SpaceBetween size="l">
      <Header
        variant="h2"
        counter={`(${tasksWithGates.length})`}
        description="Pipeline Gate Results (Real-Time)"
      >
        Quality Gates
      </Header>

      {tasksWithGates.length === 0 && (
        <Container>
          <Box margin={{ vertical: 'xs' }} textAlign="center" color="inherit">
            <SpaceBetween size="m">
              <b>Awaiting Gate Events</b>
              <Box variant="p" color="inherit">
                Gates fire during task execution (DoR, Concurrency, Adversarial, Ship Readiness).
              </Box>
            </SpaceBetween>
          </Box>
        </Container>
      )}

      {tasksWithGates.map((task: any) => (
        <div key={task.task_id}>
          <Container
            header={
              <Header variant="h3" description={task.task_id}>
                {task.title}
              </Header>
            }
          >
            <SpaceBetween size="s">
              {task.events
                .filter((e: any) => e.type === 'gate')
                .map((gate: any, idx: number) => (
                  <div key={idx}>
                    <ExpandableSection
                      variant="footer"
                      headerText={
                        <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                          <StatusIndicator type={gate.gate_result === 'pass' ? 'success' : 'error'}>
                            {gate.gate_name || 'Gate'}
                          </StatusIndicator>
                          <Box variant="code" fontSize="body-s">{gate.gate_result?.toUpperCase()}</Box>
                        </SpaceBetween>
                      }
                    >
                      <Box variant="p">{gate.msg}</Box>
                      {gate.criteria && (
                        <Box variant="small" color="text-body-secondary">
                          Criteria: {gate.criteria}
                        </Box>
                      )}
                    </ExpandableSection>
                  </div>
                ))}
            </SpaceBetween>
          </Container>
        </div>
      ))}
    </SpaceBetween>
  );
};
