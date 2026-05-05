#!/usr/bin/env python3
"""Generate Autonomous Code Factory architecture diagram.

ILR Analysis (Phase 1):
  Spine: Staff Engineer → ALM → Spec → Agent Pipeline → CI/CD → Ship-Readiness → Delivery → Staff Engineer
  Branches:
    - Notes (off Agent Pipeline) — cross-session learning
    - DORA Metrics (off Delivery) — factory health report, domain segmentation
    - Cloud (off Agent Pipeline) — AWS headless execution (ECS + Bedrock)
  Decorative (in cluster labels):
    - Constraint Extractor, Agent Builder, Autonomy Level (inside Agent Pipeline)
    - Project Isolation, Scope Boundaries (inside Spec Control Plane)
    - SDLC Gates, Pipeline Safety (inside CI/CD)
    - Failure Modes, Rollback (inside Ship-Readiness)
    - Prompt Registry, Task Queue, Lifecycle (inside State Plane)
  Convergence: None (serialized spine)

Updated: 2026-05-04 — ADR-013 components, DORA metrics, autonomy levels
"""
from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Fargate
from diagrams.aws.devtools import Codebuild, Codepipeline
from diagrams.aws.integration import StepFunctions
from diagrams.aws.ml import Bedrock
from diagrams.aws.storage import S3
from diagrams.onprem.client import User
from diagrams.onprem.vcs import Github
from diagrams.aws.compute import Lambda
from diagrams.aws.analytics import Quicksight
import os

output_dir = "docs/architecture"
os.makedirs(output_dir, exist_ok=True)


def cl(bgcolor, pencolor, fontcolor):
    """Cluster style helper — Rule 6."""
    return {
        "style": "rounded,filled",
        "fontsize": "11",
        "fontname": "Helvetica Bold",
        "labeljust": "l",
        "penwidth": "2",
        "margin": "14",
        "bgcolor": bgcolor,
        "pencolor": pencolor,
        "fontcolor": fontcolor,
    }


with Diagram(
    "",
    filename=f"{output_dir}/autonomous-code-factory",
    show=False,
    direction="LR",  # Rule 1: ALWAYS LR
    graph_attr={
        "ranksep": "1.4",   # Rule 3: horizontal distance
        "nodesep": "0.8",   # Rule 3: vertical distance
        "splines": "spline",  # Rule 2: >8 nodes
        "newrank": "true",
        "pad": "0.5",
        "fontname": "Helvetica",
    },
):
    # ═══ SPINE: Left to Right ═══

    # 1. Staff Engineer (Entry)
    with Cluster(
        "Staff Engineer\nFactory Operator · Autonomy L2-L5",
        graph_attr=cl("#e8f0fe", "#1a73e8", "#1a73e8"),
    ):
        engineer = User("Writes Specs\nApproves Outcomes")

    # 2. Work Intake — Multi-Platform ALM
    with Cluster(
        "Work Intake\nGitHub · Asana · GitLab · Scope Boundaries",
        graph_attr=cl("#e8f0fe", "#1a73e8", "#1565c0"),
    ):
        alm = Github("ALM\nData Contract")

    # 3. Spec Control Plane
    with Cluster(
        "Spec Control Plane\nCanonical Schema · Project Isolation · DoR Gate",
        graph_attr=cl("#fef7e0", "#f9a825", "#f57f17"),
    ):
        spec = S3("Spec\nConstraint Extraction")

    # 4. Agent Pipeline — Core execution with new components
    with Cluster(
        "Agent Pipeline\nAgent Builder · Autonomy · Constraint Injection",
        graph_attr=cl("#fce4ec", "#e53935", "#b71c1c"),
    ):
        agent = StepFunctions("Orchestrator\nRecon → Eng → Report")

    # 5. CI/CD + SDLC Gates
    with Cluster(
        "SDLC Gates\nInner Loop: Lint · Test · Build · PR Review",
        graph_attr=cl("#e8f5e9", "#43a047", "#2e7d32"),
    ):
        cicd = Codepipeline("Pipeline\nSDLC Inner Loop")

    # 6. Ship-Readiness + Safety
    with Cluster(
        "Ship-Readiness\nOuter Loop · Rollback · Failure Modes",
        graph_attr=cl("#fff3e0", "#ef6c00", "#e65100"),
    ):
        ship = Codebuild("Validation\nE2E · Holdout · Diff Review")

    # 7. Delivery
    with Cluster(
        "Delivery\nSemantic Commit · MR/PR · ALM Sync",
        graph_attr=cl("#e8f5e9", "#43a047", "#1b5e20"),
    ):
        delivery = Github("MR/PR\nvia MCP")

    # ═══ SPINE EDGES (weight=10 — Rule 4) ═══
    engineer >> Edge(
        label="1. Task + Autonomy", color="#1a73e8", style="bold", weight="10"
    ) >> alm
    alm >> Edge(
        label="2. Data Contract", color="#f9a825", style="bold", weight="10"
    ) >> spec
    spec >> Edge(
        label="3. Constraints + Spec", color="#e53935", style="bold", weight="10"
    ) >> agent
    agent >> Edge(
        label="4. Code + Tests", color="#43a047", style="bold", weight="10"
    ) >> cicd
    cicd >> Edge(
        label="5. Validate", color="#ef6c00", style="bold", weight="10"
    ) >> ship
    ship >> Edge(
        label="6. Release", color="#43a047", style="bold", weight="10"
    ) >> delivery
    delivery >> Edge(
        label="7. Approve", color="#1a73e8", style="bold", weight="10"
    ) >> engineer

    # ═══ BRANCHES (weight=1 — Rule 4) ═══

    # Branch A: Cross-Session Learning (off Agent Pipeline)
    with Cluster(
        "Cross-Session Learning\nNotes · Working Memory · Hindsight",
        graph_attr=cl("#f3e5f5", "#8e24aa", "#6a1b9a"),
    ):
        notes = S3("Notes\n.kiro/notes/")

    agent >> Edge(
        label="Hindsight", color="#8e24aa", style="dashed", weight="1"
    ) >> notes

    # Branch B: DORA Metrics + Factory Health (off Delivery)
    with Cluster(
        "DORA Metrics\nLead Time · CFR · MTTR · Domain Breakdown",
        graph_attr=cl("#f3e5f5", "#8e24aa", "#4a148c"),
    ):
        dora = Quicksight("Factory Report\nElite/High/Med/Low")

    delivery >> Edge(
        label="Metrics", color="#8e24aa", style="dashed", weight="1"
    ) >> dora

    # Branch C: AWS Cloud Infrastructure (off Agent Pipeline)
    with Cluster(
        "AWS Cloud Plane\nECR · Secrets · CloudWatch · EventBridge",
        graph_attr=cl("#fff3e0", "#ef6c00", "#e65100"),
    ):
        bedrock = Bedrock("Bedrock\nInference")
        ecs = Fargate("ECS Fargate\nStrands Agent")

    agent >> Edge(
        label="Headless", color="#ef6c00", style="dashed", weight="1"
    ) >> ecs
    ecs >> Edge(
        label="Invoke", color="#ef6c00", style="dashed", weight="1"
    ) >> bedrock

    # Branch D: State Plane (off ECS)
    with Cluster(
        "State Plane\nPrompt Registry · Task Queue · Lifecycle · DORA",
        graph_attr=cl("#fef7e0", "#f9a825", "#f57f17"),
    ):
        dynamo = S3("DynamoDB\n4 Tables")

    ecs >> Edge(
        label="State", color="#f9a825", style="dashed", weight="1"
    ) >> dynamo


print("Architecture diagram generated: docs/architecture/autonomous-code-factory.png")
