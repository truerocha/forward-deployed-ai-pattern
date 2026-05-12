"""
Generate the PEC Intelligence Layer architecture diagram.

Spine: Task Intake → Risk Engine → Conductor → Squad → DORA Forecast → Portal
Branch: Code KB (off Squad node)
Feedback: Weight Update (Portal → Risk Engine)

Output: docs/architecture/pec-intelligence-layer.png
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Fargate
from diagrams.aws.database import Dynamodb
from diagrams.aws.ml import Bedrock
from diagrams.aws.network import CloudFront
from diagrams.custom import Custom
import os

# Output path
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "architecture")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "pec-intelligence-layer")


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


with Diagram(
    "",
    filename=OUTPUT_FILE,
    show=False,
    direction="LR",
    graph_attr={
        "ranksep": "1.2",
        "nodesep": "0.7",
        "splines": "curved",
        "newrank": "true",
        "pad": "0.4",
    },
):
    # Spine (left to right)
    with Cluster("Task Intake\nRouter · Scope Check", graph_attr=cl("#e8f0fe", "#1a73e8", "#1a73e8")):
        intake = Fargate("Data\nContract")

    with Cluster("Risk Engine\nP(F|C) · 13 signals · XAI", graph_attr=cl("#fce4ec", "#e53935", "#b71c1c")):
        risk = Bedrock("Sigmoid\nClassifier")

    with Cluster("Conductor\nWorkflow Plan · Topology", graph_attr=cl("#e8f0fe", "#1a73e8", "#1a73e8")):
        conductor = Fargate("Plan\nGenerator")

    with Cluster("Squad Execution\nAgents · ECS · SCD", graph_attr=cl("#fef7e0", "#f9a825", "#f9a825")):
        squad = Fargate("Agent\nSquad")

    with Cluster("DORA Forecast\nEWMA · Health Pulse", graph_attr=cl("#e8f5e9", "#43a047", "#43a047")):
        forecast = Dynamodb("Metrics\nProjection")

    with Cluster("Portal\nPersona UX · DORA Sun", graph_attr=cl("#fff3e0", "#ef6c00", "#e65100")):
        portal = CloudFront("Persona\nFiltered")

    # Main spine edges (high weight)
    intake >> Edge(label="1. assess", color="#1a73e8", style="bold", weight="10", minlen="2") >> risk
    risk >> Edge(label="2. plan", color="#e53935", style="bold", weight="10", minlen="2") >> conductor
    conductor >> Edge(label="3. execute", color="#1a73e8", style="bold", weight="10", minlen="2") >> squad
    squad >> Edge(label="4. outcome", color="#f9a825", style="bold", weight="10", minlen="2") >> forecast
    forecast >> Edge(label="5. visualize", color="#43a047", style="bold", weight="10", minlen="2") >> portal

    # Branch: Code KB (off Squad)
    with Cluster("Code KB\nHybrid Search · Embeddings", graph_attr=cl("#f3e5f5", "#8e24aa", "#6a1b9a")):
        codekb = Dynamodb("Vector\nStore")

    squad >> Edge(label="query", color="#8e24aa", style="dashed", weight="1") >> codekb

    # Feedback: Weight Update (Portal → Risk)
    portal >> Edge(label="6. weight update", color="#2E7D32", style="dashed", weight="1") >> risk


if __name__ == "__main__":
    print(f"Diagram generated: {OUTPUT_FILE}.png")
