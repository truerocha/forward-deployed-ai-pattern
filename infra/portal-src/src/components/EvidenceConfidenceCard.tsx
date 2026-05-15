/**
 * EvidenceConfidenceCard — ADR-034 Feature 6
 * Shows tiered evidence resolution breakdown.
 * Personas: Architect, Staff
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import Badge from '@cloudscape-design/components/badge';
import Box from '@cloudscape-design/components/box';
import ProgressBar from '@cloudscape-design/components/progress-bar';
import SpaceBetween from '@cloudscape-design/components/space-between';

interface TierInfo {
  name: string;
  range: string;
  count: number;
}

export interface EvidenceConfidenceData {
  totalEvidence: number;
  totalFindings: number;
  highConfidenceRatio: number;
  tiers: TierInfo[];
}

const SYNTHETIC_DATA: EvidenceConfidenceData = {
  totalEvidence: 89,
  totalFindings: 23,
  highConfidenceRatio: 0.74,
  tiers: [
    { name: 'Explicit (Tier 0)', range: '0.90-1.00', count: 52 },
    { name: 'Composite (Tier 0b)', range: '0.75-0.89', count: 14 },
    { name: 'Inferred (Tier 1)', range: '0.50-0.74', count: 17 },
    { name: 'Transitive (Tier 2)', range: '0.30-0.49', count: 6 },
  ],
};

interface EvidenceConfidenceCardProps {
  data?: EvidenceConfidenceData;
}

export const EvidenceConfidenceCard: React.FC<EvidenceConfidenceCardProps> = ({ data }) => {
  const d = data || SYNTHETIC_DATA;
  const badgeColor = d.highConfidenceRatio >= 0.7 ? 'green' : d.highConfidenceRatio >= 0.5 ? 'blue' : 'red';

  return (
    <Container
      header={
        <Header
          variant="h3"
          description="Resolution tier breakdown"
          actions={
            <Badge color={badgeColor}>
              {Math.round(d.highConfidenceRatio * 100)}% HIGH CONFIDENCE
            </Badge>
          }
        >
          Evidence Confidence
        </Header>
      }
      footer={
        <Box fontSize="body-s" color="text-body-secondary">
          {d.totalEvidence} evidence records | {d.totalFindings} findings
        </Box>
      }
    >
      <SpaceBetween size="s">
        {d.tiers.map((tier) => (
          <div key={tier.name}>
            <Box variant="awsui-key-label">{tier.name} ({tier.range})</Box>
            <ProgressBar
              value={(tier.count / d.totalEvidence) * 100}
              additionalInfo={`${tier.count} records`}
            />
          </div>
        ))}
      </SpaceBetween>
    </Container>
  );
};
