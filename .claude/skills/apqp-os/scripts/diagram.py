"""APQP-OS dataflow diagram generator.

Reads all nXX-output.json artifacts and network.json, produces a single-file
HTML visualization at artifacts/dataflow-diagram.html.

Usage:
    from diagram import DataflowDiagram
    d = DataflowDiagram('FBFS')
    path = d.generate()
"""
import json
import html as html_mod
from datetime import datetime, timezone
from pathlib import Path

from store import ArtifactStore

# ── Node display names (Chinese) ────────────────────────────────────────────
NODE_NAMES = {
    "n01": "RFQ 提取",       "n02": "DRG 指标",
    "n03": "组件树",          "n04": "BOM 清单",
    "n05": "材料选型",        "n06": "用量计算",
    "n07": "DFMEA",           "n08": "工艺路线",
    "n09": "DVP&R",           "n10": "PFD",
    "n11": "材料成本",        "n12": "转化成本",
    "n13": "产能规划",        "n14": "项目计划",
    "n15": "EDD",             "n16": "RC 成本",
    "n17": "NRC 总投入",      "n18": "报价",
}

ALL_NODES = [f"n{i:02d}" for i in range(1, 19)]

# ── Phase definitions ────────────────────────────────────────────────────────
PHASES = [
    {"name": "Phase 1 · 需求解析",     "nodes": ["n01", "n02", "n03"], "color": "#3b82f6"},
    {"name": "Phase 2 · 结构分解",     "nodes": ["n04", "n05", "n06", "n07", "n08"], "color": "#06b6d4"},
    {"name": "Phase 3 · 验证规划",     "nodes": ["n09", "n10"], "color": "#8b5cf6"},
    {"name": "Phase 4 · 成本测算",     "nodes": ["n11", "n12", "n13"], "color": "#10b981"},
    {"name": "Phase 5 · 项目规划",     "nodes": ["n14", "n15"], "color": "#ec4899"},
    {"name": "Phase 6 · 报价输出",     "nodes": ["n16", "n17", "n18"], "color": "#f59e0b"},
]

_NODE_PHASE = {}
for ph in PHASES:
    for nid in ph["nodes"]:
        _NODE_PHASE[nid] = ph["color"]

# ── Fixed layout: (x, y, w, h) for each node ────────────────────────────────
NODE_LAYOUT = {
    # Row 1 — requirements  (y=40)
    "n01": (40,  40, 190, 80),
    "n02": (280, 40, 190, 80),
    "n03": (520, 40, 190, 80),
    # Row 2 — decomposition (y=200)
    "n04": (40,  200, 190, 80),
    "n05": (280, 200, 190, 80),
    "n06": (520, 200, 190, 80),
    "n07": (760, 200, 190, 80),
    "n08": (1000,200, 210, 80),
    # Row 3 — validation + cost (y=380)
    "n09": (760, 380, 190, 80),
    "n10": (520, 380, 190, 80),
    "n11": (40,  380, 200, 90),
    "n12": (280, 380, 200, 90),
    "n13": (520, 540, 200, 80),
    # Row 4 — planning  (y=540)
    "n14": (760, 540, 200, 80),
    "n15": (1000,540, 210, 80),
    # Row 5 — quotation  (y=700)
    "n16": (40,  700, 220, 100),
    "n17": (1000,700, 220, 100),
    "n18": (500, 700, 260, 110),
}

# cost bar segment config
COST_SEGMENTS = [
    {"key": "material",    "label": "材料", "gradient": ("0d9488", "0f766e")},
    {"key": "conversion",  "label": "加工", "gradient": ("3b82f6", "2563eb")},
    {"key": "logistics",   "label": "物流", "gradient": ("8b5cf6", "7c3aed")},
    {"key": "quality",     "label": "质量", "gradient": ("ec4899", "db2777")},
    {"key": "overhead",    "label": "管理", "gradient": ("f59e0b", "d97706")},
    {"key": "profit",      "label": "利润", "gradient": ("ef4444", "dc2626")},
]


class DataflowDiagram:
    """Generate a single-file HTML dataflow diagram for an APQP-OS project."""

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.store = ArtifactStore(project_path)
        self.network = self._load_network()
        self.artifacts: dict[str, dict | None] = {}
        self.done_nodes: set[str] = set()

    # ── Data loading ─────────────────────────────────────────────────────

    def _load_network(self) -> dict:
        net_path = Path(__file__).resolve().parent.parent / "references" / "network.json"
        return json.loads(net_path.read_text())

    def _load_artifacts(self):
        self.done_nodes = self.store.list_done()
        for nid in ALL_NODES:
            self.artifacts[nid] = self.store.read(nid)

    def _is_done(self, nid: str) -> bool:
        return nid in self.done_nodes

    # ── Node summary extraction ──────────────────────────────────────────

    def _node_summary(self, nid: str) -> list[str]:
        """Return 2-3 short display lines for a node."""
        art = self.artifacts.get(nid)
        if not art or art.get("status") == "pending":
            return ["\u2014"]
        p = art.get("payload", {})
        try:
            return getattr(self, f"_sum_{nid}")(p)
        except Exception:
            return ["\u2014"]

    def _sum_n01(self, p):
        si = p.get("source_index", {})
        cnt = len(si) if isinstance(si, dict) else (len(si) if isinstance(si, list) else 0)
        pr = p.get("performance_requirements", [])
        req_cnt = len(pr) if isinstance(pr, list) else 0
        geo = p.get("geometry", {})
        od = geo.get("feed_line_od_mm", "")
        iid = geo.get("feed_line_id_mm", "")
        spec = f"{od}\u00d7{iid}mm" if od and iid else ""
        lines = [f"{cnt} 份文件 \u2192 {req_cnt} 项需求"]
        if spec:
            wp = p.get("working_pressure_bar", "")
            lines.append(f"\u7ba1\u5f84 {spec}" + (f" \u00b7 {wp}bar" if wp else ""))
        return lines

    def _sum_n02(self, p):
        cats = p.get("categories", [])
        rc = p.get("review_required_count", 0)
        lines = [f"{len(cats)} \u7c7b DRG \u6307\u6807"]
        if rc:
            lines.append(f"{rc} \u9879\u9700\u5ba1\u67e5")
        return lines

    def _sum_n03(self, p):
        comps = p.get("components", [])
        has3d = p.get("has_3d_model", False)
        pct = p.get("completeness_pct", 0)
        lines = [f"{len(comps)} \u4e2a\u7ec4\u4ef6"]
        lines.append(f"3D: {'YES' if has3d else 'NO'} \u00b7 {pct}%")
        return lines

    def _sum_n04(self, p):
        items = p.get("bom_items") or p.get("bom") or p.get("items") or []
        mc = p.get("make_count", 0)
        bc = p.get("buy_count", 0)
        lines = [f"{len(items)} \u9879 BOM"]
        lines.append(f"{mc} make \u00b7 {bc} buy")
        return lines

    def _sum_n05(self, p):
        mats = p.get("materials") or p.get("component_materials") or p.get("selections") or []
        lines = [f"{len(mats)} \u79cd\u6750\u6599"]
        return lines

    def _sum_n06(self, p):
        gw = p.get("total_assembly_gross_weight_g") or p.get("total_gross_weight_g")
        ws = p.get("weight_summary", {})
        if not gw and isinstance(ws, dict):
            gw = ws.get("total_gross_weight_g")
        lines = []
        if gw:
            lines.append(f"\u6bdb\u91cd {gw}g")
        nw = p.get("total_assembly_net_weight_g")
        if nw:
            lines.append(f"\u51c0\u91cd {nw}g")
        return lines or ["\u2014"]

    def _sum_n07(self, p):
        fms = p.get("fmea_items") or p.get("failure_modes") or []
        hrpn = p.get("high_rpn_count", 0)
        lines = [f"{len(fms)} \u5931\u6548\u6a21\u5f0f"]
        if hrpn:
            lines.append(f"\u9ad8RPN {hrpn} \u9879")
        return lines

    def _sum_n08(self, p):
        ops = p.get("operations") or p.get("process_steps") or []
        inv = p.get("total_investment_eur")
        lines = [f"{len(ops)} \u9053\u5de5\u5e8f"]
        if inv:
            lines.append(f"\u6295\u8d44 \u20ac{inv/10000:.0f}\u4e07" if inv >= 10000 else f"\u6295\u8d44 \u20ac{inv:.0f}")
        return lines

    def _sum_n09(self, p):
        tests = p.get("test_items") or p.get("dvpr_items") or p.get("tests") or []
        lines = [f"{len(tests)} \u9879\u6d4b\u8bd5"]
        return lines

    def _sum_n10(self, p):
        steps = p.get("pfd_steps") or p.get("process_flow") or p.get("process_steps") or []
        lines = [f"{len(steps)} \u6b65\u6d41\u7a0b"]
        return lines

    def _sum_n11(self, p):
        total = p.get("total_material_cost_eur") or p.get("total")
        mc = p.get("make_material_cost_eur")
        bc = p.get("buy_material_cost_eur")
        lines = []
        if total is not None:
            lines.append(f"\u20ac{total:.2f} /\u4ef6")
        if mc is not None and bc is not None:
            lines.append(f"make \u20ac{mc:.2f} + buy \u20ac{bc:.2f}")
        return lines or ["\u2014"]

    def _sum_n12(self, p):
        s = p.get("summary", {})
        total = s.get("total_conversion_cost_eur") or p.get("total_conversion_cost_eur")
        lines = []
        if total is not None:
            lines.append(f"\u20ac{total:.2f} /\u4ef6")
        return lines or ["\u2014"]

    def _sum_n13(self, p):
        cap = p.get("line_capacity_per_year") or p.get("annual_capacity") or p.get("annual_capacity_at_tact")
        util = p.get("utilization_pct")
        lines = []
        if cap:
            lines.append(f"\u4ea7\u80fd {cap:,}/\u5e74" if isinstance(cap, (int, float)) else f"\u4ea7\u80fd {cap}")
        if util:
            lines.append(f"\u5229\u7528\u7387 {util}%")
        return lines or ["\u2014"]

    def _sum_n14(self, p):
        ms = p.get("milestones") or []
        lines = [f"{len(ms)} \u4e2a\u91cc\u7a0b\u7891"]
        return lines

    def _sum_n15(self, p):
        total = p.get("edd_total_eur") or p.get("total_edd_eur")
        lines = []
        if total is not None:
            if total >= 10000:
                lines.append(f"\u20ac{total/10000:.1f}\u4e07")
            else:
                lines.append(f"\u20ac{total:.0f}")
        return lines or ["\u2014"]

    def _sum_n16(self, p):
        total = p.get("total_rc_eur")
        bd = p.get("cost_breakdown_pct", {})
        lines = []
        if total is not None:
            lines.append(f"\u20ac{total:.2f} /\u4ef6")
        mat_pct = bd.get("material")
        conv_pct = bd.get("conversion")
        if mat_pct is not None:
            lines.append(f"\u6750\u6599{mat_pct:.0f}% \u52a0\u5de5{conv_pct:.0f}%" if conv_pct else f"\u6750\u6599{mat_pct:.0f}%")
        return lines or ["\u2014"]

    def _sum_n17(self, p):
        total = p.get("total_nrc_eur")
        ap = p.get("amortization_plan", {})
        npp = ap.get("nrc_per_piece_eur")
        lines = []
        if total is not None:
            if total >= 10000:
                lines.append(f"\u20ac{total/10000:.1f}\u4e07")
            else:
                lines.append(f"\u20ac{total:.0f}")
        if npp is not None:
            lines.append(f"\u5206\u644a \u20ac{npp:.2f}/\u4ef6")
        return lines or ["\u2014"]

    def _sum_n18(self, p):
        qs = p.get("quotation_summary", {})
        up = qs.get("unit_price_eur")
        rev = qs.get("annual_revenue_eur")
        lines = []
        if up is not None:
            lines.append(f"\u20ac{up:.2f} /\u4ef6")
        if rev is not None:
            lines.append(f"\u5e74\u6536\u5165 \u20ac{rev/10000:.0f}\u4e07")
        return lines or ["\u2014"]

    # ── Header data extraction ───────────────────────────────────────────

    def _header_data(self) -> dict:
        n01 = self.artifacts.get("n01")
        n16 = self.artifacts.get("n16")
        n17 = self.artifacts.get("n17")
        n18 = self.artifacts.get("n18")
        p01 = n01.get("payload", {}) if n01 else {}
        p16 = n16.get("payload", {}) if n16 else {}
        p17 = n17.get("payload", {}) if n17 else {}
        p18 = n18.get("payload", {}) if n18 else {}

        qs = p18.get("quotation_summary", {})
        customer = qs.get("customer") or p01.get("oem", "")
        part_name = qs.get("part_name") or p01.get("part_name", "")
        program = qs.get("program") or p01.get("program", "")
        project = p01.get("part_number") or self.project_path.name

        rc = p16.get("total_rc_eur")
        nrc = p17.get("total_nrc_eur")

        rc_str = f"\u20ac{rc:.2f}" if rc is not None else "\u2014"
        if nrc is not None:
            nrc_str = f"\u20ac{nrc/10000:.1f}\u4e07" if nrc >= 10000 else f"\u20ac{nrc:.0f}"
        else:
            nrc_str = "\u2014"

        done_count = len(self.done_nodes)
        total_count = 18
        return {
            "customer": customer,
            "part_name": part_name,
            "program": program,
            "project": project,
            "rc_str": rc_str,
            "nrc_str": nrc_str,
            "done_count": done_count,
            "total_count": total_count,
        }

    # ── SVG rendering helpers ────────────────────────────────────────────

    def _gradient_defs(self) -> str:
        """SVG gradient definitions for each phase color."""
        defs = []
        seen = set()
        for ph in PHASES:
            c = ph["color"]
            if c in seen:
                continue
            seen.add(c)
            gid = f"grad-{c[1:]}"
            # Darken color for gradient
            r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
            dark = f"#{max(r//3,10):02x}{max(g//3,10):02x}{max(b//3,10):02x}"
            darker = f"#{max(r//5,8):02x}{max(g//5,8):02x}{max(b//5,8):02x}"
            defs.append(
                f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
                f'<stop offset="0%" stop-color="{dark}"/>'
                f'<stop offset="100%" stop-color="{darker}"/>'
                f'</linearGradient>'
            )
        # pending gradient
        defs.append(
            '<linearGradient id="grad-pending" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0%" stop-color="#1a1f2e"/>'
            '<stop offset="100%" stop-color="#12151f"/>'
            '</linearGradient>'
        )
        # arrow markers
        for ph in PHASES:
            c = ph["color"]
            mid = f"arrow-{c[1:]}"
            if mid not in [d.split('"')[1] for d in defs if 'marker' in d]:
                defs.append(
                    f'<marker id="{mid}" viewBox="0 0 10 8" refX="9" refY="4" '
                    f'markerWidth="8" markerHeight="6" orient="auto-start-reverse">'
                    f'<path d="M 0 0 L 10 4 L 0 8 z" fill="{c}" opacity="0.6"/>'
                    f'</marker>'
                )
        defs.append(
            '<marker id="arrow-grey" viewBox="0 0 10 8" refX="9" refY="4" '
            'markerWidth="8" markerHeight="6" orient="auto-start-reverse">'
            '<path d="M 0 0 L 10 4 L 0 8 z" fill="#4a5568" opacity="0.4"/>'
            '</marker>'
        )
        # glow filter
        defs.append(
            '<filter id="glow"><feGaussianBlur stdDeviation="3" result="blur"/>'
            '<feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        )
        return "\n      ".join(defs)

    def _render_node_svg(self, nid: str) -> str:
        x, y, w, h = NODE_LAYOUT[nid]
        done = self._is_done(nid)
        color = _NODE_PHASE[nid]
        gid = f"grad-{color[1:]}" if done else "grad-pending"
        stroke = color if done else "#4a5568"
        stroke_dash = "" if done else ' stroke-dasharray="6,4"'
        opacity = "" if done else ' opacity="0.55"'
        summary = self._node_summary(nid)
        name = NODE_NAMES[nid]

        lines = [f'<g class="node-group" data-node="{nid}"{opacity}>']
        lines.append(f'  <rect class="node-rect" x="{x}" y="{y}" width="{w}" height="{h}" '
                     f'fill="url(#{gid})" stroke="{stroke}"{stroke_dash}/>')

        # Glow animation for n16/n17/n18
        if nid in ("n16", "n17", "n18") and done:
            lines.append(
                f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" ry="10" '
                f'fill="none" stroke="{color}" stroke-width="2" opacity="0.3">'
                f'<animate attributeName="opacity" values="0.3;0.6;0.3" dur="3s" repeatCount="indefinite"/>'
                f'</rect>'
            )

        text_x = x + 16
        ty = y + 20
        fill_id = color if done else "#4a5568"
        fill_title = "#e2e8f0" if done else "#64748b"
        fill_detail = "#94a3b8" if done else "#475569"
        fill_value = color if done else "#475569"

        lines.append(f'  <text class="node-id" x="{text_x}" y="{ty}" fill="{fill_id}">{nid.upper()}</text>')
        ty += 18
        lines.append(f'  <text class="node-title" x="{text_x}" y="{ty}" fill="{fill_title}">'
                     f'{html_mod.escape(name)}</text>')

        for i, s in enumerate(summary[:3]):
            ty += 16
            cls = "node-value" if i == 0 and done else "node-detail"
            fill = fill_value if i == 0 and done else fill_detail
            # Larger font for key cost nodes
            style = ""
            if nid in ("n16", "n17", "n18") and i == 0 and done:
                style = ' style="font-size:14px;font-weight:700"'
            lines.append(f'  <text class="{cls}" x="{text_x}" y="{ty}" fill="{fill}"{style}>'
                         f'{html_mod.escape(s)}</text>')
        lines.append('</g>')
        return "\n    ".join(lines)

    def _edge_color(self, from_nid: str) -> str:
        return _NODE_PHASE.get(from_nid, "#3b82f6")

    def _bezier_path(self, from_nid: str, to_nid: str) -> str:
        """Compute a cubic bezier SVG path between two nodes."""
        fx, fy, fw, fh = NODE_LAYOUT[from_nid]
        tx, ty, tw, th = NODE_LAYOUT[to_nid]

        # Source point: bottom center or right center
        # Target point: top center or left center
        fcx, fcy = fx + fw / 2, fy + fh      # bottom center
        tcx, tcy = tx + tw / 2, ty            # top center

        # If nodes are on the same row (similar y), use right→left
        if abs(fy - ty) < 40:
            fcx, fcy = fx + fw, fy + fh / 2   # right center
            tcx, tcy = tx, ty + th / 2          # left center
            dx = abs(tcx - fcx) * 0.4
            return f"M {fcx:.0f} {fcy:.0f} C {fcx+dx:.0f} {fcy:.0f} {tcx-dx:.0f} {tcy:.0f} {tcx:.0f} {tcy:.0f}"

        # Vertical/diagonal: bottom→top
        dy = abs(tcy - fcy) * 0.5
        # Shift source x toward target to avoid overlaps
        if abs(fcx - tcx) > 200:
            # Use bottom-right or bottom-left exit
            if tcx > fcx:
                fcx = fx + fw * 0.75
            else:
                fcx = fx + fw * 0.25
        return f"M {fcx:.0f} {fcy:.0f} C {fcx:.0f} {fcy+dy:.0f} {tcx:.0f} {tcy-dy:.0f} {tcx:.0f} {tcy:.0f}"

    def _render_edges_svg(self) -> str:
        edges = self.network.get("edges", [])
        path_lines = []
        particle_lines = []
        idx = 0
        for e in edges:
            if e.get("type") == "feedback":
                continue
            fn, tn = e["from"], e["to"]
            both_done = self._is_done(fn) and self._is_done(tn)
            color = self._edge_color(fn) if both_done else "#4a5568"
            dash = "" if both_done else ' stroke-dasharray="6,4"'
            opacity = "0.6" if both_done else "0.25"
            marker = f"arrow-{color[1:]}" if both_done else "arrow-grey"
            d = self._bezier_path(fn, tn)

            # Glow path
            if both_done:
                path_lines.append(
                    f'<path class="flow-path-glow" d="{d}" stroke="{color}" opacity="0.1"/>'
                )
            path_lines.append(
                f'<path class="flow-path" d="{d}" stroke="{color}" opacity="{opacity}"{dash} '
                f'marker-end="url(#{marker})"/>'
            )
            # Animated particle for done edges
            if both_done:
                dur = max(2.0, min(4.0, len(d) / 100))
                begin = f"{(idx * 0.4) % 5:.1f}s"
                particle_lines.append(
                    f'<circle class="flow-particle" fill="{color}" filter="url(#glow)">'
                    f'<animateMotion dur="{dur:.1f}s" repeatCount="indefinite" path="{d}" begin="{begin}"/>'
                    f'</circle>'
                )
            idx += 1
        return "\n      ".join(path_lines + particle_lines)

    def _render_phase_labels(self) -> str:
        """Render phase label text at top of each phase region."""
        labels = []
        # Place labels based on first node in each phase
        for ph in PHASES:
            first = ph["nodes"][0]
            x, y, _, _ = NODE_LAYOUT[first]
            labels.append(
                f'<text x="{x}" y="{y - 12}" '
                f'font-family="\'Cascadia Code\', monospace" font-size="10" font-weight="600" '
                f'fill="{ph["color"]}" letter-spacing="2" opacity="0.6">'
                f'{html_mod.escape(ph["name"])}</text>'
            )
        return "\n      ".join(labels)

    def _render_separator_lines(self) -> str:
        """Decorative dashed lines between rows."""
        lines = []
        for ysep in [170, 350, 510, 670]:
            lines.append(
                f'<line x1="20" y1="{ysep}" x2="1380" y2="{ysep}" '
                f'stroke="#1e2d4a" stroke-width="1" stroke-dasharray="4,8" opacity="0.3"/>'
            )
        return "\n      ".join(lines)

    # ── Cost breakdown bar ───────────────────────────────────────────────

    def _cost_bar_html(self) -> str:
        n16 = self.artifacts.get("n16")
        p16 = n16.get("payload", {}) if n16 and n16.get("status") != "pending" else {}
        bd_pct = p16.get("cost_breakdown_pct", {})
        total_rc = p16.get("total_rc_eur")

        title_val = f"\u20ac{total_rc:.2f}" if total_rc else "\u2014"

        if not bd_pct:
            # Grey placeholder
            return (
                '<div class="cost-bar-section animate-in">\n'
                f'  <div class="cost-bar-title">\u5355\u4ef6\u6210\u672c\u7ed3\u6784 \u00b7 {title_val}</div>\n'
                '  <div class="cost-bar-subtitle">RC (Recurring Cost) \u5206\u9879\u6784\u6210</div>\n'
                '  <div class="cost-bar-wrapper">\n'
                '    <div class="cost-segment" style="flex:1;background:#2a2f3e;">\n'
                '      <span style="color:#64748b">\u7b49\u5f85 n16 \u5b8c\u6210...</span>\n'
                '    </div>\n'
                '  </div>\n'
                '</div>'
            )

        # Absolute values
        abs_map = {
            "material": p16.get("material_cost_eur", 0),
            "conversion": p16.get("conversion_cost_eur", 0),
            "logistics": p16.get("logistics_eur", 0),
            "quality": p16.get("quality_cost_eur", 0),
            "overhead": p16.get("overhead_eur", 0),
            "profit": p16.get("profit_eur", 0),
        }

        segments_html = []
        legend_html = []
        for seg in COST_SEGMENTS:
            pct = bd_pct.get(seg["key"], 0)
            val = abs_map.get(seg["key"], 0)
            g1, g2 = seg["gradient"]
            lbl = f'{seg["label"]} {pct:.0f}%' if pct >= 4 else (f'{pct:.0f}%' if pct >= 2 else '')
            segments_html.append(
                f'    <div class="cost-segment" style="flex:{pct};background:linear-gradient(135deg,#{g1},#{g2});" '
                f'title="{seg["label"]} \u20ac{val:.2f}">\n      <span>{lbl}</span>\n    </div>'
            )
            legend_html.append(
                f'    <div class="cost-legend-item">\n'
                f'      <div class="cost-legend-swatch" style="background:#{g1};"></div>\n'
                f'      <span>{seg["label"]}</span>\n'
                f'      <span class="cost-legend-value">\u20ac{val:.2f}</span>\n'
                f'    </div>'
            )

        return (
            '<div class="cost-bar-section animate-in">\n'
            f'  <div class="cost-bar-title">\u5355\u4ef6\u6210\u672c\u7ed3\u6784 \u00b7 {title_val}</div>\n'
            '  <div class="cost-bar-subtitle">RC (Recurring Cost) \u5206\u9879\u6784\u6210</div>\n'
            '  <div class="cost-bar-wrapper">\n' +
            "\n".join(segments_html) + '\n'
            '  </div>\n'
            '  <div class="cost-legend">\n' +
            "\n".join(legend_html) + '\n'
            '  </div>\n'
            '</div>'
        )

    # ── Reliability risk matrix ──────────────────────────────────────────

    def _reliability_html(self) -> str:
        # Collect S3/S4 assumptions from all artifacts
        cost_priority = {"n16": 0, "n17": 1, "n11": 2, "n12": 3, "n18": 4,
                         "n05": 5, "n06": 6, "n08": 7, "n13": 8, "n15": 9}
        items = []
        for nid in ALL_NODES:
            art = self.artifacts.get(nid)
            if not art:
                continue
            for a in art.get("assumptions", []):
                conf = a.get("confidence", "")
                if conf not in ("S3", "S4"):
                    continue
                prio = cost_priority.get(nid, 20)
                sev = 0 if conf == "S4" else 1
                items.append({
                    "node": nid,
                    "field": a.get("field", ""),
                    "value": a.get("value", ""),
                    "unit": a.get("unit", ""),
                    "confidence": conf,
                    "rationale": a.get("rationale", ""),
                    "sort_key": (sev, prio),
                })
        items.sort(key=lambda x: x["sort_key"])
        top = items[:8]

        if not top:
            return ""

        cards = []
        for it in top:
            s_cls = it["confidence"].lower()
            badge_label = f'{it["confidence"]} {"推测" if it["confidence"]=="S4" else "经验"}'
            val_display = it["value"]
            if it["unit"]:
                val_display += f' {it["unit"]}'
            cards.append(
                f'    <div class="reliability-card {s_cls}">\n'
                f'      <div class="rel-info">\n'
                f'        <div class="rel-name">{html_mod.escape(it["field"])}</div>\n'
                f'        <div class="rel-impact">{html_mod.escape(it["rationale"][:80])}</div>\n'
                f'      </div>\n'
                f'      <div class="rel-value">{html_mod.escape(val_display)}</div>\n'
                f'      <div class="rel-badge {s_cls}">{badge_label}</div>\n'
                f'    </div>'
            )

        return (
            '<div class="reliability-section animate-in">\n'
            '  <div class="reliability-title">\u6570\u636e\u53ef\u9760\u6027\u98ce\u9669\u77e9\u9635</div>\n'
            '  <div class="reliability-grid">\n' +
            "\n".join(cards) + '\n'
            '  </div>\n'
            '</div>'
        )

    # ── Legend ────────────────────────────────────────────────────────────

    def _legend_html(self) -> str:
        items = []
        for ph in PHASES:
            items.append(
                f'  <div class="legend-item">\n'
                f'    <div class="legend-swatch" style="background:{ph["color"]};"></div>\n'
                f'    <span>{html_mod.escape(ph["name"])}</span>\n'
                f'  </div>'
            )
        # Pending swatch
        items.append(
            '  <div class="legend-item">\n'
            '    <div class="legend-swatch" style="background:#4a5568;border-style:dashed;"></div>\n'
            '    <span>\u672a\u5b8c\u6210</span>\n'
            '  </div>'
        )
        return '<div class="legend animate-in">\n' + "\n".join(items) + '\n</div>'

    # ── Side drawer JS data ──────────────────────────────────────────────

    @staticmethod
    def _trim_payload(obj, depth=0, max_list=3, max_depth=2):
        """Recursively trim large arrays/dicts to keep JS payload small."""
        if depth > max_depth:
            if isinstance(obj, dict):
                return f"{{{len(obj)} fields}}"
            if isinstance(obj, list):
                return f"[{len(obj)} items]"
            if isinstance(obj, str) and len(obj) > 120:
                return obj[:120] + "..."
            return obj
        if isinstance(obj, dict):
            return {k: DataflowDiagram._trim_payload(v, depth + 1, max_list, max_depth)
                    for k, v in obj.items()}
        if isinstance(obj, list):
            if len(obj) > max_list:
                trimmed = [DataflowDiagram._trim_payload(v, depth + 1, max_list, max_depth)
                           for v in obj[:max_list]]
                trimmed.append(f"... +{len(obj) - max_list} more")
                return trimmed
            return [DataflowDiagram._trim_payload(v, depth + 1, max_list, max_depth)
                    for v in obj]
        if isinstance(obj, str) and len(obj) > 120:
            return obj[:120] + "..."
        return obj

    def _drawer_js_data(self) -> str:
        """Build JS objects for drawer: nodeDetails, upstreamMap, downstreamMap."""
        details = {}
        for nid in ALL_NODES:
            art = self.artifacts.get(nid)
            if not art:
                details[nid] = {
                    "status": "pending", "confidence_floor": None,
                    "payload": {}, "gaps": [], "assumptions": []
                }
                continue
            details[nid] = {
                "status": art.get("status", "pending"),
                "confidence_floor": art.get("confidence_floor"),
                "payload": self._trim_payload(art.get("payload", {}), max_list=2, max_depth=1),
                "gaps": art.get("gaps", []),
                "assumptions": art.get("assumptions", []),
            }

        upstream = {nid: [] for nid in ALL_NODES}
        downstream = {nid: [] for nid in ALL_NODES}
        for e in self.network.get("edges", []):
            if e.get("type") == "feedback":
                continue
            downstream.setdefault(e["from"], []).append(e["to"])
            upstream.setdefault(e["to"], []).append(e["from"])
        # Deduplicate
        for k in upstream:
            upstream[k] = sorted(set(upstream[k]))
        for k in downstream:
            downstream[k] = sorted(set(downstream[k]))

        node_names_js = json.dumps(NODE_NAMES, ensure_ascii=False)
        return (
            f"const nodeDetails = {json.dumps(details, ensure_ascii=False)};\n"
            f"const upstreamMap = {json.dumps(upstream, ensure_ascii=False)};\n"
            f"const downstreamMap = {json.dumps(downstream, ensure_ascii=False)};\n"
            f"const nodeNames = {node_names_js};\n"
        )

    # ── CSS ──────────────────────────────────────────────────────────────

    @staticmethod
    def _css() -> str:
        return """
  :root {
    --bg-primary: #0a0e17;
    --bg-secondary: #111827;
    --bg-card: #151d2e;
    --bg-card-hover: #1a2540;
    --border: #1e2d4a;
    --border-glow: #2563eb;
    --text-primary: #e2e8f0;
    --text-secondary: #94a3b8;
    --text-dim: #4a5568;
    --accent-blue: #3b82f6;
    --accent-cyan: #06b6d4;
    --accent-emerald: #10b981;
    --accent-amber: #f59e0b;
    --accent-red: #ef4444;
    --accent-purple: #8b5cf6;
    --accent-pink: #ec4899;
    --s3-color: #f59e0b;
    --s4-color: #ef4444;
    --glow-blue: 0 0 20px rgba(59, 130, 246, 0.3);
    --glow-cyan: 0 0 20px rgba(6, 182, 212, 0.3);
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: var(--bg-primary);
    color: var(--text-primary);
    font-family: -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    overflow-x: hidden;
    min-height: 100vh;
  }

  body::before {
    content: '';
    position: fixed; inset: 0;
    background-image:
      linear-gradient(rgba(59, 130, 246, 0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(59, 130, 246, 0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none; z-index: 0;
  }

  body::after {
    content: '';
    position: fixed; inset: 0;
    background: radial-gradient(ellipse at center, transparent 40%, rgba(0,0,0,0.6) 100%);
    pointer-events: none; z-index: 0;
  }

  .page-wrapper {
    position: relative; z-index: 1;
    max-width: 1600px; margin: 0 auto;
    padding: 40px 32px 80px;
  }

  /* Header */
  .header {
    margin-bottom: 48px;
    display: flex; align-items: flex-end;
    justify-content: space-between; gap: 24px; flex-wrap: wrap;
  }
  .header-left { display: flex; flex-direction: column; gap: 8px; }
  .header-badge {
    display: inline-flex; align-items: center; gap: 6px;
    font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', 'Menlo', 'Consolas', monospace;
    font-size: 11px; font-weight: 500; letter-spacing: 2px; text-transform: uppercase;
    color: var(--accent-cyan);
    background: rgba(6, 182, 212, 0.08);
    border: 1px solid rgba(6, 182, 212, 0.2);
    padding: 6px 14px; border-radius: 4px; width: fit-content;
  }
  .header-badge::before {
    content: ''; width: 6px; height: 6px;
    background: var(--accent-cyan); border-radius: 50%;
    animation: pulse-dot 2s ease-in-out infinite;
  }
  @keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

  .header h1 {
    font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', 'Menlo', 'Consolas', monospace;
    font-size: 28px; font-weight: 700; letter-spacing: -0.5px;
    background: linear-gradient(135deg, #e2e8f0, #94a3b8);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  }
  .header-subtitle {
    font-size: 14px; color: var(--text-secondary);
    max-width: 500px; line-height: 1.6;
  }
  .header-stats { display: flex; gap: 24px; }
  .stat-block {
    text-align: right; padding: 12px 20px;
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 8px; min-width: 140px;
  }
  .stat-value {
    font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', 'Menlo', 'Consolas', monospace;
    font-size: 22px; font-weight: 700; color: var(--accent-cyan);
  }
  .stat-label {
    font-size: 11px; color: var(--text-dim);
    text-transform: uppercase; letter-spacing: 1px; margin-top: 2px;
  }

  /* SVG Flow Container */
  .flow-container { position: relative; width: 100%; margin-bottom: 48px; }
  .flow-svg { width: 100%; height: auto; }

  /* Node styling */
  .node-group { cursor: pointer; transition: transform 0.2s ease; }
  .node-group:hover { transform: translateY(-2px); }
  .node-rect { rx: 10; ry: 10; stroke-width: 1.5; transition: all 0.3s ease; }
  .node-group:hover .node-rect { stroke-width: 2; filter: drop-shadow(0 0 12px var(--accent-blue)); }

  .node-id {
    font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', 'Menlo', 'Consolas', monospace;
    font-size: 10px; font-weight: 600; letter-spacing: 1px;
  }
  .node-title {
    font-family: -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    font-size: 13px; font-weight: 600;
  }
  .node-value {
    font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', 'Menlo', 'Consolas', monospace;
    font-size: 11px; font-weight: 500;
  }
  .node-detail {
    font-family: -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    font-size: 10px;
  }

  /* Flow connections */
  .flow-path { fill: none; stroke-width: 2; }
  .flow-path-glow { fill: none; stroke-width: 6; opacity: 0.1; }
  .flow-particle { r: 3; opacity: 0.9; }

  /* Reliability Section */
  .reliability-section { margin-top: 16px; }
  .reliability-title {
    font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', 'Menlo', 'Consolas', monospace;
    font-size: 16px; font-weight: 600; letter-spacing: -0.3px;
    color: var(--text-primary); margin-bottom: 20px;
    display: flex; align-items: center; gap: 10px;
  }
  .reliability-title::before {
    content: ''; width: 3px; height: 20px;
    background: var(--accent-amber); border-radius: 2px;
  }
  .reliability-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
    gap: 12px;
  }
  .reliability-card {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px 20px;
    display: grid; grid-template-columns: 1fr auto auto;
    align-items: center; gap: 16px;
    transition: all 0.25s ease; position: relative; overflow: hidden;
  }
  .reliability-card::before {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
  }
  .reliability-card.s3::before { background: var(--s3-color); }
  .reliability-card.s4::before { background: var(--s4-color); }
  .reliability-card:hover {
    background: var(--bg-card-hover);
    border-color: rgba(59, 130, 246, 0.3);
    transform: translateX(4px);
  }
  .rel-info { display: flex; flex-direction: column; gap: 2px; }
  .rel-name { font-weight: 600; font-size: 13px; }
  .rel-impact { font-size: 11px; color: var(--text-dim); line-height: 1.5; }
  .rel-value {
    font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', 'Menlo', 'Consolas', monospace;
    font-size: 13px; font-weight: 500; color: var(--text-secondary); white-space: nowrap;
  }
  .rel-badge {
    font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', 'Menlo', 'Consolas', monospace;
    font-size: 10px; font-weight: 600; letter-spacing: 1px;
    padding: 4px 10px; border-radius: 4px; white-space: nowrap;
  }
  .rel-badge.s3 {
    color: var(--s3-color); background: rgba(245, 158, 11, 0.1);
    border: 1px solid rgba(245, 158, 11, 0.25);
  }
  .rel-badge.s4 {
    color: var(--s4-color); background: rgba(239, 68, 68, 0.1);
    border: 1px solid rgba(239, 68, 68, 0.25);
  }

  /* Legend */
  .legend { display: flex; gap: 24px; margin-top: 32px; flex-wrap: wrap; }
  .legend-item { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-secondary); }
  .legend-swatch { width: 12px; height: 12px; border-radius: 3px; border: 1px solid rgba(255,255,255,0.1); }

  /* Cost breakdown bar */
  .cost-bar-section {
    margin-top: 48px; padding: 28px 32px;
    background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px;
  }
  .cost-bar-title {
    font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', 'Menlo', 'Consolas', monospace;
    font-size: 16px; font-weight: 600; margin-bottom: 6px;
    display: flex; align-items: center; gap: 10px;
  }
  .cost-bar-title::before {
    content: ''; width: 3px; height: 20px;
    background: var(--accent-emerald); border-radius: 2px;
  }
  .cost-bar-subtitle { font-size: 12px; color: var(--text-dim); margin-bottom: 20px; }
  .cost-bar-wrapper {
    display: flex; height: 44px; border-radius: 8px; overflow: hidden; margin-bottom: 16px;
  }
  .cost-segment {
    display: flex; align-items: center; justify-content: center;
    font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', 'Menlo', 'Consolas', monospace;
    font-size: 11px; font-weight: 600; color: rgba(255,255,255,0.9);
    position: relative; transition: all 0.3s ease; cursor: pointer; overflow: hidden;
  }
  .cost-segment:hover {
    filter: brightness(1.2);
    transform: scaleY(1.08);
  }
  .cost-legend { display: flex; gap: 20px; flex-wrap: wrap; margin-top: 24px; }
  .cost-legend-item { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-secondary); }
  .cost-legend-swatch { width: 10px; height: 10px; border-radius: 2px; }
  .cost-legend-value {
    font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', 'Menlo', 'Consolas', monospace;
    font-size: 12px; color: var(--text-primary); font-weight: 500;
  }

  /* Animations */
  @keyframes fadeInUp {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .animate-in { animation: fadeInUp 0.6s ease forwards; opacity: 0; }
  .animate-in:nth-child(1) { animation-delay: 0.05s; }
  .animate-in:nth-child(2) { animation-delay: 0.1s; }
  .animate-in:nth-child(3) { animation-delay: 0.15s; }
  .animate-in:nth-child(4) { animation-delay: 0.2s; }
  .animate-in:nth-child(5) { animation-delay: 0.25s; }
  .animate-in:nth-child(6) { animation-delay: 0.3s; }

  /* Footer */
  .footer {
    margin-top: 48px; padding-top: 24px; border-top: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: center;
    font-size: 11px; color: var(--text-dim);
    font-family: 'Cascadia Code', 'Fira Code', 'SF Mono', 'Menlo', 'Consolas', monospace;
  }

  /* Drawer */
  .drawer-overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.5);
    z-index: 200; opacity: 0; pointer-events: none;
    transition: opacity 0.3s ease;
  }
  .drawer-overlay.open { opacity: 1; pointer-events: auto; }

  .drawer {
    position: fixed; top: 0; right: -440px; width: 420px; height: 100vh;
    background: var(--bg-secondary); border-left: 1px solid var(--border);
    z-index: 210; overflow-y: auto; padding: 28px 24px;
    transition: right 0.3s ease;
  }
  .drawer.open { right: 0; }

  .drawer-close {
    position: absolute; top: 16px; right: 16px;
    background: none; border: 1px solid var(--border); border-radius: 6px;
    color: var(--text-secondary); cursor: pointer; width: 32px; height: 32px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; transition: all 0.2s;
  }
  .drawer-close:hover { background: var(--bg-card); color: var(--text-primary); }

  .drawer-header {
    margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid var(--border);
  }
  .drawer-node-id {
    font-family: 'Cascadia Code', monospace; font-size: 12px;
    color: var(--accent-cyan); background: rgba(6,182,212,0.1);
    padding: 3px 10px; border-radius: 4px; display: inline-block; margin-bottom: 6px;
  }
  .drawer-node-title { font-size: 18px; font-weight: 700; }
  .drawer-status {
    font-family: 'Cascadia Code', monospace; font-size: 11px; margin-top: 6px;
    color: var(--text-dim);
  }

  .drawer-section {
    margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid var(--border);
  }
  .drawer-section-title {
    font-family: 'Cascadia Code', monospace; font-size: 12px;
    color: var(--accent-blue); letter-spacing: 1px; text-transform: uppercase;
    margin-bottom: 10px;
  }

  .drawer-table { width: 100%; font-size: 12px; border-collapse: collapse; }
  .drawer-table td {
    padding: 4px 8px; border-bottom: 1px solid rgba(30,45,74,0.5);
    vertical-align: top;
  }
  .drawer-table td:first-child {
    color: var(--text-dim); white-space: nowrap; width: 40%;
    font-family: 'Cascadia Code', monospace; font-size: 11px;
  }
  .drawer-table td:last-child { color: var(--text-secondary); word-break: break-word; }

  .drawer-gap {
    padding: 8px 12px; margin-bottom: 6px; border-radius: 6px;
    font-size: 12px; line-height: 1.5;
  }
  .drawer-gap.error { background: rgba(239,68,68,0.08); border-left: 3px solid var(--accent-red); }
  .drawer-gap.warning { background: rgba(245,158,11,0.08); border-left: 3px solid var(--s3-color); }
  .drawer-gap.info { background: rgba(59,130,246,0.08); border-left: 3px solid var(--accent-blue); }

  .drawer-dep {
    display: inline-block; margin: 2px 4px 2px 0; padding: 3px 10px;
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 4px; font-family: 'Cascadia Code', monospace;
    font-size: 11px; color: var(--text-secondary); cursor: pointer;
  }
  .drawer-dep:hover { border-color: var(--accent-cyan); color: var(--accent-cyan); }

  @media (max-width: 900px) {
    .header { flex-direction: column; align-items: flex-start; }
    .header-stats { align-self: flex-start; }
    .reliability-grid { grid-template-columns: 1fr; }
    .page-wrapper { padding: 24px 16px 60px; }
    .drawer { width: 100%; right: -100%; }
  }
"""

    # ── JS for drawer ────────────────────────────────────────────────────

    def _drawer_js(self) -> str:
        return """
function openDrawer(nid) {
  const d = nodeDetails[nid];
  if (!d) return;
  const name = nodeNames[nid] || nid;

  document.getElementById('drawer-node-id').textContent = nid.toUpperCase();
  document.getElementById('drawer-node-title').textContent = name;

  const statusEl = document.getElementById('drawer-status');
  statusEl.textContent = 'Status: ' + d.status + (d.confidence_floor ? '  |  Confidence: ' + d.confidence_floor : '');

  // Payload table
  const payloadEl = document.getElementById('drawer-payload');
  payloadEl.innerHTML = renderTable(d.payload, 0);

  // Gaps
  const gapsEl = document.getElementById('drawer-gaps');
  if (d.gaps && d.gaps.length) {
    gapsEl.innerHTML = d.gaps.map(g => {
      const sev = g.severity || 'info';
      return '<div class="drawer-gap ' + sev + '"><strong>' + esc(g.rule || '') + '</strong> ' + esc(g.msg || '') + '</div>';
    }).join('');
  } else {
    gapsEl.innerHTML = '<span style="color:var(--text-dim);font-size:12px">No gaps</span>';
  }

  // Assumptions
  const assEl = document.getElementById('drawer-assumptions');
  if (d.assumptions && d.assumptions.length) {
    assEl.innerHTML = '<table class="drawer-table">' +
      d.assumptions.map(a =>
        '<tr><td>' + esc(a.id || '') + '</td><td>' + esc(a.field || '') + ' = ' +
        esc(String(a.value || '')) + ' ' + esc(a.unit || '') +
        ' <span style="color:var(--s3-color)">[' + esc(a.confidence || '') + ']</span></td></tr>'
      ).join('') + '</table>';
  } else {
    assEl.innerHTML = '<span style="color:var(--text-dim);font-size:12px">No assumptions</span>';
  }

  // Dependencies
  const upEl = document.getElementById('drawer-upstream');
  const dnEl = document.getElementById('drawer-downstream');
  upEl.innerHTML = (upstreamMap[nid] || []).map(n =>
    '<span class="drawer-dep" onclick="openDrawer(\\'' + n + '\\')">' + n.toUpperCase() + ' ' + (nodeNames[n]||'') + '</span>'
  ).join('') || '<span style="color:var(--text-dim);font-size:12px">None</span>';
  dnEl.innerHTML = (downstreamMap[nid] || []).map(n =>
    '<span class="drawer-dep" onclick="openDrawer(\\'' + n + '\\')">' + n.toUpperCase() + ' ' + (nodeNames[n]||'') + '</span>'
  ).join('') || '<span style="color:var(--text-dim);font-size:12px">None</span>';

  document.getElementById('drawer').classList.add('open');
  document.getElementById('drawer-overlay').classList.add('open');
}

function closeDrawer() {
  document.getElementById('drawer').classList.remove('open');
  document.getElementById('drawer-overlay').classList.remove('open');
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function renderTable(obj, depth) {
  if (obj === null || obj === undefined) return '<span style="color:var(--text-dim)">null</span>';
  if (typeof obj !== 'object') return esc(String(obj));
  if (Array.isArray(obj)) {
    if (obj.length === 0) return '<span style="color:var(--text-dim)">[]</span>';
    if (obj.length > 10) {
      return '<span style="color:var(--text-dim)">[' + obj.length + ' items]</span>';
    }
    if (typeof obj[0] !== 'object') return esc(obj.join(', '));
    return '<table class="drawer-table">' +
      obj.map((item, i) => '<tr><td>#' + (i+1) + '</td><td>' + renderTable(item, depth+1) + '</td></tr>').join('') +
      '</table>';
  }
  const keys = Object.keys(obj);
  if (keys.length === 0) return '<span style="color:var(--text-dim)">{}</span>';
  if (depth > 2) return '<span style="color:var(--text-dim)">{' + keys.length + ' fields}</span>';
  return '<table class="drawer-table">' +
    keys.map(k => '<tr><td>' + esc(k) + '</td><td>' + renderTable(obj[k], depth+1) + '</td></tr>').join('') +
    '</table>';
}

// Event binding
document.querySelectorAll('.node-group').forEach(node => {
  node.addEventListener('click', () => openDrawer(node.dataset.node));
});
document.getElementById('drawer-overlay').addEventListener('click', closeDrawer);
document.getElementById('drawer-close-btn').addEventListener('click', closeDrawer);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
"""

    # ── Main generate ────────────────────────────────────────────────────

    def generate(self) -> Path:
        """Generate the dataflow diagram HTML and return the output path."""
        self._load_artifacts()
        hd = self._header_data()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Build SVG content
        nodes_svg = "\n    ".join(self._render_node_svg(nid) for nid in ALL_NODES)
        edges_svg = self._render_edges_svg()
        phase_labels = self._render_phase_labels()
        separators = self._render_separator_lines()

        subtitle_parts = []
        if hd["customer"]:
            subtitle_parts.append(hd["customer"])
        if hd["part_name"]:
            subtitle_parts.append(hd["part_name"])
        subtitle = " \u00b7 ".join(subtitle_parts)

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APQP-OS \u6210\u672c\u6570\u636e\u6d41\u56fe</title>
<style>{self._css()}</style>
</head>
<body>

<div class="page-wrapper">

  <!-- Header -->
  <header class="header animate-in">
    <div class="header-left">
      <div class="header-badge">APQP-OS Data Flow</div>
      <h1>{html_mod.escape(subtitle or self.project_path.name)} \u00b7 \u6210\u672c\u6570\u636e\u6d41</h1>
      <p class="header-subtitle">\u4ece RFQ \u63d0\u53d6\u5230\u6700\u7ec8\u62a5\u4ef7\uff0c\u5b8c\u6574\u8ffd\u8e2a 18 \u8282\u70b9\u6570\u636e\u94fe\u8def\uff08\u5df2\u5b8c\u6210 {hd['done_count']}/{hd['total_count']}\uff09</p>
    </div>
    <div class="header-stats">
      <div class="stat-block">
        <div class="stat-value">{hd['rc_str']}</div>
        <div class="stat-label">RC \u5355\u4ef6\u6210\u672c</div>
      </div>
      <div class="stat-block">
        <div class="stat-value">{hd['nrc_str']}</div>
        <div class="stat-label">NRC \u5de5\u7a0b\u8d39\u7528</div>
      </div>
      <div class="stat-block">
        <div class="stat-value">{hd['done_count']}/18</div>
        <div class="stat-label">Progress</div>
      </div>
    </div>
  </header>

  <!-- Main Flow Diagram -->
  <div class="flow-container animate-in">
    <svg class="flow-svg" viewBox="0 0 1400 850" xmlns="http://www.w3.org/2000/svg">
      <defs>
      {self._gradient_defs()}
      </defs>

      <!-- Separators -->
      {separators}

      <!-- Phase labels -->
      {phase_labels}

      <!-- Edges -->
      {edges_svg}

      <!-- Nodes -->
      {nodes_svg}
    </svg>
  </div>

  <!-- Cost Breakdown -->
  {self._cost_bar_html()}

  <!-- Reliability Risk Matrix -->
  {self._reliability_html()}

  <!-- Legend -->
  {self._legend_html()}

  <!-- Footer -->
  <div class="footer animate-in">
    <span>APQP-OS \u00b7 {html_mod.escape(subtitle or self.project_path.name)}</span>
    <span>Generated {now}</span>
  </div>

</div>

<!-- Drawer overlay -->
<div class="drawer-overlay" id="drawer-overlay"></div>

<!-- Side drawer -->
<div class="drawer" id="drawer">
  <button class="drawer-close" id="drawer-close-btn">&times;</button>
  <div class="drawer-header">
    <div class="drawer-node-id" id="drawer-node-id"></div>
    <div class="drawer-node-title" id="drawer-node-title"></div>
    <div class="drawer-status" id="drawer-status"></div>
  </div>

  <div class="drawer-section">
    <div class="drawer-section-title">Payload</div>
    <div id="drawer-payload"></div>
  </div>

  <div class="drawer-section">
    <div class="drawer-section-title">Gaps</div>
    <div id="drawer-gaps"></div>
  </div>

  <div class="drawer-section">
    <div class="drawer-section-title">Assumptions</div>
    <div id="drawer-assumptions"></div>
  </div>

  <div class="drawer-section">
    <div class="drawer-section-title">Upstream</div>
    <div id="drawer-upstream"></div>
  </div>

  <div class="drawer-section">
    <div class="drawer-section-title">Downstream</div>
    <div id="drawer-downstream"></div>
  </div>
</div>

<script>
{self._drawer_js_data()}
{self._drawer_js()}
</script>

</body>
</html>"""

        out_path = self.store.artifacts_dir / "dataflow-diagram.html"
        out_path.write_text(html, encoding="utf-8")
        return out_path
