#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════
# Forward Deployed Engineer — Teardown / Decommission Script
# ═══════════════════════════════════════════════════════════════════
#
# Destroys all AWS resources created by the Code Factory.
# Two modes:
#   1. Terraform destroy (preferred — uses state file)
#   2. Tag-based cleanup (fallback — finds resources by naming convention)
#
# Usage:
#   bash scripts/teardown-fde.sh --terraform
#   bash scripts/teardown-fde.sh --tags
#   bash scripts/teardown-fde.sh --dry-run
# ═══════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

AWS_PROFILE_ARG=""
if [ -f "$HOME/.kiro/fde-manifest.json" ]; then
    PROFILE=$(python3 -c "import json; print(json.load(open('$HOME/.kiro/fde-manifest.json')).get('credentials',{}).get('aws_profile',''))" 2>/dev/null || echo "")
    if [ -n "$PROFILE" ]; then AWS_PROFILE_ARG="$PROFILE"; fi
fi

aws_cmd() {
    if [ -n "$AWS_PROFILE_ARG" ]; then aws --profile "$AWS_PROFILE_ARG" "$@"; else aws "$@"; fi
}

ENVIRONMENT="dev"
AWS_REGION="us-east-1"
if [ -f "$HOME/.kiro/fde-manifest.json" ]; then
    ENVIRONMENT=$(python3 -c "import json; print(json.load(open('$HOME/.kiro/fde-manifest.json')).get('cloud',{}).get('environment','dev'))" 2>/dev/null || echo "dev")
    AWS_REGION=$(python3 -c "import json; print(json.load(open('$HOME/.kiro/fde-manifest.json')).get('cloud',{}).get('aws_region','us-east-1'))" 2>/dev/null || echo "us-east-1")
fi

NAME_PREFIX="fde-${ENVIRONMENT}"
DRY_RUN=false

teardown_terraform() {
    echo -e "\n${CYAN}══ Terraform Destroy ══${NC}"
    TF_DIR="$SCRIPT_DIR/infra/terraform"

    if [ ! -d "$TF_DIR/.terraform" ]; then
        echo -e "  ${RED}✗${NC} No Terraform state at $TF_DIR"
        echo -e "  ${BOLD}  → Fix:${NC} Use --tags mode instead"
        return 1
    fi

    TF_ENV=""
    TF_PROFILE=$(python3 -c "import json; print(json.load(open('$HOME/.kiro/fde-manifest.json')).get('cloud',{}).get('aws_tf_profile',''))" 2>/dev/null || echo "")
    if [ -n "$TF_PROFILE" ]; then TF_ENV="AWS_PROFILE=$TF_PROFILE"; fi

    echo -e "  ${BOLD}ℹ${NC} Environment: $ENVIRONMENT | Region: $AWS_REGION"
    if [ -n "$TF_PROFILE" ]; then echo -e "  ${BOLD}ℹ${NC} AWS Profile: $TF_PROFILE"; fi

    if [ "$DRY_RUN" = true ]; then
        env $TF_ENV terraform -chdir="$TF_DIR" plan -destroy -var-file="factory.tfvars" 2>&1 | tail -30
        echo -e "\n  ${YELLOW}DRY RUN:${NC} No resources destroyed."
        return 0
    fi

    env $TF_ENV terraform -chdir="$TF_DIR" plan -destroy -var-file="factory.tfvars" 2>&1 | tail -30

    echo ""
    echo -e "  ${RED}${BOLD}WARNING:${NC} This will permanently destroy all AWS resources above."
    read -rp "  Type 'destroy' to confirm: " CONFIRM
    if [ "$CONFIRM" != "destroy" ]; then
        echo -e "  ${GREEN}Aborted.${NC}"
        return 0
    fi

    env $TF_ENV terraform -chdir="$TF_DIR" destroy -var-file="factory.tfvars" -auto-approve 2>&1
    echo -e "\n  ${GREEN}✓${NC} Terraform destroy complete."

    rm -f "$TF_DIR/terraform.tfstate" "$TF_DIR/terraform.tfstate.backup" "$TF_DIR/tfplan"
    rm -rf "$TF_DIR/.terraform" "$TF_DIR/.terraform.lock.hcl"
    echo -e "  ${GREEN}✓${NC} Local state cleaned up."
}

teardown_by_tags() {
    echo -e "\n${CYAN}══ Tag-Based Resource Cleanup ══${NC}"
    echo -e "  ${BOLD}ℹ${NC} Prefix: $NAME_PREFIX | Region: $AWS_REGION"
    echo ""

    FOUND=0

    # ECS
    echo -e "  ${CYAN}── ECS ──${NC}"
    CLUSTERS=$(aws_cmd ecs list-clusters --region "$AWS_REGION" --query "clusterArns[?contains(@,'$NAME_PREFIX')]" --output text 2>/dev/null || echo "")
    for cluster_arn in $CLUSTERS; do
        SERVICES=$(aws_cmd ecs list-services --cluster "$cluster_arn" --region "$AWS_REGION" --query "serviceArns" --output text 2>/dev/null || echo "")
        for svc in $SERVICES; do
            echo -e "    ${RED}✗${NC} Service: $svc"; ((FOUND++))
            [ "$DRY_RUN" = false ] && { aws_cmd ecs update-service --cluster "$cluster_arn" --service "$svc" --desired-count 0 --region "$AWS_REGION" >/dev/null 2>&1 || true; aws_cmd ecs delete-service --cluster "$cluster_arn" --service "$svc" --force --region "$AWS_REGION" >/dev/null 2>&1 || true; }
        done
        echo -e "    ${RED}✗${NC} Cluster: $cluster_arn"; ((FOUND++))
        [ "$DRY_RUN" = false ] && { aws_cmd ecs delete-cluster --cluster "$cluster_arn" --region "$AWS_REGION" >/dev/null 2>&1 || true; }
    done

    # ECR
    echo -e "  ${CYAN}── ECR ──${NC}"
    REPOS=$(aws_cmd ecr describe-repositories --region "$AWS_REGION" --query "repositories[?contains(repositoryName,'$NAME_PREFIX')].repositoryName" --output text 2>/dev/null || echo "")
    for repo in $REPOS; do
        echo -e "    ${RED}✗${NC} Repo: $repo"; ((FOUND++))
        [ "$DRY_RUN" = false ] && { aws_cmd ecr delete-repository --repository-name "$repo" --force --region "$AWS_REGION" >/dev/null 2>&1 || true; }
    done

    # S3
    echo -e "  ${CYAN}── S3 ──${NC}"
    BUCKETS=$(aws_cmd s3api list-buckets --query "Buckets[?contains(Name,'$NAME_PREFIX')].Name" --output text 2>/dev/null || echo "")
    for bucket in $BUCKETS; do
        echo -e "    ${RED}✗${NC} Bucket: $bucket"; ((FOUND++))
        [ "$DRY_RUN" = false ] && { aws_cmd s3 rb "s3://$bucket" --force --region "$AWS_REGION" >/dev/null 2>&1 || true; }
    done

    # Secrets Manager
    echo -e "  ${CYAN}── Secrets ──${NC}"
    SECRETS=$(aws_cmd secretsmanager list-secrets --region "$AWS_REGION" --query "SecretList[?contains(Name,'$NAME_PREFIX')].Name" --output text 2>/dev/null || echo "")
    for secret in $SECRETS; do
        echo -e "    ${RED}✗${NC} Secret: $secret"; ((FOUND++))
        [ "$DRY_RUN" = false ] && { aws_cmd secretsmanager delete-secret --secret-id "$secret" --force-delete-without-recovery --region "$AWS_REGION" >/dev/null 2>&1 || true; }
    done

    # EventBridge
    echo -e "  ${CYAN}── EventBridge ──${NC}"
    BUSES=$(aws_cmd events list-event-buses --region "$AWS_REGION" --query "EventBuses[?contains(Name,'$NAME_PREFIX')].Name" --output text 2>/dev/null || echo "")
    for bus in $BUSES; do
        RULES=$(aws_cmd events list-rules --event-bus-name "$bus" --region "$AWS_REGION" --query "Rules[].Name" --output text 2>/dev/null || echo "")
        for rule in $RULES; do
            TARGETS=$(aws_cmd events list-targets-by-rule --rule "$rule" --event-bus-name "$bus" --region "$AWS_REGION" --query "Targets[].Id" --output text 2>/dev/null || echo "")
            for target in $TARGETS; do
                [ "$DRY_RUN" = false ] && { aws_cmd events remove-targets --rule "$rule" --event-bus-name "$bus" --ids "$target" --region "$AWS_REGION" >/dev/null 2>&1 || true; }
            done
            echo -e "    ${RED}✗${NC} Rule: $rule"; ((FOUND++))
            [ "$DRY_RUN" = false ] && { aws_cmd events delete-rule --name "$rule" --event-bus-name "$bus" --region "$AWS_REGION" >/dev/null 2>&1 || true; }
        done
        echo -e "    ${RED}✗${NC} Bus: $bus"; ((FOUND++))
        [ "$DRY_RUN" = false ] && { aws_cmd events delete-event-bus --name "$bus" --region "$AWS_REGION" >/dev/null 2>&1 || true; }
    done

    # API Gateway
    echo -e "  ${CYAN}── API Gateway ──${NC}"
    APIS=$(aws_cmd apigatewayv2 get-apis --region "$AWS_REGION" --query "Items[?contains(Name,'$NAME_PREFIX')].ApiId" --output text 2>/dev/null || echo "")
    for api in $APIS; do
        echo -e "    ${RED}✗${NC} API: $api"; ((FOUND++))
        [ "$DRY_RUN" = false ] && { aws_cmd apigatewayv2 delete-api --api-id "$api" --region "$AWS_REGION" >/dev/null 2>&1 || true; }
    done

    # CloudWatch Logs
    echo -e "  ${CYAN}── Logs ──${NC}"
    for prefix in "/ecs/$NAME_PREFIX" "/apigateway/$NAME_PREFIX"; do
        LOG_GROUPS=$(aws_cmd logs describe-log-groups --region "$AWS_REGION" --log-group-name-prefix "$prefix" --query "logGroups[].logGroupName" --output text 2>/dev/null || echo "")
        for lg in $LOG_GROUPS; do
            echo -e "    ${RED}✗${NC} Log Group: $lg"; ((FOUND++))
            [ "$DRY_RUN" = false ] && { aws_cmd logs delete-log-group --log-group-name "$lg" --region "$AWS_REGION" >/dev/null 2>&1 || true; }
        done
    done

    # IAM Roles
    echo -e "  ${CYAN}── IAM ──${NC}"
    ROLES=$(aws_cmd iam list-roles --query "Roles[?contains(RoleName,'$NAME_PREFIX')].RoleName" --output text 2>/dev/null || echo "")
    for role in $ROLES; do
        echo -e "    ${RED}✗${NC} Role: $role"; ((FOUND++))
        if [ "$DRY_RUN" = false ]; then
            POLICIES=$(aws_cmd iam list-attached-role-policies --role-name "$role" --query "AttachedPolicies[].PolicyArn" --output text 2>/dev/null || echo "")
            for pol in $POLICIES; do aws_cmd iam detach-role-policy --role-name "$role" --policy-arn "$pol" >/dev/null 2>&1 || true; done
            INLINE=$(aws_cmd iam list-role-policies --role-name "$role" --query "PolicyNames" --output text 2>/dev/null || echo "")
            for pol in $INLINE; do aws_cmd iam delete-role-policy --role-name "$role" --policy-name "$pol" >/dev/null 2>&1 || true; done
            aws_cmd iam delete-role --role-name "$role" >/dev/null 2>&1 || true
        fi
    done

    # VPC (last)
    echo -e "  ${CYAN}── VPC ──${NC}"
    VPCS=$(aws_cmd ec2 describe-vpcs --region "$AWS_REGION" --filters "Name=tag:Name,Values=$NAME_PREFIX-vpc" --query "Vpcs[].VpcId" --output text 2>/dev/null || echo "")
    for vpc in $VPCS; do
        echo -e "    ${RED}✗${NC} VPC: $vpc"; ((FOUND++))
        if [ "$DRY_RUN" = false ]; then
            NATS=$(aws_cmd ec2 describe-nat-gateways --region "$AWS_REGION" --filter "Name=vpc-id,Values=$vpc" --query "NatGateways[?State!='deleted'].NatGatewayId" --output text 2>/dev/null || echo "")
            for nat in $NATS; do aws_cmd ec2 delete-nat-gateway --nat-gateway-id "$nat" --region "$AWS_REGION" >/dev/null 2>&1 || true; done
            [ -n "$NATS" ] && { echo -e "    ${YELLOW}⚠${NC} Waiting for NAT Gateway deletion..."; sleep 60; }
            IGWS=$(aws_cmd ec2 describe-internet-gateways --region "$AWS_REGION" --filters "Name=attachment.vpc-id,Values=$vpc" --query "InternetGateways[].InternetGatewayId" --output text 2>/dev/null || echo "")
            for igw in $IGWS; do aws_cmd ec2 detach-internet-gateway --internet-gateway-id "$igw" --vpc-id "$vpc" --region "$AWS_REGION" >/dev/null 2>&1 || true; aws_cmd ec2 delete-internet-gateway --internet-gateway-id "$igw" --region "$AWS_REGION" >/dev/null 2>&1 || true; done
            SUBNETS=$(aws_cmd ec2 describe-subnets --region "$AWS_REGION" --filters "Name=vpc-id,Values=$vpc" --query "Subnets[].SubnetId" --output text 2>/dev/null || echo "")
            for sub in $SUBNETS; do aws_cmd ec2 delete-subnet --subnet-id "$sub" --region "$AWS_REGION" >/dev/null 2>&1 || true; done
            RTS=$(aws_cmd ec2 describe-route-tables --region "$AWS_REGION" --filters "Name=vpc-id,Values=$vpc" --query "RouteTables[?Associations[0].Main!=\`true\`].RouteTableId" --output text 2>/dev/null || echo "")
            for rt in $RTS; do aws_cmd ec2 delete-route-table --route-table-id "$rt" --region "$AWS_REGION" >/dev/null 2>&1 || true; done
            SGS=$(aws_cmd ec2 describe-security-groups --region "$AWS_REGION" --filters "Name=vpc-id,Values=$vpc" --query "SecurityGroups[?GroupName!='default'].GroupId" --output text 2>/dev/null || echo "")
            for sg in $SGS; do aws_cmd ec2 delete-security-group --group-id "$sg" --region "$AWS_REGION" >/dev/null 2>&1 || true; done
            EIPS=$(aws_cmd ec2 describe-addresses --region "$AWS_REGION" --filters "Name=tag:Name,Values=$NAME_PREFIX-*" --query "Addresses[].AllocationId" --output text 2>/dev/null || echo "")
            for eip in $EIPS; do aws_cmd ec2 release-address --allocation-id "$eip" --region "$AWS_REGION" >/dev/null 2>&1 || true; done
            aws_cmd ec2 delete-vpc --vpc-id "$vpc" --region "$AWS_REGION" >/dev/null 2>&1 || true
        fi
    done

    echo ""
    if [ "$DRY_RUN" = true ]; then
        echo -e "  ${YELLOW}DRY RUN:${NC} Found $FOUND resources. Nothing destroyed."
    elif [ "$FOUND" -eq 0 ]; then
        echo -e "  ${GREEN}✓${NC} No FDE resources found."
    else
        echo -e "  ${GREEN}✓${NC} Cleaned up $FOUND resources."
    fi
}

echo ""
echo "═══════════════════════════════════════════════════════════"
echo " Forward Deployed Engineer — Teardown"
echo " Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo " Environment: $ENVIRONMENT | Region: $AWS_REGION"
[ -n "$AWS_PROFILE_ARG" ] && echo " AWS Profile: $AWS_PROFILE_ARG"
echo "═══════════════════════════════════════════════════════════"

case "${1:-}" in
    --terraform) teardown_terraform ;;
    --tags)
        echo -e "\n  ${RED}${BOLD}WARNING:${NC} Tag-based cleanup will destroy all FDE resources."
        read -rp "  Type 'destroy' to confirm: " CONFIRM
        [ "$CONFIRM" = "destroy" ] && teardown_by_tags || echo -e "  ${GREEN}Aborted.${NC}"
        ;;
    --dry-run) DRY_RUN=true; teardown_by_tags ;;
    *)
        echo ""
        echo "Usage:"
        echo "  bash scripts/teardown-fde.sh --terraform    # Destroy via Terraform state"
        echo "  bash scripts/teardown-fde.sh --tags          # Destroy by naming convention"
        echo "  bash scripts/teardown-fde.sh --dry-run       # Show what would be destroyed"
        exit 1
        ;;
esac
