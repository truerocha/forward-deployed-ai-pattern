"""
Generate the ICRL Review Feedback Loop architecture diagram.

Follows the Diagram Engineering steering (ILR pattern):
  - Direction: LR (horizontal spine)
  - Spine: PR Review → Lambda → Metrics → Rework → MCTS → Verification → PR
  - Branches: ICRL Episodes (below), Autonomy (above)
  - Color coding per domain convention

Ref: docs/adr/ADR-027-review-feedback-loop.md
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda, Fargate
from diagrams.aws.database import Dynamodb
from diagrams.aws.integration import Eventbridge
from diagrams.aws.management import Cloudwatch
from diagrams.aws.network import APIGateway


def cl(bgcolor, pencolor, fontcolor):
    """Cluster styling helper."""
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
    filename="docs/architecture/review-feedback-icrl-loop",
    show=False,
    direction="LR",
    graph_attr={
        "ranksep": "1.4",
        "nodesep": "0.8",
        "splines": "curved",
        "newrank": "true",
        "pad": "0.4",
    },
):
    # Spine: Detection -> Processing -> Re-execution

    with Cluster("1. Detection\nGitHub Webhook", graph_attr=cl("#e8f0fe", "#1a73e8", "#1a73e8")):
        apigw = APIGateway("API Gateway\n/webhook/github")

    with Cluster("2. Classification\nReview Feedback", graph_attr=cl("#fef7e0", "#f9a825", "#f9a825")):
        eb_review = Eventbridge("EventBridge\nPR Review Rule")
        review_lambda = Lambda("Review Feedback\nLambda")

    with Cluster("3. Metrics & Learning\nDORA + ICRL", graph_attr=cl("#e8f5e9", "#43a047", "#43a047")):
        metrics_db = Dynamodb("Metrics Table\nDORA/Trust/Happy")
        icrl_store = Dynamodb("ICRL Episodes\nPattern Digest")

    with Cluster("4. Re-execution\nMCTS + Conductor", graph_attr=cl("#fce4ec", "#e53935", "#b71c1c")):
        eb_rework = Eventbridge("EventBridge\ntask.rework_requested")
        ecs_agent = Fargate("ECS Agent\nMCTS Planner")

    with Cluster("5. Verification Gate\nDeterministic Rewards", graph_attr=cl("#fff3e0", "#ef6c00", "#e65100")):
        verify = Lambda("Verification\nLinter+Types+Tests")

    with Cluster("6. Output\nNew PR", graph_attr=cl("#f3e5f5", "#8e24aa", "#6a1b9a")):
        pr_output = APIGateway("GitHub PR\n(annotated)")

    # Main Spine (high weight)
    apigw >> Edge(label="1. PR review event", weight="10", style="bold", color="#1a73e8") >> eb_review
    eb_review >> Edge(label="2. classify", weight="10", style="bold", color="#f9a825") >> review_lambda
    review_lambda >> Edge(label="3. record metrics", weight="10", style="bold", color="#43a047") >> metrics_db
    review_lambda >> Edge(label="4. emit rework", weight="10", style="bold", color="#e53935") >> eb_rework
    eb_rework >> Edge(label="5. MCTS explore", weight="10", style="bold", color="#e53935") >> ecs_agent
    ecs_agent >> Edge(label="6. verify", weight="10", style="bold", color="#ef6c00") >> verify
    verify >> Edge(label="7. create PR", weight="10", style="bold", color="#8e24aa") >> pr_output

    # Branch: ICRL Episode Storage (low weight)
    review_lambda >> Edge(label="store episode", weight="1", style="dashed", color="#43a047") >> icrl_store
    icrl_store >> Edge(label="inject context", weight="1", style="dashed", color="#43a047") >> ecs_agent

    # Branch: Monitoring (low weight)
    cw = Cloudwatch("CloudWatch\nAlarms")
    review_lambda >> Edge(label="circuit breaker", weight="1", style="dashed", color="#e53935") >> cw
