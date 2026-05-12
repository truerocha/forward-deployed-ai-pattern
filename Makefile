# Makefile — Forward Deployed AI Pattern

.PHONY: setup-hooks mirror mirror-dry-run profile

setup-hooks:
	@echo "Installing git hooks..."
	@cp scripts/hooks/pre-push .git/hooks/pre-push
	@chmod +x .git/hooks/pre-push
	@echo "✅ pre-push hook installed"

profile:
	@if [ -z "$(LEVEL)" ]; then echo "Usage: make profile LEVEL=starter|standard|full"; exit 1; fi
	@if [ ! -f ".kiro/profiles/$(LEVEL).json" ]; then echo "❌ Profile '$(LEVEL)' not found"; exit 1; fi
	@echo "Activating profile: $(LEVEL)"
	@HOOKS=$$(python3 -c "import json; print(' '.join(json.load(open('.kiro/profiles/$(LEVEL).json'))['hooks']))"); \
	for hook in .kiro/hooks/*.kiro.hook; do \
		name=$$(basename "$$hook" .kiro.hook); \
		if echo "$$HOOKS" | grep -qw "$$name"; then \
			echo "  ✅ $$name (active)"; \
		else \
			echo "  ⏸️  $$name (inactive in $(LEVEL) profile)"; \
		fi; \
	done
	@echo ""
	@echo "Profile '$(LEVEL)' activated. See docs/quickstart.md for next steps."

mirror:
	@bash scripts/mirror-push.sh

mirror-dry-run:
	@bash scripts/mirror-push.sh --dry-run

# ─── Portal / Dashboard ─────────────────────────────────────────

.PHONY: portal-build portal-deploy portal-deploy-build

portal-build:
	@echo "Building portal from source..."
	@cd infra/portal-src && npm run build
	@rm -rf infra/dashboard/assets
	@cp -r infra/portal-src/dist/assets infra/dashboard/assets
	@cp infra/portal-src/dist/index.html infra/dashboard/index.html
	@echo "✅ Portal built → infra/dashboard/"

portal-deploy:
	@bash scripts/deploy-dashboard.sh

portal-deploy-build:
	@bash scripts/deploy-dashboard.sh --build

# ─── Docker / ECS Agent Images ───────────────────────────────────

# ECR URL is resolved from Terraform outputs (no hardcoding)
ECR_URL := $(shell terraform -chdir=infra/terraform output -raw ecr_repository_url 2>/dev/null)
AWS_REGION ?= us-east-1
AWS_PROFILE ?= $(shell echo $${AWS_PROFILE:-default})
export AWS_PROFILE

.PHONY: docker-login docker-build docker-build-adot docker-push-all docker-deploy

docker-login:
	@aws ecr get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(ECR_URL)

docker-build: docker-login
	@echo "Building strands-agent for linux/amd64..."
	docker buildx build --platform linux/amd64 \
		-t $(ECR_URL):latest \
		-f infra/docker/Dockerfile.strands-agent --push .
	@echo "✅ strands-agent:latest pushed (linux/amd64)"

docker-build-adot: docker-login
	@echo "Building ADOT sidecar for linux/amd64..."
	@echo 'FROM --platform=linux/amd64 public.ecr.aws/aws-observability/aws-otel-collector:v0.40.0' | \
		docker buildx build --platform linux/amd64 \
		-t $(ECR_URL):adot-v0.40.0 --push -
	@echo "✅ adot-v0.40.0 pushed (linux/amd64)"

docker-build-onboarding: docker-login
	@echo "Building onboarding-agent for linux/amd64..."
	docker buildx build --platform linux/amd64 \
		-t $(shell terraform -chdir=infra/terraform output -raw onboarding_ecr_url 2>/dev/null || echo $(ECR_URL)):latest \
		-f infra/docker/Dockerfile.onboarding-agent --push .
	@echo "✅ onboarding-agent:latest pushed (linux/amd64)"

docker-push-all: docker-build docker-build-adot
	@echo "✅ All agent images pushed to ECR (linux/amd64)"

docker-deploy: docker-push-all
	@echo "Verifying all task definition images exist in ECR..."
	@aws ecr describe-images --repository-name $(shell basename $(ECR_URL)) --image-ids imageTag=latest --region $(AWS_REGION) >/dev/null 2>&1 || \
		(echo "❌ strands-agent:latest not found in ECR"; exit 1)
	@aws ecr describe-images --repository-name $(shell basename $(ECR_URL)) --image-ids imageTag=adot-v0.40.0 --region $(AWS_REGION) >/dev/null 2>&1 || \
		(echo "❌ adot-v0.40.0 not found in ECR — run: make docker-build-adot"; exit 1)
	@echo "✅ All images verified in ECR"
	@echo "Forcing new ECS task definition registration..."
	@terraform -chdir=infra/terraform apply -target=aws_ecs_task_definition.strands_agent -auto-approve
	@echo "✅ ECS task definition updated — new tasks will use the fresh image"
