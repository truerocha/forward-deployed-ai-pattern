export type AgentRole = 'planner' | 'coder' | 'reviewer' | 'deployer';

export type AgentStatus = 'idle' | 'intake' | 'provisioning' | 'setup' | 'thinking' | 'working' | 'complete' | 'error';

export interface Agent {
  id: string;
  name: string;
  role: AgentRole;
  status: AgentStatus;
  lastMessage?: string;
  progress?: number; 
  cpuUsage?: number;
  memoryUsage?: number;
}

export interface LogEntry {
  id: string;
  timestamp: string;
  agentId: string;
  agentName: string;
  message: string;
  type: 'info' | 'thought' | 'action' | 'error' | 'working' | 'complete' | 'system';
  _sortKey?: string;
}

export interface SoftwareFactoryState {
  isProcessing: boolean;
  currentStep: number;
  totalSteps: number;
  logs: LogEntry[];
  agents: Agent[];
  output?: string;
}

export type AppView = 'pipeline' | 'agents' | 'reasoning' | 'gates' | 'health' | 'registries';
