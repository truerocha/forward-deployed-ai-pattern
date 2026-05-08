# Quickstart — Deploy the Code Factory in 15 Minutes

> Target audience: New teams adopting the Forward Deployed AI Pattern.
> Profile: Starter (6 hooks, minimal overhead, core governance).
> Prerequisites: AWS account, Terraform >= 1.5, Docker, Git.

---

## Step 1: Clone and Configure (2 min)

```bash
git clone <your-repo-url>
cd forward-deployed-ai-pattern

# Copy and edit the Terraform variables
cp infra/terraform/factory.tfvars.example infra/terraform/factory.tfvars
# Edit factory.tfvars: set aws_region, environment, bedrock_model_id
```

## Step 2: Deploy Infrastructure (5 min)

```bash
cd infra/terraform
terraform init
terraform plan -var-file="factory.tfvars"
terraform apply -var-file="factory.tfvars"
```

This deploys:
- ECS Fargate cluster for agent execution
- ECR repository for agent Docker images
- DynamoDB tables (SCD, context hierarchy, metrics, memory, organism, knowledge)
- EFS for shared agent workspaces
- S3 bucket for artifacts
- IAM roles with least-privilege policies

## Step 3: Build and Push Agent Image (3 min)

```bash
# Get ECR login
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com

# Build the agent image
docker build -f infra/docker/Dockerfile.strands-agent -t fde-strands-agent .

# Tag and push
docker tag fde-strands-agent:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/fde-dev-strands-agent:latest
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/fde-dev-strands-agent:latest
```

## Step 4: Activate Starter Profile (2 min)

```bash
# From repo root — activates the 6 essential hooks
make profile LEVEL=starter
```

The starter profile includes:
| Hook | What It Does |
|------|-------------|
| `fde-dor-gate` | Validates task readiness before execution |
| `fde-adversarial-gate` | Challenges every write operation |
| `fde-dod-gate` | Validates completion against quality standards |
| `fde-pipeline-validation` | Ensures data travels correctly through pipeline |
| `fde-test-immutability` | Prevents test weakening to pass |
| `fde-circuit-breaker` | Classifies errors as CODE vs ENVIRONMENT |

## Step 5: Run Smoke Test (3 min)

```bash
# Verify the factory can dispatch and complete a task
python3 -m pytest tests/integration/test_distributed_orchestration.py -v
```

---

## What's Next?

### Upgrade to Standard Profile (when maturity score > 40)

```bash
make profile LEVEL=standard
```

Adds: branch evaluation, ship readiness, work intake, prompt refinement, notes consolidation, doc gardening.

### Upgrade to Full Profile (when maturity score > 70)

```bash
make profile LEVEL=full
```

Adds: alternative exploration, golden principles, enterprise backlog/docs/release, repo onboarding.

### Key Concepts

- **Autonomy Levels (L1-L5)**: How much the factory can do without human intervention. Starts at L3 (recommended for new teams).
- **Anti-Instability Loop**: Automatically reduces autonomy if Change Fail Rate rises. Starts in observe-only mode for 30 days.
- **DORA Metrics**: Lead time, deploy frequency, CFR, and MTTR tracked per autonomy level.
- **Cost Tracking**: Every Bedrock invocation tracked. Alert at $2.00/task (configurable).

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTI_INSTABILITY_OBSERVE_ONLY` | `true` | Set to `false` after 30-day baseline |
| `METRICS_TABLE` | `fde-dev-metrics` | DynamoDB table for all metrics |
| `MAX_CONCURRENT_AGENTS` | `6` | Max parallel agents per stage |
| `STAGE_TIMEOUT_SECONDS` | `600` | Max time per pipeline stage |

### Documentation

- Architecture: `docs/architecture/design-document.md`
- ADRs: `docs/adr/ADR-*.md`
- Operations: `docs/operations/`
- Development plan: `docs/design/fde-core-brain-development.md`

---

*Total setup time: ~15 minutes. The factory is now ready to receive work items.*
