export type AgentRole = 'planner' | 'coder' | 'reviewer' | 'deployer' | 'architect' | 'adversarial' | 'fidelity' | 'tech-lead' | 'reporting';

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
  subtask?: string;
  modelTier?: string;
  stageIndex?: number;
  totalStages?: number;
  topology?: string;
  paradigm?: string;
  designQuality?: number;
  durationSeconds?: number;
  // Synapse 6: Transparency metrics
  reasoningDivergence?: number;
  heartbeatPhase?: string;
  transparencyProbeCount?: number;
  // Synapse 7: Ownership & ancestry
  goalAncestryDepth?: number;
  executionMode?: 'standard' | 'heartbeat';
}

export interface LogEntry {
  id: string;
  timestamp: string;
  agentId: string;
  agentName: string;
  message: string;
  type: 'info' | 'thought' | 'action' | 'error' | 'working' | 'complete' | 'system';
  phase?: string;
  gateName?: string;
  gateResult?: string;
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

export type AppView = 'pipeline' | 'agents' | 'reasoning' | 'gates' | 'health' | 'registries' | 'cost' | 'observability' | 'history' | 'a2a';
