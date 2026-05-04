# ADR-004: Circuit Breaker for Error Classification

## Status
Accepted

## Context
When a test or build command does not succeed, the agent's default behavior is to modify source code and retry. If the root cause is an infrastructure issue (port in use, Docker not running, expired credentials), the agent destroys correct code trying to fix an environment problem. This is SPOF 3 (Token Burner Loop).

## Decision
This design implements a Circuit Breaker as a postToolUse hook on shell commands that:
1. Reads only the last 40 lines of stderr (context trimming)
2. Classifies the error as CODE or ENVIRONMENT using keyword matching
3. If ENVIRONMENT: stops immediately, does not touch source code, reports to human
4. If CODE: allows up to 3 attempts with the same approach, then requires a different approach
5. After 3 different approaches with no resolution: rolls back all changes and reports

## Consequences
- Infrastructure issues no longer cause cascading code destruction
- Token consumption is bounded (max 3 attempts per approach, max 3 approaches)
- The human is notified of environment issues that require manual intervention
- Context trimming (40 lines) prevents stack trace pollution of the context window
