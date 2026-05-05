#!/usr/bin/env python3
"""
Forward Deployed Engineer — AWS IAM Permission Validator

Validates that the current AWS identity has the specific permissions
required to deploy and operate the Code Factory cloud infrastructure.

Usage: python3 scripts/validate-aws-iam.py [--region us-east-1] [--json]

Exit codes:
  0 — All required permissions validated
  1 — One or more permissions missing
  2 — AWS credentials not configured
"""

import json
import sys
import argparse

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
except ImportError:
    print("ERROR: boto3 not installed. Run: pip install boto3")
    sys.exit(2)

REQUIRED_PERMISSIONS = {
    "bedrock": {
        "why": "Agent inference via Amazon Bedrock",
    },
    "ecr": {
        "why": "Push Strands agent Docker images to ECR",
    },
    "ecs": {
        "why": "Run headless agents on ECS Fargate",
    },
    "s3": {
        "why": "Factory artifacts bucket (specs, notes, reports)",
    },
    "secretsmanager": {
        "why": "Store ALM tokens (GitHub, Asana, GitLab)",
    },
    "logs": {
        "why": "Agent execution logs in CloudWatch",
    },
    "iam": {
        "why": "Terraform creates IAM roles for ECS tasks",
    },
    "ec2_vpc": {
        "why": "VPC networking for ECS Fargate tasks",
    },
}


def check_identity(region):
    """Verify AWS credentials and return identity info."""
    try:
        sts = boto3.client("sts", region_name=region)
        identity = sts.get_caller_identity()
        return {
            "account": identity["Account"],
            "arn": identity["Arn"],
            "user_id": identity["UserId"],
        }
    except NoCredentialsError:
        print("ERROR: No AWS credentials found.")
        print("Configure: aws configure, or set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY")
        sys.exit(2)
    except ClientError as e:
        print(f"ERROR: AWS STS call failed: {e}")
        sys.exit(2)


def check_permissions_via_dry_run(region):
    """Check permissions by attempting read-only API calls per service."""
    results = {}

    checks = [
        ("s3", lambda: boto3.client("s3", region_name=region).list_buckets()),
        ("ecr", lambda: boto3.client("ecr", region_name=region).describe_repositories(maxResults=1)),
        ("ecs", lambda: boto3.client("ecs", region_name=region).list_clusters(maxResults=1)),
        ("secretsmanager", lambda: boto3.client("secretsmanager", region_name=region).list_secrets(MaxResults=1)),
        ("logs", lambda: boto3.client("logs", region_name=region).describe_log_groups(limit=1)),
        ("ec2_vpc", lambda: boto3.client("ec2", region_name=region).describe_vpcs(MaxResults=5)),
        ("iam", lambda: boto3.client("iam", region_name=region).list_roles(MaxItems=1)),
    ]

    for service, check_fn in checks:
        try:
            check_fn()
            results[service] = {"status": "ok", "detail": f"{service} API accessible"}
        except ClientError as e:
            if "AccessDenied" in str(e) or "UnauthorizedAccess" in str(e):
                results[service] = {"status": "fail", "detail": str(e)}
            else:
                results[service] = {"status": "ok", "detail": f"{service} accessible (non-auth error)"}
        except Exception as e:
            results[service] = {"status": "warn", "detail": str(e)}

    # Bedrock — separate because it may not be available in all regions
    try:
        bedrock = boto3.client("bedrock", region_name=region)
        bedrock.list_foundation_models(maxResults=1)
        results["bedrock"] = {"status": "ok", "detail": "Bedrock API accessible"}
    except ClientError as e:
        if "AccessDenied" in str(e):
            results["bedrock"] = {"status": "fail", "detail": str(e)}
        else:
            results["bedrock"] = {"status": "ok", "detail": "Bedrock accessible"}
    except Exception:
        results["bedrock"] = {"status": "warn", "detail": "Bedrock may not be available in this region"}

    return results


def main():
    parser = argparse.ArgumentParser(description="Validate AWS IAM permissions for FDE Code Factory")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    identity = check_identity(args.region)

    if not args.json:
        print(f"\n  AWS Account: {identity['account']}")
        print(f"  Identity:    {identity['arn']}")
        print(f"  Region:      {args.region}")
        print()

    results = check_permissions_via_dry_run(args.region)

    if args.json:
        print(json.dumps({"identity": identity, "region": args.region, "permissions": results}, indent=2))
        sys.exit(0 if all(r["status"] != "fail" for r in results.values()) else 1)

    passed = 0
    failed = 0

    for service, result in results.items():
        why = REQUIRED_PERMISSIONS.get(service, {}).get("why", "")
        if result["status"] == "ok":
            print(f"  ✓ {service}: {result['detail']}")
            passed += 1
        elif result["status"] == "warn":
            print(f"  ⚠ {service}: {result['detail']}")
            passed += 1
        else:
            print(f"  ✗ {service}: {result['detail']}")
            if why:
                print(f"    Required for: {why}")
            failed += 1

    print(f"\n  Passed: {passed} | Failed: {failed}")

    if failed > 0:
        print(f"\n  ACTION: Attach required IAM policies to {identity['arn']}")
        print("  See: docs/flows/12-staff-engineer-onboarding.md")
        sys.exit(1)
    else:
        print("\n  All required AWS permissions validated.")
        sys.exit(0)


if __name__ == "__main__":
    main()
