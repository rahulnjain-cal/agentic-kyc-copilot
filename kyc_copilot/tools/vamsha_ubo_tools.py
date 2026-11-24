"""Vamsha Deterministic Python Cascading UBO Ownership Calculator.

Named after *Vamsha* (Sanskrit: dynastic lineage / genealogical tree), this
module implements a simple, 100% deterministic Python graph roll-up engine so
LLMs NEVER mentally multiply multi-tier corporate ownership percentages.

Handles:
- Direct equity (>= 25%) and cascading multi-tier indirect equity multiplication
  (e.g., 65% Delaware intermediary * 50% Cayman parent = 32.5% effective equity).
- Class-B / super-voting rights overrides (>= 25% voting control even when
  equity < 25%).
- Unverified offshore trust / opaque layer detection (> 25% unverified).
- Circular holding loop detection and >100% cap-table integrity validation with
  guided recovery instructions.
- Senior Managing Official fallback when no individual crosses >= 25%.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from pydantic import ValidationError

from kyc_copilot.models.schemas import (
    ControlMechanism,
    CorporateGraphEdgesInput,
    OwnershipEdge,
    ToolResultEnvelope,
    UBOGraphResult,
    UBOParty,
)
from kyc_copilot.tools.registry_data import mint_snapshot_id


def _detect_cycle_nodes(edges: list[OwnershipEdge]) -> list[str]:
    """Simple 3-color DFS cycle detector returning offending cycle node IDs."""
    adjacency: dict[str, list[str]] = defaultdict(list)
    all_nodes: set[str] = set()
    for edge in edges:
        adjacency[edge.parent_id].append(edge.child_id)
        all_nodes.add(edge.parent_id)
        all_nodes.add(edge.child_id)

    color: dict[str, int] = {node: 0 for node in all_nodes}  # 0=white,1=gray,2=black
    offending: list[str] = []

    def _dfs(node: str, stack: list[str]) -> None:
        color[node] = 1
        stack.append(node)
        for nxt in adjacency.get(node, []):
            if color[nxt] == 1:
                cycle_start = stack.index(nxt)
                for cyc_node in stack[cycle_start:]:
                    if cyc_node not in offending:
                        offending.append(cyc_node)
            elif color[nxt] == 0:
                _dfs(nxt, stack)
        stack.pop()
        color[node] = 2

    for node in sorted(all_nodes):
        if color[node] == 0:
            _dfs(node, [])

    return offending


def calculate_cascading_ubo_ownership_rollup(
    case_id: str,
    target_entity_id: str,
    edges: list[dict[str, Any]],
    senior_managing_official_name: Optional[str] = None,
    equity_threshold_pct: float = 25.0,
    voting_threshold_pct: float = 25.0,
) -> dict[str, Any]:
    """Deterministically calculates cascading UBO equity and voting-rights control.

    Traverses the corporate ownership DAG upwards from `target_entity_id`,
    multiplying fractional equity across every path to sum each ultimate
    natural person's effective equity percentage and evaluating voting-rights
    overrides, offshore trust opacity, circular holdings, and cap-table sums.

    Args:
        case_id: Unique KYC case identifier.
        target_entity_id: Entity ID of the applicant operating company.
        edges: List of directed parent->child ownership edge dicts matching
            `OwnershipEdge` schema (`parent_id`, `parent_name`, `parent_type`,
            `child_id`, `equity_pct`, `voting_pct`, `jurisdiction_iso`, `verified`).
        senior_managing_official_name: Optional fallback controlling official
            name used only if zero individuals reach equity or voting thresholds.
        equity_threshold_pct: Regulatory UBO equity threshold (default 25.0%).
        voting_threshold_pct: Regulatory voting control threshold (default 25.0%).

    Returns:
        JSON-serializable `ToolResultEnvelope[UBOGraphResult]` dict. If a
        circular holding loop or >100% ownership sum is detected, returns
        `status="RECOVERABLE_ERROR"` with exact `offending_node_ids` and
        explicit Controlling Person recovery instructions.
    """
    snapshot_id = mint_snapshot_id("UBO")
    try:
        graph_input = CorporateGraphEdgesInput(
            case_id=case_id,
            target_entity_id=target_entity_id,
            edges=edges,  # type: ignore[arg-type]
            senior_managing_official_name=senior_managing_official_name,
            equity_threshold_pct=equity_threshold_pct,
            voting_threshold_pct=voting_threshold_pct,
        )
    except ValidationError as exc:
        return ToolResultEnvelope[UBOGraphResult](
            status="RECOVERABLE_ERROR",
            data=None,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                f"Ownership graph input invalid ({exc.error_count()} error(s)). "
                "Verify equity_pct and voting_pct are between 0 and 100."
            ),
        ).model_dump(mode="json")

    # 1. Integrity checks: circular holding loops & >100% child cap-table sums
    cycle_nodes = _detect_cycle_nodes(graph_input.edges)
    equity_by_child: dict[str, float] = defaultdict(float)
    parents_by_child: dict[str, list[OwnershipEdge]] = defaultdict(list)

    for edge in graph_input.edges:
        equity_by_child[edge.child_id] += edge.equity_pct
        parents_by_child[edge.child_id].append(edge)

    overflow_nodes = [
        child_id
        for child_id, total_eq in equity_by_child.items()
        if total_eq > 100.01
    ]
    offending_nodes = sorted(set(cycle_nodes + overflow_nodes))

    if offending_nodes:
        err_result = UBOGraphResult(
            target_entity_id=graph_input.target_entity_id,
            identified_ubos=[],
            opaque_layer_detected=True,
            offending_node_ids=offending_nodes,
            mermaid_or_json_tree={
                "target": graph_input.target_entity_id,
                "error_nodes": offending_nodes,
                "edges": [e.model_dump() for e in graph_input.edges],
            },
        )
        return ToolResultEnvelope[UBOGraphResult](
            status="RECOVERABLE_ERROR",
            data=err_result,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                "Flag opaque_layer_detected=True and inspect voting_pct via "
                f"Controlling Person rules. Offending nodes: {offending_nodes}"
            ),
        ).model_dump(mode="json")

    # 2. Deterministic upward traversal accumulating effective equity & voting
    effective_equity: dict[str, float] = defaultdict(float)
    effective_voting: dict[str, float] = defaultdict(float)
    party_meta: dict[str, OwnershipEdge] = {}
    party_paths: dict[str, list[str]] = defaultdict(list)
    party_depth: dict[str, int] = {}
    opaque_layer_detected = False

    def _walk_up(
        current_child: str,
        equity_multiplier: float,
        voting_multiplier: float,
        depth: int,
        trail: list[str],
    ) -> None:
        nonlocal opaque_layer_detected
        for edge in parents_by_child.get(current_child, []):
            path_equity = equity_multiplier * (edge.equity_pct / 100.0)
            path_voting = voting_multiplier * (edge.voting_pct / 100.0)
            step_label = (
                f"{edge.parent_name} ({edge.equity_pct:g}% eq / {edge.voting_pct:g}% vote)"
            )
            new_trail = [step_label, *trail]

            if edge.parent_type == "OFFSHORE_TRUST":
                if not edge.verified and (path_equity * 100.0) >= graph_input.equity_threshold_pct:
                    opaque_layer_detected = True
                # Treat unverified trust as terminal opaque layer if it has no parents.
                if not parents_by_child.get(edge.parent_id):
                    party_meta[edge.parent_id] = edge
                    effective_equity[edge.parent_id] += path_equity * 100.0
                    effective_voting[edge.parent_id] += path_voting * 100.0
                    party_paths[edge.parent_id].append(" -> ".join(new_trail))
                    party_depth[edge.parent_id] = max(party_depth.get(edge.parent_id, 0), depth)
                    continue

            if edge.parent_type == "INDIVIDUAL":
                party_meta[edge.parent_id] = edge
                effective_equity[edge.parent_id] += path_equity * 100.0
                effective_voting[edge.parent_id] += path_voting * 100.0
                party_paths[edge.parent_id].append(" -> ".join(new_trail))
                party_depth[edge.parent_id] = max(party_depth.get(edge.parent_id, 0), depth)
            else:
                _walk_up(
                    current_child=edge.parent_id,
                    equity_multiplier=path_equity,
                    voting_multiplier=path_voting,
                    depth=depth + 1,
                    trail=new_trail,
                )

    _walk_up(
        current_child=graph_input.target_entity_id,
        equity_multiplier=1.0,
        voting_multiplier=1.0,
        depth=1,
        trail=[graph_input.target_entity_id],
    )

    identified_ubos: list[UBOParty] = []
    for party_id, meta in party_meta.items():
        eff_eq = round(effective_equity[party_id], 2)
        eff_vote = round(effective_voting[party_id], 2)
        meets_equity = eff_eq >= graph_input.equity_threshold_pct
        meets_voting = eff_vote >= graph_input.voting_threshold_pct

        if not (meets_equity or meets_voting):
            continue

        mechanism: ControlMechanism
        if meta.parent_type == "OFFSHORE_TRUST":
            mechanism = "TRUSTEE_CONTROL"
        elif not meets_equity and meets_voting:
            mechanism = "VOTING_RIGHTS_OVERRIDE"
        elif party_depth.get(party_id, 1) > 1:
            mechanism = "INDIRECT_ROLLUP"
        else:
            mechanism = "DIRECT_EQUITY"

        identified_ubos.append(
            UBOParty(
                party_id=party_id,
                full_name=meta.parent_name,
                effective_equity_pct=eff_eq,
                effective_voting_pct=eff_vote,
                control_mechanism=mechanism,
                jurisdiction_iso=meta.jurisdiction_iso,
                ownership_paths=party_paths[party_id],
                verified=meta.verified,
            )
        )

    # Sort deterministically by effective equity descending, then voting descending
    identified_ubos.sort(
        key=lambda u: (u.effective_equity_pct, u.effective_voting_pct),
        reverse=True,
    )

    # Senior Managing Official fallback when zero UBOs cross thresholds
    if not identified_ubos and graph_input.senior_managing_official_name:
        identified_ubos.append(
            UBOParty(
                party_id="SMO-FALLBACK-01",
                full_name=graph_input.senior_managing_official_name,
                effective_equity_pct=0.0,
                effective_voting_pct=0.0,
                control_mechanism="SENIOR_MANAGING_OFFICIAL",
                jurisdiction_iso="GB",
                ownership_paths=[
                    f"Senior Managing Official fallback for {graph_input.target_entity_id}"
                ],
                verified=True,
            )
        )

    mermaid_lines = ["graph TD"]
    for edge in graph_input.edges:
        mermaid_lines.append(
            f'  {edge.parent_id}["{edge.parent_name}"] -->|"{edge.equity_pct:g}% eq / {edge.voting_pct:g}% vote"| {edge.child_id}'
        )

    result = UBOGraphResult(
        target_entity_id=graph_input.target_entity_id,
        identified_ubos=identified_ubos,
        opaque_layer_detected=opaque_layer_detected,
        offending_node_ids=[],
        mermaid_or_json_tree={
            "target_entity_id": graph_input.target_entity_id,
            "mermaid": "\n".join(mermaid_lines),
            "nodes": [u.model_dump() for u in identified_ubos],
        },
    )
    return ToolResultEnvelope[UBOGraphResult](
        status="SUCCESS",
        data=result,
        snapshot_id=snapshot_id,
        recovery_instruction=None,
    ).model_dump(mode="json")
