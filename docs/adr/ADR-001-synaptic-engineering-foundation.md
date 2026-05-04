# ADR-001: Synaptic Engineering as Design Foundation

## Status
Accepted

## Context
The Autonomous Code Factory requires a coherent set of design principles that govern decisions across all layers — from work intake through delivery. Without a unifying framework, individual components optimize locally but create systemic incoherence.

## Decision
This design adopts Synaptic Engineering as the foundational design philosophy. Four neuro-inspired principles govern all architectural decisions:

1. **Neurons**: Every component has rigid input/output contracts
2. **Synaptic Cleft**: Context transmission between components is clean and minimal
3. **Neural Plasticity**: Successful patterns strengthen, unused patterns decay
4. **Executive Function**: Human decides WHAT/WHY, agent decides HOW

## Consequences
- Every new hook, steering, or feature must map to one of the four principles
- Context loading is minimal by default (manual steering inclusion, not auto)
- Notes system includes date-based decay (90-day archival without PINNED tag)
- The human remains the decision-maker for scope and priority; the agent handles implementation
