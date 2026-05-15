/**
 * GoldenSignalsCard — Test Scenarios (TDD: all must fail initially)
 *
 * Tests the 4 Golden Signals of SRE applied to the SDLC:
 * 1. Latency: lead time, pipeline execution time
 * 2. Traffic: throughput, concurrent agents
 * 3. Errors: CFR, failed tasks, dispatch failures
 * 4. Saturation: agent capacity, stuck tasks, queue depth
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import { GoldenSignalsCard } from './GoldenSignalsCard';

describe('GoldenSignalsCard', () => {
  // ─── Rendering ────────────────────────────────────────────────

  it('should not render when no metrics data is provided', () => {
    const { container } = render(<GoldenSignalsCard metrics={null} health={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('should render the card header with "Golden Signals" title', () => {
    render(<GoldenSignalsCard metrics={mockMetrics} health={mockHealth} />);
    expect(screen.getByText('Golden Signals')).toBeInTheDocument();
  });

  // ─── Signal 1: Latency ────────────────────────────────────────

  it('should display lead time in human-readable format (minutes/hours)', () => {
    render(<GoldenSignalsCard metrics={mockMetrics} health={mockHealth} />);
    expect(screen.getByText('Latency')).toBeInTheDocument();
    // 2188182ms = 36.5 min
    expect(screen.getByText(/36\.5/)).toBeInTheDocument();
  });

  it('should show latency status as success when lead time < 15min', () => {
    const fastMetrics = { ...mockMetrics, avg_duration_ms: 600000 }; // 10 min
    render(<GoldenSignalsCard metrics={fastMetrics} health={mockHealth} />);
    expect(screen.getByTestId('latency-status')).toHaveAttribute('data-status', 'success');
  });

  it('should show latency status as warning when lead time 15-60min', () => {
    render(<GoldenSignalsCard metrics={mockMetrics} health={mockHealth} />);
    // 36.5 min = warning
    expect(screen.getByTestId('latency-status')).toHaveAttribute('data-status', 'warning');
  });

  it('should show latency status as error when lead time > 60min', () => {
    const slowMetrics = { ...mockMetrics, avg_duration_ms: 7200000 }; // 120 min
    render(<GoldenSignalsCard metrics={slowMetrics} health={mockHealth} />);
    expect(screen.getByTestId('latency-status')).toHaveAttribute('data-status', 'error');
  });

  // ─── Signal 2: Traffic ────────────────────────────────────────

  it('should display throughput (tasks completed in 24h)', () => {
    render(<GoldenSignalsCard metrics={mockMetrics} health={mockHealth} />);
    expect(screen.getByText('Traffic')).toBeInTheDocument();
    expect(screen.getByText('1 tasks/24h')).toBeInTheDocument();
  });

  it('should display active agents count', () => {
    render(<GoldenSignalsCard metrics={mockMetrics} health={mockHealth} />);
    expect(screen.getByText('0 active agents')).toBeInTheDocument();
  });

  // ─── Signal 3: Errors ─────────────────────────────────────────

  it('should display change failure rate (CFR)', () => {
    render(<GoldenSignalsCard metrics={mockMetrics} health={mockHealth} />);
    expect(screen.getByText('Errors')).toBeInTheDocument();
    expect(screen.getByText(/0%.*CFR/)).toBeInTheDocument();
  });

  it('should display failed tasks count', () => {
    render(<GoldenSignalsCard metrics={mockMetrics} health={mockHealth} />);
    expect(screen.getByText('0 failed (24h)')).toBeInTheDocument();
  });

  it('should display dispatch stuck count when > 0', () => {
    const stuckMetrics = { ...mockMetrics, dispatch_stuck: 3 };
    render(<GoldenSignalsCard metrics={stuckMetrics} health={mockHealth} />);
    expect(screen.getByText('3 dispatch blocked')).toBeInTheDocument();
  });

  it('should show error status when CFR > 15%', () => {
    const highCfrMetrics = { ...mockMetrics, dora: { ...mockMetrics.dora, change_failure_rate_pct: 25 } };
    render(<GoldenSignalsCard metrics={highCfrMetrics} health={mockHealth} />);
    expect(screen.getByTestId('errors-status')).toHaveAttribute('data-status', 'error');
  });

  // ─── Signal 4: Saturation ─────────────────────────────────────

  it('should display agent capacity percentage', () => {
    render(<GoldenSignalsCard metrics={mockMetrics} health={mockHealth} />);
    expect(screen.getByText('Saturation')).toBeInTheDocument();
    expect(screen.getByText('0% capacity')).toBeInTheDocument();
  });

  it('should display stuck tasks from health checks', () => {
    const stuckHealth = {
      ...mockHealth,
      checks: [
        ...mockHealth.checks.filter((c: any) => c.name !== 'stuck_tasks'),
        { name: 'stuck_tasks', status: 'warn', detail: '2 task(s) running >30min without update' },
      ],
    };
    render(<GoldenSignalsCard metrics={mockMetrics} health={stuckHealth} />);
    expect(screen.getByText(/2.*stuck/i)).toBeInTheDocument();
  });

  it('should show saturation status as error when capacity > 80%', () => {
    const saturatedMetrics = { ...mockMetrics, active_agents: 9 };
    const saturatedHealth = {
      ...mockHealth,
      checks: mockHealth.checks.map((c: any) =>
        c.name === 'agent_capacity' ? { ...c, status: 'warn', detail: '9/10 agents active (90% capacity)' } : c
      ),
    };
    render(<GoldenSignalsCard metrics={saturatedMetrics} health={saturatedHealth} />);
    expect(screen.getByTestId('saturation-status')).toHaveAttribute('data-status', 'error');
  });

  // ─── Overall Health ───────────────────────────────────────────

  it('should show overall signal health badge (green when all signals healthy)', () => {
    const healthyMetrics = {
      ...mockMetrics,
      avg_duration_ms: 300000, // 5 min (fast)
      dora: { ...mockMetrics.dora, change_failure_rate_pct: 0 },
    };
    render(<GoldenSignalsCard metrics={healthyMetrics} health={mockHealth} />);
    expect(screen.getByTestId('overall-health')).toHaveAttribute('data-status', 'success');
  });

  it('should show overall signal health badge (red when any signal is error)', () => {
    const badMetrics = { ...mockMetrics, avg_duration_ms: 7200000 }; // 120 min
    render(<GoldenSignalsCard metrics={badMetrics} health={mockHealth} />);
    expect(screen.getByTestId('overall-health')).toHaveAttribute('data-status', 'error');
  });
});

// ─── Mock Data ──────────────────────────────────────────────────

const mockMetrics = {
  active: 0,
  completed_24h: 1,
  failed_24h: 0,
  avg_duration_ms: 2188182, // 36.5 min
  active_agents: 0,
  idle_agents: 28,
  stale_agents: 1,
  dispatch_stuck: 0,
  dispatch_stuck_task_ids: [],
  total_agents_provisioned: 29,
  dora: {
    lead_time_avg_ms: 2188182,
    success_rate_pct: 76,
    throughput_24h: 1,
    change_failure_rate_pct: 0,
    level: 'Medium',
  },
};

const mockHealth = {
  status: 'healthy',
  checks: [
    { name: 'task_queue_table', status: 'pass', detail: 'Accessible' },
    { name: 'agent_lifecycle_table', status: 'pass', detail: 'Accessible' },
    { name: 'stuck_tasks', status: 'pass', detail: 'No stuck tasks' },
    { name: 'dead_letters', status: 'pass', detail: 'No recent dead letters' },
    { name: 'agent_capacity', status: 'pass', detail: '0/10 agents active (0% capacity)' },
  ],
};
