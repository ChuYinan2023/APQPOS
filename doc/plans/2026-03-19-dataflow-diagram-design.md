# Dataflow Diagram Generator — Design

## Summary

Auto-generate a single-file HTML dataflow diagram for APQP-OS projects. Updated after every node execution, progressively showing the 18-node DAG with real data from artifacts.

## Core Decisions

| Item | Decision |
|------|----------|
| Timing | After every node completion (progressive) |
| Layout | Template-based fixed coordinates (from FBFS verified layout) |
| Implementation | Pure Python script `scripts/diagram.py`, no external deps |
| Pending nodes | Grey + dashed border + "—" placeholder |
| Node details | Click opens right-side drawer panel (payload/gaps/assumptions) |
| Bottom sections | Cost breakdown bar + reliability risk matrix (both auto from artifacts) |

## Architecture

```
scripts/diagram.py
├── class DataflowDiagram
│   ├── __init__(project_path)      # Load all artifacts via ArtifactStore
│   ├── _load_artifacts()           # Read all nXX-output.json
│   ├── _render_header()            # Project title + RC/NRC stats
│   ├── _render_node_svg(node_id)   # Single node SVG: colored or grey
│   ├── _render_edge_svg(edge)      # Edge: solid+particle or grey dashed
│   ├── _render_cost_bar()          # Cost breakdown bar (n16 data)
│   ├── _render_reliability()       # Reliability matrix (S3/S4 assumptions)
│   ├── _render_drawer_js()         # Side drawer JS + node data injection
│   └── generate()                  # Assemble full HTML → artifacts/dataflow-diagram.html
```

## Node Data Extraction Mapping

| Node | SVG display | Source fields |
|------|-------------|---------------|
| n01 | File count, requirement count, pipe spec | payload.source_index, payload.requirements |
| n03 | Geometry summary | payload.geometry |
| n04 | Component count, make/buy split | payload.components, payload.make_buy |
| n05 | Key material unit prices | payload.materials |
| n06 | Net weight / gross weight | payload.weight_summary |
| n08 | Process count, equipment investment | payload.process_steps, payload.investment |
| n11 | Material cost EUR/pc | payload.total, payload.make_total, payload.buy_total |
| n12 | Conversion cost EUR/pc | payload.total_conversion_cost_eur |
| n15 | EDD total | payload.edd_total_eur |
| n16 | RC unit price + cost structure % | payload.total_rc_eur, payload.cost_breakdown_pct |
| n17 | NRC per piece | payload.nrc_per_piece_eur |
| n18 | Final quotation + annual revenue | payload.quotation_summary |
| Others | Node name + status + confidence | envelope fields |

## Side Drawer Content

```
┌─────────────────────────┐
│ N11 · Material Cost [×] │
│ Status: ready  Conf: S4 │
│─────────────────────────│
│ ▸ Calculation Results   │
│   (full payload table)  │
│─────────────────────────│
│ ▸ Gaps (count)          │
│   severity + rule + msg │
│─────────────────────────│
│ ▸ Assumptions (count)   │
│   confidence + details  │
│─────────────────────────│
│ ▸ Upstream: n05, n06    │
│ ▸ Downstream: n16       │
└─────────────────────────┘
```

## Integration

In SKILL.md Node Execution Pattern, add step 7.5 after report writing:

```python
from diagram import DataflowDiagram
DataflowDiagram(project_path).generate()
```

## Cost Breakdown Bar Fix

- Use CSS `flex` percentages instead of absolute flex values
- Hover: `transform: scaleX(1.05)` + highlight instead of changing flex-grow
- Click segment: show detail (amount, percentage, source node)

## Visual States

- **Completed node**: Colored fill + border matching phase color, real data, solid edges with animated particles
- **Pending node**: `#1a1f2e` fill, `#2a3040` border (dashed), "—" for data, grey dashed edges, no particles
- **Phase labels**: Always visible regardless of node status
