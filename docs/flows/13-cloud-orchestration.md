# Cloud Orchestration Flow

How ALM webhooks trigger headless agent execution on AWS.

```mermaid
flowchart LR
    subgraph ALM["ALM Platforms"]
        GH["GitHub\nlabel: factory-ready"]
        GL["GitLab\nlabel: factory-ready"]
        AS["Asana\nmove to In Progress"]
    end

    subgraph AWS["AWS Cloud"]
        APIGW["API Gateway\nPOST /webhook/{platform}"]
        EB["EventBridge\nfde-dev-factory-bus"]
        ECS["ECS Fargate\nRunTask"]

        subgraph Agent["Strands Agent Container"]
            ROUTER["Router\nevent → agent"]
            REGISTRY["Registry\n3 agents"]
            RECON["Reconnaissance\nPhase 1"]
            ENG["Engineering\nPhases 2-3"]
            REPORT["Reporting\nPhase 4"]
        end

        BEDROCK["Bedrock\nClaude Sonnet 4.5"]
        S3["S3\nArtifacts"]
    end

    GH -->|webhook| APIGW
    GL -->|webhook| APIGW
    AS -->|webhook| APIGW
    APIGW -->|PutEvents| EB
    EB -->|RunTask| ECS
    ECS --> ROUTER
    ROUTER --> REGISTRY
    REGISTRY --> RECON
    RECON --> ENG
    ENG --> REPORT
    ENG -->|InvokeModel| BEDROCK
    REPORT -->|write results| S3
    REPORT -->|update status| GH
```

## Webhook URLs

After `terraform apply`, the outputs provide webhook URLs:

| Platform | URL Pattern | Configure At |
|----------|------------|-------------|
| GitHub | `https://{api-id}.execute-api.{region}.amazonaws.com/webhook/github` | Repo → Settings → Webhooks |
| GitLab | `https://{api-id}.execute-api.{region}.amazonaws.com/webhook/gitlab` | Project → Settings → Webhooks |
| Asana | `https://{api-id}.execute-api.{region}.amazonaws.com/webhook/asana` | Asana API → Create Webhook |

## Agent Pipeline

| Agent | Phase | Tools | Purpose |
|-------|-------|-------|---------|
| Reconnaissance | 1 | read_spec, run_shell_command | Maps modules, produces intake contract |
| Engineering | 2-3 | read_spec, write_artifact, run_shell_command, ALM tools | Executes engineering recipe |
| Reporting | 4 | write_artifact, ALM tools | Writes completion report, updates ALM |

## E2E Validation

```bash
bash scripts/validate-e2e-cloud.sh --profile profile-name
```

## Teardown

```bash
bash scripts/teardown-fde.sh --terraform
bash scripts/teardown-fde.sh --tags
bash scripts/teardown-fde.sh --dry-run
```

## Related
- ADR: [ADR-009 AWS Cloud Infrastructure](../adr/ADR-009-aws-cloud-infrastructure.md)
- Flow: [12-Staff Engineer Onboarding](12-staff-engineer-onboarding.md)
- Terraform: `infra/terraform/eventbridge.tf`, `infra/terraform/apigateway.tf`
- Agent code: `infra/docker/agents/`
