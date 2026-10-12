"""Initial-optimization gate: every active rider must have a confirmed, valid endpoint.

Issue messages name riders and reasons only — never another rider's coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import DeliveryRound, EndpointKind


@dataclass(frozen=True)
class GateIssue:
    rider_id: str
    reason: str  # missing | unconfirmed | invalid_location


def endpoint_gate_issues(rnd: DeliveryRound) -> list[GateIssue]:
    issues: list[GateIssue] = []
    for rider in rnd.active_riders():
        ep = rider.endpoint
        if ep is None:
            issues.append(GateIssue(rider.id, "missing"))
            continue
        if ep.kind in (EndpointKind.HOME, EndpointKind.CUSTOM):
            if ep.location_id is None or ep.location_id not in rnd.locations:
                issues.append(GateIssue(rider.id, "invalid_location"))
                continue
        elif ep.location_id is not None and ep.kind is EndpointKind.LAST_STOP:
            issues.append(GateIssue(rider.id, "invalid_location"))
            continue
        if not ep.confirmed:
            issues.append(GateIssue(rider.id, "unconfirmed"))
    return issues
