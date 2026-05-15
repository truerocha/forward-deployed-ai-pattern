/**
 * RegistriesView — Infrastructure Registries using live API data from /status/registries.
 * No longer reads from static factory-config.json for infrastructure endpoints.
 */
import React, { useState, useEffect } from 'react';

import Container from '@cloudscape-design/components/container';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';
import KeyValuePairs from '@cloudscape-design/components/key-value-pairs';
import Badge from '@cloudscape-design/components/badge';
import StatusIndicator from '@cloudscape-design/components/status-indicator';

import factoryConfig from '../factory-config.json';
import { useTranslation } from 'react-i18next';

export const RegistriesView: React.FC = () => {
  const { t } = useTranslation();
  const [registries, setRegistries] = useState<any>(null);
  const API_URL = document.querySelector('meta[name="factory-api-url"]')?.getAttribute('content') || '';

  useEffect(() => {
    if (!API_URL) return;
    fetch(`${API_URL}/status/registries`)
      .then((res) => res.ok ? res.json() : null)
      .then((data) => setRegistries(data))
      .catch(() => {});
  }, [API_URL]);

  // Derive infrastructure endpoints from live registries data
  const infraItems = registries?.infrastructure || [];
  const dataPlane = registries?.data_plane || [];

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
            { label: 'Region', value: registries?.region || factoryConfig.region },
            { label: 'Environment', value: <Badge color="blue">{registries?.environment || factoryConfig.environment}</Badge> },
            { label: 'ALM Integrations', value: (factoryConfig.alm_integrations || []).join(', ') },
          ]}
        />
      </Container>

      <Container
        header={<Header variant="h3">Infrastructure</Header>}
      >
        {infraItems.length > 0 ? (
          <SpaceBetween size="s">
            {infraItems.map((item: any, idx: number) => (
              <div key={idx}>
                <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                  <StatusIndicator type={item.status === 'ready' ? 'success' : 'warning'}>
                    {item.name}
                  </StatusIndicator>
                  <Badge color="grey">{item.version}</Badge>
                  <Box variant="small" color="text-body-secondary">{item.details}</Box>
                </SpaceBetween>
              </div>
            ))}
          </SpaceBetween>
        ) : (
          <Box textAlign="center" color="inherit" padding="l">
            <StatusIndicator type="pending">Loading infrastructure data...</StatusIndicator>
          </Box>
        )}
      </Container>

      <Container
        header={<Header variant="h3">Data Plane</Header>}
      >
        {dataPlane.length > 0 ? (
          <SpaceBetween size="s">
            {dataPlane.map((item: any, idx: number) => (
              <div key={idx}>
                <SpaceBetween direction="horizontal" size="xs" alignItems="center">
                  <StatusIndicator type={item.status === 'ready' ? 'success' : 'warning'}>
                    {item.name}
                  </StatusIndicator>
                  <Box variant="small" color="text-body-secondary">{item.details}</Box>
                </SpaceBetween>
              </div>
            ))}
          </SpaceBetween>
        ) : (
          <Box textAlign="center" color="inherit" padding="l">
            <StatusIndicator type="pending">Loading data plane status...</StatusIndicator>
          </Box>
        )}
      </Container>
    </SpaceBetween>
  );
};
