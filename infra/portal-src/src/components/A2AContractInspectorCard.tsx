/**
 * A2AContractInspectorCard — Pydantic contract validation and payload inspection.
 *
 * Provides deep debugging for Engineers investigating data contract violations
 * between A2A agents. Shows input/output JSON payloads with syntax highlighting,
 * Pydantic validation errors with stack traces, and task lifecycle tracking.
 *
 * Persona: Engineer, Staff Engineer
 * Data Source: DynamoDB workflow state (ContextoWorkflow) + OTel span attributes
 */
import React, { useState, useEffect, useCallback } from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Badge from '@cloudscape-design/components/badge';
import Tabs from '@cloudscape-design/components/tabs';
import Cards from '@cloudscape-design/components/cards';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import Alert from '@cloudscape-design/components/alert';
import Button from '@cloudscape-design/components/button';
import Grid from '@cloudscape-design/components/grid';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import TokenGroup from '@cloudscape-design/components/token-group';

interface WorkflowStep {
  id: string;
  agentName: string;
  task: string;
  latencyMs: number;
  status: 'SUCCESS' | 'FAILED' | 'IN_PROGRESS' | 'SKIPPED';
  input: Record<string, any>;
  output: Record<string, any>;
  tools?: string[];
}

interface ErrorDetails {
  node: string;
  message: string;
  schemaViolated: string;
  trace: string;
  classification?: string;
}

interface WorkflowTelemetry {
  workflowId: string;
  status: string;
  noAtual: string;
  timestamp: string;
  retries: number;
  maxRetries: number;
  errorDetails?: ErrorDetails;
  steps: WorkflowStep[];
}

interface A2AContractInspectorCardProps {
  apiUrl?: string;
  pollingIntervalMs?: number;
  initialData?: WorkflowTelemetry;
}

const statusTypeMap: Record<string, 'success' | 'error' | 'in-progress' | 'stopped'> = {
  SUCCESS: 'success',
  FAILED: 'error',
  IN_PROGRESS: 'in-progress',
  SKIPPED: 'stopped',
};

export const A2AContractInspectorCard: React.FC<A2AContractInspectorCardProps> = ({
  apiUrl = '',
  pollingIntervalMs = 5000,
  initialData,
}) => {
  const [workflowState, setWorkflowState] = useState<WorkflowTelemetry | null>(initialData || null);
  const [loading, setLoading] = useState(!initialData);
  const [errorAlert, setErrorAlert] = useState<string | null>(null);

  const fetchTelemetry = useCallback(async () => {
    if (!apiUrl) {
      setLoading(false);
      return;
    }

    try {
      const res = await fetch(`${apiUrl}/status/a2a/latest`);
      if (res.ok) {
        const data = await res.json();
        setWorkflowState(data);
        setErrorAlert(null);
      }
    } catch (err) {
      setErrorAlert('Failed to fetch A2A telemetry from API');
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  useEffect(() => {
    if (!apiUrl) return;
    fetchTelemetry();
    const interval = setInterval(fetchTelemetry, pollingIntervalMs);
    return () => clearInterval(interval);
  }, [fetchTelemetry, pollingIntervalMs, apiUrl]);

  if (loading) {
    return (
      <Container>
        <Box padding="xl" textAlign="center">
          <StatusIndicator type="loading">Loading A2A telemetry...</StatusIndicator>
        </Box>
      </Container>
    );
  }

  if (!workflowState) {
    return (
      <Container
        header={<Header variant="h3">Contract Inspector</Header>}
      >
        <Box textAlign="center" padding="l" color="text-status-inactive">
          No active A2A workflow. Data appears when workflows execute.
        </Box>
      </Container>
    );
  }

  const isContractError = workflowState.status?.includes('CONTRACT') || workflowState.status?.includes('VALIDATION');

  return (
    <SpaceBetween size="m">
      {/* Contract violation alert */}
      {isContractError && workflowState.errorDetails && (
        <Alert
          type="error"
          header="Data Contract Violation (A2A)"
          dismissible={false}
          action={<Button variant="primary" onClick={fetchTelemetry}>Refresh</Button>}
        >
          Node <strong>{workflowState.errorDetails.node}</strong> failed to serialize response.
          Schema <strong>{workflowState.errorDetails.schemaViolated}</strong> has missing required fields.
        </Alert>
      )}

      {errorAlert && <Alert type="warning">{errorAlert}</Alert>}

      {/* Workflow metadata header */}
      <Container
        header={
          <Header
            variant="h3"
            description={`Workflow: ${workflowState.workflowId}`}
            info={
              <SpaceBetween direction="horizontal" size="xs">
                <Badge color={workflowState.retries > 0 ? 'red' : 'green'}>
                  Retries: {workflowState.retries}/{workflowState.maxRetries}
                </Badge>
                <StatusIndicator type={isContractError ? 'error' : 'success'}>
                  {workflowState.status}
                </StatusIndicator>
              </SpaceBetween>
            }
          >
            Contract Inspector
          </Header>
        }
      >
        <Grid gridDefinition={[{ colspan: 4 }, { colspan: 4 }, { colspan: 4 }]}>
          <div>
            <Box variant="awsui-key-label">Current Node</Box>
            <Box variant="p">{workflowState.noAtual}</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Last Update</Box>
            <Box variant="p">{new Date(workflowState.timestamp).toLocaleTimeString()}</Box>
          </div>
          <div>
            <Box variant="awsui-key-label">Resilience</Box>
            <Box variant="p">DynamoDB Checkpoint + SQS DLQ</Box>
          </div>
        </Grid>
      </Container>

      {/* Task lifecycle cards with payload inspection */}
      <Container
        header={<Header variant="h3">Task Lifecycle (A2A Steps)</Header>}
      >
        <Cards
          cardDefinition={{
            header: (item: WorkflowStep) => (
              <SpaceBetween direction="horizontal" size="xs">
                <StatusIndicator type={statusTypeMap[item.status] || 'pending'}>
                  {item.agentName}
                </StatusIndicator>
                <Badge color="grey">{item.latencyMs}ms</Badge>
              </SpaceBetween>
            ),
            sections: [
              {
                id: 'task',
                header: 'Task',
                content: (item: WorkflowStep) => item.task,
              },
              {
                id: 'tools',
                header: 'Tools Invoked',
                content: (item: WorkflowStep) =>
                  item.tools && item.tools.length > 0 ? (
                    <TokenGroup
                      items={item.tools.map((t) => ({ label: t, dismissLabel: '' }))}
                      readOnly
                    />
                  ) : (
                    <Box color="text-status-inactive">No tools</Box>
                  ),
              },
              {
                id: 'payloads',
                header: 'Contract Payloads',
                content: (item: WorkflowStep) => (
                  <Tabs
                    tabs={[
                      {
                        label: 'Input',
                        id: `input-${item.id}`,
                        content: (
                          <Box padding="xs">
                            <pre style={{
                              backgroundColor: 'var(--color-background-code-default, #f4f4f4)',
                              padding: '8px',
                              borderRadius: '4px',
                              overflowX: 'auto',
                              fontSize: '12px',
                              maxHeight: '200px',
                            }}>
                              {JSON.stringify(item.input, null, 2)}
                            </pre>
                          </Box>
                        ),
                      },
                      {
                        label: 'Output',
                        id: `output-${item.id}`,
                        content: (
                          <Box padding="xs">
                            <pre style={{
                              backgroundColor: item.status === 'FAILED'
                                ? 'var(--color-background-status-error, #fdf3f2)'
                                : 'var(--color-background-code-default, #f4f4f4)',
                              padding: '8px',
                              borderRadius: '4px',
                              overflowX: 'auto',
                              fontSize: '12px',
                              maxHeight: '200px',
                            }}>
                              {JSON.stringify(item.output, null, 2)}
                            </pre>
                          </Box>
                        ),
                      },
                    ]}
                  />
                ),
              },
            ],
          }}
          items={workflowState.steps}
          loadingText="Loading steps..."
          empty={<Box textAlign="center">No steps executed yet.</Box>}
        />
      </Container>

      {/* Stack trace for contract errors */}
      {workflowState.errorDetails && (
        <ExpandableSection
          headerText="Error Stack Trace (Pydantic Validation)"
          variant="container"
        >
          <SpaceBetween size="s">
            <KeyValuePairs
              columns={3}
              items={[
                { label: 'Node', value: workflowState.errorDetails.node },
                { label: 'Schema', value: workflowState.errorDetails.schemaViolated },
                { label: 'Classification', value: workflowState.errorDetails.classification || 'CONTRACT' },
              ]}
            />
            <Box padding="xs">
              <pre style={{
                color: '#d13212',
                backgroundColor: 'var(--color-background-status-error, #fdf3f2)',
                padding: '12px',
                borderRadius: '4px',
                fontFamily: 'monospace',
                fontSize: '12px',
                overflowX: 'auto',
                whiteSpace: 'pre-wrap',
              }}>
                {workflowState.errorDetails.trace}
              </pre>
            </Box>
          </SpaceBetween>
        </ExpandableSection>
      )}
    </SpaceBetween>
  );
};
