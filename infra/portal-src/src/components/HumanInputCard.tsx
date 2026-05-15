/**
 * HumanInputCard — Human-in-the-Loop interaction.
 * Pattern: Cloudscape Container shell + Cloudscape form components.
 */
import React, { useState, useEffect, useCallback } from 'react';
import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Box from '@cloudscape-design/components/box';
import SpaceBetween from '@cloudscape-design/components/space-between';
import StatusIndicator from '@cloudscape-design/components/status-indicator';
import Button from '@cloudscape-design/components/button';
import Textarea from '@cloudscape-design/components/textarea';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import Badge from '@cloudscape-design/components/badge';
import Tiles from '@cloudscape-design/components/tiles';

interface HumanInputRequest {
  question: string;
  context: string;
  options?: string[];
  timeout_seconds: number;
  request_id: string;
}

interface HumanInputCardProps {
  request?: HumanInputRequest | null;
  onRespond: (requestId: string, response: string) => void;
}

export const HumanInputCard: React.FC<HumanInputCardProps> = ({ request, onRespond }) => {
  const [selectedOption, setSelectedOption] = useState<string>('');
  const [freeText, setFreeText] = useState('');
  const [remainingSeconds, setRemainingSeconds] = useState(0);

  useEffect(() => {
    if (!request) return;
    setRemainingSeconds(request.timeout_seconds);
    setSelectedOption(''); setFreeText('');
    const interval = setInterval(() => {
      setRemainingSeconds((prev) => { if (prev <= 1) { clearInterval(interval); return 0; } return prev - 1; });
    }, 1000);
    return () => clearInterval(interval);
  }, [request]);

  const handleSubmit = useCallback(() => {
    if (!request) return;
    const response = selectedOption || freeText;
    if (response.trim()) onRespond(request.request_id, response.trim());
  }, [request, selectedOption, freeText, onRespond]);

  const timeoutPercent = request ? (remainingSeconds / request.timeout_seconds) * 100 : 0;
  const isUrgent = remainingSeconds > 0 && remainingSeconds <= 30;
  const isExpired = remainingSeconds === 0 && request !== null && request !== undefined;

  if (!request) {
    return (<Container header={<Header variant="h3">Human-in-the-Loop</Header>}><Box textAlign="center" padding="l" color="inherit"><StatusIndicator type="pending">No pending requests</StatusIndicator></Box></Container>);
  }

  return (
    <Container
      header={<Header variant="h3" description={`Request: ${request.request_id}`} actions={<Badge color={isExpired ? 'red' : isUrgent ? 'red' : 'blue'}>{isExpired ? 'EXPIRED' : `${Math.floor(remainingSeconds / 60)}:${(remainingSeconds % 60).toString().padStart(2, '0')}`}</Badge>}>Agent Needs Input</Header>}
      footer={<Box fontSize="body-s" color="text-body-secondary">Request ID: {request.request_id}</Box>}
    >
      <SpaceBetween size="m">
        <ProgressBar value={timeoutPercent} variant="standalone" status={isUrgent || isExpired ? 'error' : undefined} additionalInfo={isExpired ? 'Timed out — agent will use default' : undefined} />
        <div><Box fontWeight="bold">{request.question}</Box>{request.context && <Box fontSize="body-s" color="text-body-secondary">{request.context}</Box>}</div>
        {request.options && request.options.length > 0 && (
          <Tiles value={selectedOption} onChange={({ detail }) => setSelectedOption(detail.value)} items={request.options.map((opt) => ({ value: opt, label: opt }))} columns={1} />
        )}
        {(!request.options || request.options.length === 0) && (
          <Textarea value={freeText} onChange={({ detail }) => setFreeText(detail.value)} disabled={isExpired} placeholder="Type your response…" rows={3} />
        )}
        {isExpired && <StatusIndicator type="error">Request timed out — agent will use default</StatusIndicator>}
        <Button variant="primary" onClick={handleSubmit} disabled={isExpired || (!selectedOption && !freeText.trim())} iconName="send">Respond</Button>
      </SpaceBetween>
    </Container>
  );
};
