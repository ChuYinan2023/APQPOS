#!/usr/bin/env python3
"""APQP Orchestrator — manage project DAG state.

Commands:
  status   <project_path> [--json]  Show all nodes with current status
  init     <project_path>           Initialize a new project directory
           [--customer NAME]
           [--rfq file1 file2 ...]
  affected <project_path> <node_id> List downstream nodes affected by a change (topological order)
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

# store.py lives next to this script
sys.path.insert(0, str(Path(__file__).parent))
from store import ArtifactStore

NETWORK_JSON = Path(__file__).parent.parent / "references" / "network.json"

STATUS_ICON = {
    "pending":       "⬜",
    "ready":         "✅",
    "done":          "✓ ",
    "waiting_human": "⏸ ",
    "blocked":       "🚫",
}


def load_network() -> dict:
    return json.loads(NETWORK_JSON.read_text())


def get_ready_nodes(network: dict, done: set[str]) -> list[dict]:
    ready = []
    for node in network["nodes"]:
        nid = node["id"]
        if nid in done:
            continue
        # Only main/normal/secondary edges are blocking; feedback edges are not
        deps = [
            e["from"] for e in network["edges"]
            if e["to"] == nid and e["type"] != "feedback"
        ]
        if all(d in done or d.startswith("ext-") for d in deps):
            ready.append(node)
    return ready


def get_downstream(network: dict, node_id: str) -> list[str]:
    """Return all downstream nodes affected by a change to node_id, in topological order.

    Traverses main/normal/secondary edges (not feedback) from node_id outward.
    """
    # Build adjacency list (forward edges, excluding feedback)
    adj: dict[str, list[str]] = {}
    for e in network["edges"]:
        if e["type"] != "feedback":
            adj.setdefault(e["from"], []).append(e["to"])

    # BFS to find all reachable downstream nodes
    visited = set()
    queue = list(adj.get(node_id, []))
    while queue:
        nid = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        queue.extend(adj.get(nid, []))

    # Sort by topological order (preserve node list order from network.json)
    node_order = {n["id"]: i for i, n in enumerate(network["nodes"])}
    return sorted(visited, key=lambda x: node_order.get(x, 999))


def build_status_data(project_path: str) -> dict:
    """Build structured status data for both text and JSON output."""
    store = ArtifactStore(project_path)
    network = load_network()
    done = store.list_done()
    p = Path(project_path)

    # Read project.json for metadata
    proj = {}
    proj_file = p / "project.json"
    if proj_file.exists():
        try:
            proj = json.loads(proj_file.read_text())
        except Exception:
            pass

    nodes = []
    all_gaps = []
    all_assumptions = []
    total_assumptions_count = 0

    for node in network["nodes"]:
        nid = node["id"]
        status = store.get_status(nid)
        node_info = {
            "id": nid,
            "name": node.get("name", ""),
            "type": node.get("type", ""),
            "status": status,
            "confidence_floor": None,
            "gap_error": 0,
            "gap_warning": 0,
            "gap_info": 0,
        }

        # Read artifact for data quality info
        artifact = store.read(nid)
        if artifact:
            node_info["confidence_floor"] = artifact.get("confidence_floor")
            for g in artifact.get("gaps", []):
                sev = g.get("severity", "info")
                if sev == "error":
                    node_info["gap_error"] += 1
                elif sev == "warning":
                    node_info["gap_warning"] += 1
                else:
                    node_info["gap_info"] += 1
                all_gaps.append({
                    "node": nid,
                    "rule": g.get("rule", ""),
                    "msg": g.get("msg", ""),
                    "severity": sev,
                })
            assumptions = artifact.get("assumptions", [])
            total_assumptions_count += len(assumptions)

        nodes.append(node_info)

    ready = get_ready_nodes(network, done)
    ready_ids = [n["id"] for n in ready]

    # Deliverables status (from n01 if available)
    deliverables_total = 0
    deliverables_generated = 0
    deliverables_phase = 0
    current_phase = proj.get("current_phase", "SOURCING")
    n01 = store.read("n01")
    if n01:
        delivs = n01.get("payload", {}).get("deliverables_required", [])
        deliverables_total = len(delivs)
        deliverables_generated = sum(1 for d in delivs if d.get("output_file"))
        deliverables_phase = sum(1 for d in delivs if current_phase in d.get("phase", ""))

    # Confidence floor across all nodes
    all_conf = [n["confidence_floor"] for n in nodes if n["confidence_floor"]]
    overall_confidence = max(all_conf, key=lambda s: int(s[1:])) if all_conf else None

    # Sort gaps by severity for top open items
    severity_order = {"error": 0, "warning": 1, "info": 2}
    all_gaps.sort(key=lambda g: severity_order.get(g["severity"], 9))

    return {
        "project": str(p.resolve()),
        "customer": proj.get("customer", ""),
        "current_phase": current_phase,
        "nodes": nodes,
        "done": sorted(done),
        "ready": ready_ids,
        "overall_confidence": overall_confidence,
        "total_gaps": {"error": sum(1 for g in all_gaps if g["severity"]=="error"),
                       "warning": sum(1 for g in all_gaps if g["severity"]=="warning"),
                       "info": sum(1 for g in all_gaps if g["severity"]=="info")},
        "total_assumptions": total_assumptions_count,
        "deliverables": {"total": deliverables_total, "phase_required": deliverables_phase,
                         "generated": deliverables_generated, "phase": current_phase},
        "top_open_items": all_gaps[:8],
    }


def cmd_status(project_path: str, as_json: bool = False) -> None:
    data = build_status_data(project_path)

    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    W = 70  # output width

    # ── Header ─────────────────────────────────────────────────────────
    customer = data.get("customer", "")
    phase = data.get("current_phase", "")
    proj_name = Path(data["project"]).name
    print(f"\nProject: {proj_name} | Customer: {customer} | Phase: {phase}")
    print("═" * W)

    # ── Node table ─────────────────────────────────────────────────────
    print(f"{'Node':<6} {'Status':<10} {'Conf':<5} {'Gaps':<12} Name")
    print("─" * W)
    for node in data["nodes"]:
        icon = STATUS_ICON.get(node["status"], "? ")
        conf = node.get("confidence_floor") or "—"
        # Build gap string
        gap_parts = []
        if node["gap_error"]:
            gap_parts.append(f"{node['gap_error']}❌")
        if node["gap_warning"]:
            gap_parts.append(f"{node['gap_warning']}⚠️")
        if node["gap_info"]:
            gap_parts.append(f"{node['gap_info']}ℹ️")
        gap_str = " ".join(gap_parts) if gap_parts else "—"
        tag = " [human]" if node["type"] == "human" else ""
        print(f"{node['id']:<6} {icon} {node['status']:<7} {conf:<5} {gap_str:<12} {node['name']}{tag}")

    # ── Ready to run ───────────────────────────────────────────────────
    done = set(data["done"])
    if data["ready"]:
        print(f"\n▶ Ready to run: {', '.join(data['ready'])}")
    else:
        network = load_network()
        all_ids = {n["id"] for n in network["nodes"]}
        if done >= all_ids:
            print("\n✓ All nodes complete.")
        else:
            print("\n⏸ Waiting for human input or external files.")

    # ── Summary ────────────────────────────────────────────────────────
    print(f"\n{'═' * W}")
    print("Summary:")
    oc = data.get("overall_confidence", "—")
    tg = data["total_gaps"]
    ta = data["total_assumptions"]
    dl = data["deliverables"]
    print(f"  Progress:     {len(done)}/18 nodes complete")
    print(f"  Confidence:   {oc}")
    print(f"  Gaps:         {tg['error']} error, {tg['warning']} warning, {tg['info']} info")
    print(f"  Assumptions:  {ta}")
    print(f"  Deliverables: {dl['generated']}/{dl['phase_required']} generated ({dl['phase']} phase)")

    # ── Top open items ─────────────────────────────────────────────────
    top = data.get("top_open_items", [])
    if top:
        print(f"\n⚠ Top open items:")
        sev_icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}
        for i, g in enumerate(top[:6], 1):
            icon = sev_icon.get(g["severity"], "·")
            msg = g["msg"][:60]
            print(f"  {i}. {g['rule']} {icon} {msg}")
    print()


def cmd_affected(project_path: str, node_id: str, as_json: bool = False) -> None:
    network = load_network()
    store = ArtifactStore(project_path)

    downstream = get_downstream(network, node_id)

    # Filter to only nodes that have existing artifacts (need re-run)
    node_names = {n["id"]: n["name"] for n in network["nodes"]}
    affected = []
    for nid in downstream:
        status = store.get_status(nid)
        affected.append({
            "id": nid,
            "name": node_names.get(nid, ""),
            "status": status,
            "has_artifact": status != "pending",
        })

    result = {
        "source": node_id,
        "downstream_total": len(downstream),
        "need_rerun": [a["id"] for a in affected if a["has_artifact"]],
        "not_yet_run": [a["id"] for a in affected if not a["has_artifact"]],
        "affected": affected,
    }

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"\n{'='*55}")
    print(f"  Affected by change to: {node_id} ({node_names.get(node_id, '')})")
    print(f"{'='*55}")
    print(f"\n  Downstream nodes: {len(downstream)}")

    if result["need_rerun"]:
        print(f"\n  ⚠ Need re-run ({len(result['need_rerun'])}):")
        for nid in result["need_rerun"]:
            print(f"    → {nid} ({node_names.get(nid, '')})")

    if result["not_yet_run"]:
        print(f"\n  ○ Not yet run ({len(result['not_yet_run'])}):")
        for nid in result["not_yet_run"]:
            print(f"    · {nid} ({node_names.get(nid, '')})")

    print()


def cmd_init(project_path: str, customer: str = "", rfq_files: list[str] = None) -> None:
    p = Path(project_path)
    (p / "inputs").mkdir(parents=True, exist_ok=True)
    (p / "artifacts").mkdir(parents=True, exist_ok=True)
    (p / "logs").mkdir(parents=True, exist_ok=True)
    (p / "reports").mkdir(parents=True, exist_ok=True)

    proj_file = p / "project.json"
    if proj_file.exists():
        print(f"Project already exists: {project_path}")
        return

    proj = {
        "id": p.name,
        "customer": customer,
        "current_phase": "SOURCING",
        "rfq_files": rfq_files or [],
        "known_gaps": {
            "annual_volume": None,
            "sop_date": None,
            "3d_model_available": False,
        },
        "created_at": date.today().isoformat(),
    }
    proj_file.write_text(json.dumps(proj, ensure_ascii=False, indent=2))
    print(f"✅ Project initialized: {p.resolve()}")
    print(f"   Copy RFQ files into: {p.resolve() / 'inputs'}/")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Show DAG status")
    p_status.add_argument("project_path")
    p_status.add_argument("--json", action="store_true", help="Output as JSON")

    p_init = sub.add_parser("init", help="Initialize a new project")
    p_init.add_argument("project_path")
    p_init.add_argument("--customer", default="", help="OEM name")
    p_init.add_argument("--rfq", nargs="*", default=[], dest="rfq_files", help="RFQ file names")

    p_affected = sub.add_parser("affected", help="List downstream nodes affected by a change")
    p_affected.add_argument("project_path")
    p_affected.add_argument("node_id", help="Source node ID (e.g. n03)")
    p_affected.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.cmd == "status":
        cmd_status(args.project_path, as_json=args.json)
    elif args.cmd == "init":
        cmd_init(args.project_path, args.customer, args.rfq_files)
    elif args.cmd == "affected":
        cmd_affected(args.project_path, args.node_id, as_json=args.json)


if __name__ == "__main__":
    main()
