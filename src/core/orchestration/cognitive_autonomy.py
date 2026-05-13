"""
Cognitive Autonomy — Decoupled Capability Depth + Delivery Authority.

FUNDAMENTAL CHANGE (ADR-029):
  The factory no longer uses a single "autonomy level" (L1-L5) to control
  both HOW it executes and WHAT it's allowed to do with the output.

  Instead, two orthogonal axes:
    1. Capability Depth (0.0-1.0): How much reasoning power to apply
       - Determined by: Risk Engine score + cognitive signals
       - NEVER decreases on failure (failure = harder task = needs MORE capability)

    2. Delivery Authority (earned): What the factory is allowed to do with output
       - Determined by: output quality (L1 reviewer + L2 score + verification gate)
       - CAN decrease on failure (trust must be re-earned)

  The Anti-Instability Loop only reduces AUTHORITY, never CAPABILITY.
  Past failures INCREASE the capability floor (more agents, more verification).

Feature flag: COGNITIVE_AUTONOMY_ENABLED (default: true)
Ref: docs/adr/ADR-029-cognitive-autonomy-model.md
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("fde.orchestration.cognitive_autonomy")

_COGNITIVE_AUTONOMY_ENABLED = os.environ.get(
    "COGNITIVE_AUTONOMY_ENABLED", "true"
).lower() == "true"

_DEPTH_LOW = 0.3
_DEPTH_MEDIUM = 0.5
_DEPTH_HIGH = 0.7
_DEPTH_MAXIMUM = 0.85

_AUTHORITY_AUTO_MERGE_MIN_TRUST = 0.80
_AUTHORITY_CFR_BLOCK_THRESHOLD = 0.30


@dataclass
class CapabilityProfile:
    """How much reasoning power to apply (the HOW axis)."""

    depth: float
    squad_size: int
    model_tier: str
    verification_level: str
    include_adversarial: bool
    include_pr_reviewer: bool
    include_architect: bool
    topology_recommendation: str
    contributing_signals: dict[str, float] = field(default_factory=dict)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "depth": round(self.depth, 3),
            "squad_size": self.squad_size,
            "model_tier": self.model_tier,
            "verification_level": self.verification_level,
            "include_adversarial": self.include_adversarial,
            "include_pr_reviewer": self.include_pr_reviewer,
            "include_architect": self.include_architect,
            "topology_recommendation": self.topology_recommendation,
            "contributing_signals": {k: round(v, 3) for k, v in self.contributing_signals.items()},
            "rationale": self.rationale,
        }


@dataclass
class DeliveryAuthorityProfile:
    """What the factory is allowed to do with output (the TRUST axis)."""

    can_auto_merge: bool
    requires_human_review: bool
    requires_staff_engineer: bool
    authority_level: str
    cfr_current: float = 0.0
    trust_score: float = 0.0
    consecutive_successes: int = 0
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_auto_merge": self.can_auto_merge,
            "requires_human_review": self.requires_human_review,
            "requires_staff_engineer": self.requires_staff_engineer,
            "authority_level": self.authority_level,
            "cfr_current": round(self.cfr_current, 3),
            "trust_score": round(self.trust_score, 3),
            "consecutive_successes": self.consecutive_successes,
            "rationale": self.rationale,
        }


@dataclass
class CognitiveAutonomyDecision:
    """Complete cognitive autonomy decision — replaces static L1-L5."""

    capability: CapabilityProfile
    authority: DeliveryAuthorityProfile
    timestamp: str = ""
    legacy_autonomy_level: int = 4

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.authority.requires_staff_engineer:
            self.legacy_autonomy_level = 1
        elif self.authority.requires_human_review and not self.authority.can_auto_merge:
            self.legacy_autonomy_level = 3
        elif self.authority.can_auto_merge:
            self.legacy_autonomy_level = 5
        else:
            self.legacy_autonomy_level = 4

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability.to_dict(),
            "authority": self.authority.to_dict(),
            "legacy_autonomy_level": self.legacy_autonomy_level,
            "timestamp": self.timestamp,
        }


def compute_capability_depth(
    risk_score: float = 0.0,
    synapse_signals: dict[str, float] | None = None,
    dependency_count: int = 0,
    blocking_count: int = 0,
    icrl_failure_count: int = 0,
    cfr_history: float = 0.0,
) -> CapabilityProfile:
    """Compute capability depth from cognitive signals.

    NEVER decreases on failure. Failures indicate harder task = MORE capability.
    """
    signals = synapse_signals or {}
    depth = risk_score

    # Integration complexity raises floor
    if dependency_count >= 4:
        depth = max(depth, 0.6)
    elif dependency_count >= 2:
        depth = max(depth, 0.4)

    # Critical path raises floor
    if blocking_count >= 3:
        depth = max(depth, 0.7)

    # Past failures INCREASE capability (recovery, not punishment)
    if icrl_failure_count >= 3:
        depth = max(depth, 0.8)
    elif icrl_failure_count >= 1:
        depth = max(depth, 0.5)

    # High CFR raises capability floor (recovery mechanism)
    if cfr_history > 0.15:
        depth = max(depth, 0.6)
    if cfr_history > 0.30:
        depth = max(depth, 0.8)

    # Synapse signals (fine-tuning)
    decomposition_cost = signals.get("decomposition_cost_ratio", 0.0)
    if decomposition_cost > 0.7:
        depth = max(depth, 0.7)

    catalog_confidence = signals.get("catalog_confidence", 1.0)
    if catalog_confidence < 0.5:
        depth = max(depth, 0.5)

    interface_depth = signals.get("interface_depth_ratio", 0.5)
    if interface_depth > 0.8:
        depth = max(depth, 0.6)

    depth = max(0.0, min(1.0, depth))
    profile = _map_depth_to_profile(depth)

    profile.contributing_signals = {
        "risk_score": risk_score,
        "dependency_count": float(dependency_count),
        "blocking_count": float(blocking_count),
        "icrl_failure_count": float(icrl_failure_count),
        "cfr_history": cfr_history,
        "decomposition_cost": decomposition_cost,
        "catalog_confidence": catalog_confidence,
        "interface_depth": interface_depth,
    }
    profile.rationale = (
        f"Depth={depth:.2f}: risk={risk_score:.2f}, deps={dependency_count}, "
        f"blocks={blocking_count}, failures={icrl_failure_count}, cfr={cfr_history:.2f}"
    )

    logger.info(
        "Capability: depth=%.2f squad=%d model=%s verify=%s",
        depth, profile.squad_size, profile.model_tier, profile.verification_level,
    )
    return profile


def _map_depth_to_profile(depth: float) -> CapabilityProfile:
    """Map continuous depth to concrete execution parameters."""
    if depth >= _DEPTH_MAXIMUM:
        return CapabilityProfile(
            depth=depth, squad_size=8, model_tier="deep",
            verification_level="full_mcts", include_adversarial=True,
            include_pr_reviewer=True, include_architect=True,
            topology_recommendation="debate",
        )
    elif depth >= _DEPTH_HIGH:
        return CapabilityProfile(
            depth=depth, squad_size=6, model_tier="reasoning",
            verification_level="full", include_adversarial=True,
            include_pr_reviewer=True, include_architect=True,
            topology_recommendation="tree",
        )
    elif depth >= _DEPTH_MEDIUM:
        return CapabilityProfile(
            depth=depth, squad_size=4, model_tier="standard",
            verification_level="standard", include_adversarial=True,
            include_pr_reviewer=False, include_architect=False,
            topology_recommendation="sequential",
        )
    else:
        return CapabilityProfile(
            depth=depth, squad_size=2, model_tier="fast",
            verification_level="minimal", include_adversarial=False,
            include_pr_reviewer=False, include_architect=False,
            topology_recommendation="sequential",
        )


def compute_delivery_authority(
    cfr_current: float = 0.0,
    trust_score: float = 0.0,
    consecutive_successes: int = 0,
    staff_engineer_override: bool = False,
) -> DeliveryAuthorityProfile:
    """Compute delivery authority from trust signals.

    Authority is EARNED by output quality, not assumed by labels.
    CAN decrease on failure (trust must be re-earned).
    """
    if staff_engineer_override:
        return DeliveryAuthorityProfile(
            can_auto_merge=False, requires_human_review=True,
            requires_staff_engineer=True, authority_level="blocked",
            cfr_current=cfr_current, trust_score=trust_score,
            consecutive_successes=consecutive_successes,
            rationale="Staff Engineer override — manual review required",
        )

    if cfr_current > _AUTHORITY_CFR_BLOCK_THRESHOLD:
        return DeliveryAuthorityProfile(
            can_auto_merge=False, requires_human_review=True,
            requires_staff_engineer=True, authority_level="blocked",
            cfr_current=cfr_current, trust_score=trust_score,
            consecutive_successes=consecutive_successes,
            rationale=f"CFR {cfr_current:.1%} > {_AUTHORITY_CFR_BLOCK_THRESHOLD:.0%} — blocked",
        )

    trust_normalized = trust_score / 100.0 if trust_score > 1.0 else trust_score
    can_auto = (
        cfr_current < 0.10
        and trust_normalized >= _AUTHORITY_AUTO_MERGE_MIN_TRUST
        and consecutive_successes >= 3
    )

    if can_auto:
        return DeliveryAuthorityProfile(
            can_auto_merge=True, requires_human_review=False,
            requires_staff_engineer=False, authority_level="auto_merge",
            cfr_current=cfr_current, trust_score=trust_score,
            consecutive_successes=consecutive_successes,
            rationale=f"Auto-merge earned: CFR={cfr_current:.1%}, trust={trust_normalized:.0%}, successes={consecutive_successes}",
        )

    return DeliveryAuthorityProfile(
        can_auto_merge=False, requires_human_review=True,
        requires_staff_engineer=False, authority_level="ready_for_review",
        cfr_current=cfr_current, trust_score=trust_score,
        consecutive_successes=consecutive_successes,
        rationale=f"Human review: CFR={cfr_current:.1%}, trust={trust_normalized:.0%}, successes={consecutive_successes} (need>=3)",
    )


def compute_cognitive_autonomy(
    risk_score: float = 0.0,
    synapse_signals: dict[str, float] | None = None,
    dependency_count: int = 0,
    blocking_count: int = 0,
    icrl_failure_count: int = 0,
    cfr_current: float = 0.0,
    trust_score: float = 0.0,
    consecutive_successes: int = 0,
    staff_engineer_override: bool = False,
) -> CognitiveAutonomyDecision:
    """Main entry point — replaces compute_autonomy_level().

    Produces both capability (how to execute) and authority (what to do
    with output) as independent axes.
    """
    if not _COGNITIVE_AUTONOMY_ENABLED:
        return _legacy_fallback()

    capability = compute_capability_depth(
        risk_score=risk_score,
        synapse_signals=synapse_signals,
        dependency_count=dependency_count,
        blocking_count=blocking_count,
        icrl_failure_count=icrl_failure_count,
        cfr_history=cfr_current,
    )

    authority = compute_delivery_authority(
        cfr_current=cfr_current,
        trust_score=trust_score,
        consecutive_successes=consecutive_successes,
        staff_engineer_override=staff_engineer_override,
    )

    decision = CognitiveAutonomyDecision(capability=capability, authority=authority)

    logger.info(
        "Cognitive autonomy: depth=%.2f squad=%d authority=%s legacy=L%d",
        capability.depth, capability.squad_size,
        authority.authority_level, decision.legacy_autonomy_level,
    )
    return decision


def _legacy_fallback() -> CognitiveAutonomyDecision:
    """Fallback when cognitive autonomy is disabled."""
    return CognitiveAutonomyDecision(
        capability=CapabilityProfile(
            depth=0.5, squad_size=4, model_tier="reasoning",
            verification_level="standard", include_adversarial=True,
            include_pr_reviewer=False, include_architect=False,
            topology_recommendation="sequential",
            rationale="Legacy fallback (COGNITIVE_AUTONOMY_ENABLED=false)",
        ),
        authority=DeliveryAuthorityProfile(
            can_auto_merge=False, requires_human_review=True,
            requires_staff_engineer=False, authority_level="ready_for_review",
            rationale="Legacy fallback — human review always required",
        ),
        legacy_autonomy_level=3,
    )
