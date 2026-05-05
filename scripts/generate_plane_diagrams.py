#!/usr/bin/env python3
"""Generate modular architecture diagrams — one per plane + hero overview.

Planes:
  0. Hero (General Architecture) — 5 planes as blocks
  1. Version Source Management Plane — Git, branches, ALM, Project Isolation
  2. FDE Plane — Orchestrator, Agent Builder, Autonomy, Pipeline stages
  3. Context Plane — Constraint Extractor, Prompt Registry, Scope Boundaries, Learning
  4. Data Plane — Data Contract, Router, Task Queue, DynamoDB, S3
  5. Control Plane — SDLC Gates, DORA Metrics, Failure Modes, Pipeline Safety

Each diagram follows ILR pattern: LR direction, spine + branches, max 3 nodes/cluster.
"""
from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Fargate
from diagrams.aws.database import Dynamodb
from diagrams.aws.devtools import Codebuild, Codepipeline
from diagrams.aws.integration import StepFunctions, Eventbridge
from diagrams.aws.ml import Bedrock
from diagrams.aws.storage import S3
from diagrams.aws.analytics import Quicksight
from diagrams.aws.security import SecretsManager
from diagrams.onprem.client import User
from diagrams.onprem.vcs import Github
import os

output_dir = "docs/architecture/planes"
os.makedirs(output_dir, exist_ok=True)


def cl(bgcolor, pencolor, fontcolor):
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


def generate_hero():
    with Diagram(
        "",
        filename=f"{output_dir}/00-hero-overview",
        show=False,
        direction="LR",
        graph_attr={"ranksep": "1.6", "nodesep": "0.9", "splines": "curved", "newrank": "true", "pad": "0.5"},
    ):
        with Cluster("1. Version Source Management\nGit · ALM · Branches · Isolation", graph_attr=cl("#e8f0fe", "#1a73e8", "#1a73e8")):
            vsm = Github("Source\nManagement")

        with Cluster("2. Data Plane\nContract · Router · Queue · Storage", graph_attr=cl("#fef7e0", "#f9a825", "#f57f17")):
            data = Dynamodb("Data\nFlow")

        with Cluster("3. Context Plane\nConstraints · Prompts · Scope · Learning", graph_attr=cl("#e8f5e9", "#43a047", "#2e7d32")):
            context = S3("Context\nKnowledge")

        with Cluster("4. FDE Plane\nOrchestrator · Builder · Autonomy · Agents", graph_attr=cl("#fce4ec", "#e53935", "#b71c1c")):
            fde = StepFunctions("Agent\nPipeline")

        with Cluster("5. Control Plane\nSDLC · DORA · Safety · Failure Modes", graph_attr=cl("#fff3e0", "#ef6c00", "#e65100")):
            control = Quicksight("Governance\nMetrics")

        vsm >> Edge(label="1. Tasks", color="#1a73e8", style="bold", weight="10") >> data
        data >> Edge(label="2. Contract", color="#f9a825", style="bold", weight="10") >> context
        context >> Edge(label="3. Prompts", color="#43a047", style="bold", weight="10") >> fde
        fde >> Edge(label="4. Results", color="#e53935", style="bold", weight="10") >> control
        control >> Edge(label="5. Feedback", color="#ef6c00", style="bold", weight="10") >> vsm

    print("  Generated: 00-hero-overview.png")


def generate_vsm_plane():
    with Diagram(
        "",
        filename=f"{output_dir}/01-vsm-plane",
        show=False,
        direction="LR",
        graph_attr={"ranksep": "1.2", "nodesep": "0.7", "splines": "curved", "newrank": "true"},
    ):
        with Cluster("Staff Engineer", graph_attr=cl("#e8f0fe", "#1a73e8", "#1a73e8")):
            engineer = User("Writes Specs\nSets Autonomy")

        with Cluster("ALM Platforms\nGitHub · Asana · GitLab", graph_attr=cl("#e8f0fe", "#1a73e8", "#1565c0")):
            alm = Github("Issue Board\nData Contract")

        with Cluster("Project Isolation\nBranch · Workspace · S3 Prefix", graph_attr=cl("#fef7e0", "#f9a825", "#f57f17")):
            isolation = S3("Isolated\nWorkspace")

        engineer >> Edge(label="1. Create Task", color="#1a73e8", style="bold", weight="10") >> alm
        alm >> Edge(label="2. Isolate", color="#f9a825", style="bold", weight="10") >> isolation

        with Cluster("Delivery\nFeature Branch · PR/MR", graph_attr=cl("#e8f5e9", "#43a047", "#2e7d32")):
            pr = Github("PR/MR\nvia MCP")

        isolation >> Edge(label="3. Code", color="#43a047", style="bold", weight="10") >> pr
        pr >> Edge(label="4. Review", color="#1a73e8", style="dashed", weight="1") >> engineer

    print("  Generated: 01-vsm-plane.png")


def generate_fde_plane():
    with Diagram(
        "",
        filename=f"{output_dir}/02-fde-plane",
        show=False,
        direction="LR",
        graph_attr={"ranksep": "1.2", "nodesep": "0.7", "splines": "curved", "newrank": "true"},
    ):
        with Cluster("Autonomy Resolution\nL2 Collaborator → L5 Observer", graph_attr=cl("#e8f0fe", "#1a73e8", "#1a73e8")):
            autonomy = StepFunctions("Compute\nAutonomy Level")

        with Cluster("Agent Builder\nPrompt Registry · Tool Selection", graph_attr=cl("#fce4ec", "#e53935", "#b71c1c")):
            builder = Bedrock("Build\nSpecialized Agent")

        with Cluster("Pipeline Execution\nRecon → Engineering → Reporting", graph_attr=cl("#fce4ec", "#e53935", "#b71c1c")):
            pipeline = Fargate("Execute\n3-Phase Pipeline")

        autonomy >> Edge(label="1. Level + Gates", color="#1a73e8", style="bold", weight="10") >> builder
        builder >> Edge(label="2. Agent Definition", color="#e53935", style="bold", weight="10") >> pipeline

        with Cluster("AWS Cloud\nECS Fargate · Bedrock", graph_attr=cl("#fff3e0", "#ef6c00", "#e65100")):
            cloud = Fargate("Headless\nExecution")

        pipeline >> Edge(label="Headless", color="#ef6c00", style="dashed", weight="1") >> cloud

    print("  Generated: 02-fde-plane.png")


def generate_context_plane():
    with Diagram(
        "",
        filename=f"{output_dir}/03-context-plane",
        show=False,
        direction="LR",
        graph_attr={"ranksep": "1.8", "nodesep": "0.5", "splines": "curved", "newrank": "true"},
    ):
        with Cluster("Constraint Extractor\nRule-Based + LLM (opt-in)", graph_attr=cl("#e8f5e9", "#43a047", "#2e7d32")):
            extractor = Bedrock("Extract\nConstraints")

        with Cluster("Prompt Registry\nVersioned · Hash · Tags · Cross-Session Learning", graph_attr=cl("#e8f5e9", "#43a047", "#2e7d32")):
            registry = Dynamodb("Prompt\nLookup")

        with Cluster("Scope Boundaries\nConfidence · Forbidden Actions · Tooling Check", graph_attr=cl("#fef7e0", "#f9a825", "#f57f17")):
            scope = S3("Scope\nValidation")

        extractor >> Edge(label="1. Constraints", color="#43a047", style="bold", weight="10") >> registry
        registry >> Edge(label="2. Prompt + Context", color="#43a047", style="bold", weight="10") >> scope

    print("  Generated: 03-context-plane.png")


def generate_data_plane():
    with Diagram(
        "",
        filename=f"{output_dir}/04-data-plane",
        show=False,
        direction="LR",
        graph_attr={"ranksep": "1.2", "nodesep": "0.7", "splines": "curved", "newrank": "true"},
    ):
        with Cluster("Router\nGitHub · GitLab · Asana · Direct", graph_attr=cl("#fef7e0", "#f9a825", "#f57f17")):
            router = Eventbridge("Route\nExtract Contract")

        with Cluster("Task Queue\nPriority · Dependencies · Status", graph_attr=cl("#fef7e0", "#f9a825", "#f57f17")):
            queue = Dynamodb("Task Queue\nDynamoDB")

        with Cluster("Artifact Storage\nSpecs · Results · Reports", graph_attr=cl("#fff3e0", "#ef6c00", "#e65100")):
            storage = S3("S3 Bucket\nVersioned")

        router >> Edge(label="1. Data Contract", color="#f9a825", style="bold", weight="10") >> queue
        queue >> Edge(label="2. Artifacts", color="#ef6c00", style="bold", weight="10") >> storage

        with Cluster("Event Bus\nWebhooks · ALM Events", graph_attr=cl("#e8f0fe", "#1a73e8", "#1a73e8")):
            events = Eventbridge("EventBridge\nFactory Bus")

        events >> Edge(label="Events", color="#1a73e8", style="dashed", weight="1") >> router

    print("  Generated: 04-data-plane.png")


def generate_control_plane():
    with Diagram(
        "",
        filename=f"{output_dir}/05-control-plane",
        show=False,
        direction="LR",
        graph_attr={"ranksep": "1.2", "nodesep": "0.7", "splines": "curved", "newrank": "true"},
    ):
        with Cluster("SDLC Gates\nInner: Lint · Test · Build\nOuter: DoR · Adversarial · Ship", graph_attr=cl("#e8f5e9", "#43a047", "#2e7d32")):
            gates = Codepipeline("Quality\nGates")

        with Cluster("DORA Metrics\nLead Time · CFR · MTTR · Domain", graph_attr=cl("#fff3e0", "#ef6c00", "#e65100")):
            dora = Quicksight("Factory\nHealth Report")

        with Cluster("Pipeline Safety\nDiff Review · Rollback · Failure Modes", graph_attr=cl("#fce4ec", "#e53935", "#b71c1c")):
            safety = Codebuild("Safety\nEnforcement")

        gates >> Edge(label="1. Gate Results", color="#43a047", style="bold", weight="10") >> dora
        dora >> Edge(label="2. Metrics", color="#ef6c00", style="bold", weight="10") >> safety

        with Cluster("Failure Modes\nFM-01 → FM-99 Taxonomy", graph_attr=cl("#f3e5f5", "#8e24aa", "#6a1b9a")):
            fm = Dynamodb("Classify\nRecovery Action")

        safety >> Edge(label="Classify", color="#8e24aa", style="dashed", weight="1") >> fm

    print("  Generated: 05-control-plane.png")


if __name__ == "__main__":
    print("Generating plane diagrams...")
    generate_hero()
    generate_vsm_plane()
    generate_fde_plane()
    generate_context_plane()
    generate_data_plane()
    generate_control_plane()
    print(f"All 6 diagrams generated in {output_dir}/")
