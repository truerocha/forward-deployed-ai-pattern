/**
 * RegistriesView — Infrastructure Registries using Cloudscape Container + KeyValuePairs.
 */
import React from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import Badge from '@cloudscape-design/components/badge';

import factoryConfig from '../factory-config.json';
import { useTranslation } from 'react-i18next';

export const RegistriesView: React.FC = () => {
  const { t } = useTranslation();

  return (
    <SpaceBetween size="l">
      <Header
        variant="h2"
        description={t('registries.subtitle')}
      >
        {t('registries.title')}
      </Header>

      <Container
        header={<Header variant="h3">Factory Configuration</Header>}
      >
        <KeyValuePairs
          columns={2}
          items={[
            { label: 'Project ID', value: <Box variant="code">{factoryConfig.project_id}</Box> },
            { label: 'Region', value: factoryConfig.region },
            { label: 'Environment', value: <Badge color="blue">{factoryConfig.environment}</Badge> },
            { label: 'ALM Integrations', value: (factoryConfig.alm_integrations || []).join(', ') },
          ]}
        />
      </Container>

      <Container
        header={<Header variant="h3">Infrastructure Endpoints</Header>}
      >
        <KeyValuePairs
          columns={2}
          items={[
            { label: 'API Endpoint', value: <Box variant="code">{factoryConfig.api_endpoint || '(not configured)'}</Box> },
            { label: 'Artifacts Bucket', value: <Box variant="code">{factoryConfig.artifacts_bucket || '(not configured)'}</Box> },
            { label: 'VPC', value: <Box variant="code">{factoryConfig.vpc || '(not configured)'}</Box> },
            { label: 'Distribution', value: <Box variant="code">{factoryConfig.distribution || '(not configured)'}</Box> },
          ]}
        />
      </Container>
    </SpaceBetween>
  );
};
