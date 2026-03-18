# Internal Deliverable Templates

Company internal templates used as fallback when customer templates are not available.

## Lookup Priority

1. Customer template (from n01 `deliverables_required[].template_file`) — preferred
2. Internal template (this directory) — fallback
3. Node generates blank format — last resort

## Naming Convention

```
<deliverable-id>-<short-name>.xlsx
```

Examples:
- `D-02-edd-pbd.xlsx` — ED&D PBD cost breakdown
- `D-03-sdt.xlsx` — Supplier Development Team
- `D-14-dvpr.xlsx` — DVPR plan

## Adding Templates

Place templates here as nodes are developed. Each node guide specifies which deliverables it is responsible for filling. See `references/artifact-schema.md` → "Deliverable Template Lifecycle" for the full contract.
