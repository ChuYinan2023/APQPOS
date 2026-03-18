"""APQP node execution report writer — generates human-readable markdown summary.

Report location: <project>/reports/nXX-report-YYYYMMDD-HHMMSS.md

Usage:
    from reporter import NodeReport
    report = NodeReport('<project_path>', 'n01')
    report.write(artifact)          # generates report file
    report.print_summary(artifact)  # prints key lines to chat/console
"""
from datetime import datetime, timezone
from pathlib import Path

NODE_NAMES = {
    "n01": "Requirements Parser",
    "n02": "DRG 设计要求指南",
    "n03": "3D 数模解析",
    "n04": "BOM",
    "n05": "材料选型",
    "n06": "用量计算",
    "n07": "DFMEA",
    "n08": "工艺路线",
    "n09": "DVP&R 验证计划",
    "n10": "PFD + 控制计划",
    "n11": "物料成本",
    "n12": "转化成本",
    "n13": "生产能力物理载体",
    "n14": "项目计划",
    "n15": "ED&D 工程开发费",
    "n16": "RC 单件成本",
    "n17": "NRC 总开发投入",
    "n18": "报价",
}

SEVERITY_ICON = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}
STATUS_ICON = {"ready": "✅", "done": "✅", "waiting_human": "⏸", "error": "❌"}

# Which nodes become unblocked after each node completes
NEXT_NODES = {
    "n01": ["n02", "n09", "n14", "n18"],
    "n02": ["n03", "n07", "n09"],
    "n03": ["n04", "n05", "n06", "n07", "n08"],
    "n04": ["n05", "n06", "n10"],
    "n05": ["n11"],
    "n06": ["n11"],
    "n07": ["n09", "n08", "n02"],
    "n08": ["n10", "n11", "n12", "n13"],
    "n09": ["n15"],
    "n10": ["n13"],
    "n11": ["n16"],
    "n12": ["n16"],
    "n13": ["n17"],
    "n14": ["n15"],
    "n15": ["n17"],
    "n16": ["n18"],
    "n17": ["n18"],
}


class NodeReport:
    def __init__(self, project_path: str, node_id: str):
        self.node_id = node_id
        self.project_path = Path(project_path)
        self.report_dir = self.project_path / "reports"
        self.report_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.report_path = self.report_dir / f"{node_id}-report-{ts}.md"

    def write(self, artifact: dict, execution_summary: str = "") -> Path:
        """Generate and write the markdown report. Returns report path.

        Args:
            artifact: The node output artifact dict.
            execution_summary: Free-text markdown written by the AI describing what
                happened during execution — files read, problems encountered, how they
                were resolved, any skill improvements made. This becomes the first
                section of the report. If omitted, the section is skipped.
        """
        lines = self._build(artifact, execution_summary)
        self.report_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"[REPORT] {self.report_path.name}")
        return self.report_path

    def print_summary(self, artifact: dict) -> None:
        """Print a short summary to console (for chat output)."""
        p = artifact.get("payload", {})
        status = artifact.get("status", "?")
        icon = STATUS_ICON.get(status, "·")
        gaps = artifact.get("gaps", [])
        errors = [g for g in gaps if g["severity"] == "error"]
        warnings = [g for g in gaps if g["severity"] == "warning"]

        print(f"\n{'='*60}")
        print(f"{icon}  {self.node_id.upper()} — {NODE_NAMES.get(self.node_id, '')}  [{status}]")
        print(f"    项目: {self.project_path.name}")
        if p.get("part_number"):
            print(f"    零件: {p['part_number']}  {p.get('part_name','')}")
        if p.get("oem"):
            print(f"    OEM:  {p['oem']}  平台: {p.get('platform','?')}  发动机: {p.get('engine','?')}")

        counts = []
        for label, field in [
            ("性能需求", "performance_requirements"),
            ("测试项", "test_matrix"),
            ("特殊特性", "special_characteristics"),
            ("引用标准", "referenced_standards"),
            ("交付物", "deliverables_required"),
        ]:
            v = p.get(field)
            if v is not None:
                counts.append(f"{label} {len(v)}")
        if counts:
            print(f"    提取: {' | '.join(counts)}")

        # n02 专属摘要
        if self.node_id == "n02":
            cats = p.get("categories", [])
            total = sum(len(c.get("indicators", [])) for c in cats)
            review_n = p.get("review_required_count", 0)
            if total:
                print(f"    DRG 指标: {total} 条 ({len(cats)} 类) | 待审阅: {review_n}")

        # n03 专属摘要
        if self.node_id == "n03":
            comps = p.get("components", [])
            intf = p.get("assembly_interfaces", [])
            pct = p.get("completeness_pct", 0)
            has_3d = p.get("has_3d_model", False)
            model_flag = "✓ 有" if has_3d else "⚠️ fallback（无 3D 模型）"
            print(f"    组件: {len(comps)} | 接口: {len(intf)} | 完整度: {pct}% | 3D 模型: {model_flag}")

        if errors:
            print(f"    ❌ 错误缺口 {len(errors)}: {', '.join(g['rule'] for g in errors)}")
        if warnings:
            print(f"    ⚠️  警告缺口 {len(warnings)}: {', '.join(g['rule'] for g in warnings)}")

        conf = artifact.get("confidence_floor", "?")
        print(f"    置信度底线: {conf}")
        print(f"    报告: reports/{self.report_path.name}")
        print(f"{'='*60}\n")

    # ------------------------------------------------------------------ #
    #  Private builders                                                    #
    # ------------------------------------------------------------------ #

    def _build(self, artifact: dict, execution_summary: str = "") -> list[str]:
        p = artifact.get("payload", {})
        gaps = artifact.get("gaps", [])
        assumptions = artifact.get("assumptions", [])
        status = artifact.get("status", "?")
        status_icon = STATUS_ICON.get(status, "·")

        L = []

        # ── Header ──────────────────────────────────────────────────────
        node_name = NODE_NAMES.get(self.node_id, self.node_id)
        L += [
            f"# {self.node_id.upper()} 执行报告 — {node_name}",
            "",
            f"**项目**: {self.project_path.name}  ",
            f"**生成时间**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
            f"**状态**: {status_icon} {status}  ",
            f"**置信度底线**: {artifact.get('confidence_floor', '?')}  ",
            "",
            "---",
            "",
        ]

        # ── Execution summary (AI-written narrative) ─────────────────────
        if execution_summary and execution_summary.strip():
            L += [
                "## 执行过程总结",
                "",
                execution_summary.strip(),
                "",
                "---",
                "",
            ]

        # ── Node-specific sections ───────────────────────────────────────
        if self.node_id == "n01":
            L += self._n01_sections(p, artifact)
        elif self.node_id == "n02":
            L += self._n02_sections(p, artifact)
        elif self.node_id == "n03":
            L += self._n03_sections(p, artifact)
        else:
            L += self._generic_payload_section(p)

        # ── Gaps ────────────────────────────────────────────────────────
        if gaps:
            L += ["", "## 缺口（Gaps）", ""]
            errors = [g for g in gaps if g["severity"] == "error"]
            warnings = [g for g in gaps if g["severity"] == "warning"]
            infos = [g for g in gaps if g["severity"] == "info"]
            for group, label in [(errors, "错误"), (warnings, "警告"), (infos, "信息")]:
                if group:
                    L.append(f"### {SEVERITY_ICON.get(group[0]['severity'], '·')} {label}")
                    L.append("")
                    for g in group:
                        line = f"- **`{g['rule']}`** {g['msg']}"
                        if g.get("assumption"):
                            line += f"  \n  → 假设: *{g['assumption']}*"
                        L.append(line)
                    L.append("")
        else:
            L += ["", "## 缺口", "", "> 无缺口。", ""]

        # ── Assumptions ─────────────────────────────────────────────────
        if assumptions:
            L += ["", "## 假设（Assumptions）", ""]
            L.append("| ID | 字段 | 值 | 置信度 | 理由 |")
            L.append("|----|----|----|----|---|")
            for a in assumptions:
                val = f"{a.get('value', '')} {a.get('unit', '')}".strip()
                L.append(
                    f"| {a.get('id','')} | {a.get('field','')} | {val} "
                    f"| {a.get('confidence','')} | {a.get('rationale','')} |"
                )
            L.append("")

        # ── Next steps ──────────────────────────────────────────────────
        next_nodes = NEXT_NODES.get(self.node_id, [])
        if next_nodes:
            L += ["", "## 下一步", ""]
            for n in next_nodes:
                L.append(f"- **{n}** — {NODE_NAMES.get(n, n)}")
            # Highlight human nodes
            human = [n for n in next_nodes if n in ("n03", "n18")]
            if human:
                L.append("")
                L.append(f"> ⏸ **{', '.join(human)} 为 human 节点**，需要人工输入后才能继续。")
            L.append("")

        # ── Footer ──────────────────────────────────────────────────────
        L += [
            "---",
            "",
            f"**制品文件**: `artifacts/{self.node_id}-output.json`  ",
            f"**日志文件**: `logs/{self.node_id}-*.md`  ",
            f"**本报告**: `reports/{self.report_path.name}`  ",
        ]
        return L

    def _n01_sections(self, p: dict, artifact: dict) -> list[str]:
        L = []

        # Part overview
        L += ["## 零件概览", ""]
        rows = [
            ("OEM", p.get("oem", "")),
            ("零件号", p.get("part_number", "")),
            ("零件名", p.get("part_name", "")),
            ("平台 / 程序", p.get("platform", "")),
            ("发动机", p.get("engine", "")),
            ("工作压力", f"{p.get('working_pressure_bar', '')} bar" if p.get("working_pressure_bar") else ""),
            ("设计寿命", p.get("design_life", "")),
            ("年产量", p.get("annual_volume") or "⚠️ 未知"),
            ("SOP日期", p.get("sop_date") or "⚠️ 未知"),
        ]
        L.append("| 字段 | 值 |")
        L.append("|------|----|")
        for k, v in rows:
            if v:
                L.append(f"| {k} | {v} |")
        L.append("")

        # Geometry
        geo = p.get("geometry", {})
        if geo:
            L += ["## 几何参数", ""]
            L.append("| 参数 | 值 |")
            L.append("|------|----|")
            if geo.get("feed_line_od_mm"):
                L.append(f"| 进油管 OD×ID | Ø{geo['feed_line_od_mm']}×{geo['feed_line_id_mm']} mm |")
            if geo.get("return_line_od_mm"):
                L.append(f"| 回油管 OD×ID | Ø{geo['return_line_od_mm']}×{geo['return_line_id_mm']} mm |")
            hp = geo.get("engine_hp_port", {})
            if hp:
                L.append(f"| 发动机HP口 外径 | ~{hp.get('outer_diameter_mm','')} mm |")
                L.append(f"| 发动机HP口 内径 | ~{hp.get('inner_diameter_mm','')} mm |")
            ef = geo.get("end_form", {})
            if ef:
                L.append(f"| 端成形 OD | {ef.get('od_mm','')} mm |")
                L.append(f"| 端成形 ID | {ef.get('id_mm','')} mm |")
                L.append(f"| 端成形 长度 | {ef.get('length_mm','')} mm |")
            d = geo.get("damper", {})
            if d:
                L.append(f"| 减振器 外径 | Ø{d.get('outer_diameter_mm','')} mm |")
                L.append(f"| 减振器 宽度 | {d.get('width_mm_with_tolerance','')} mm |")
                L.append(f"| 减振器 供应商 | {d.get('supplier','')} |")
            L.append("")

        # Quick connector
        qc = p.get("quick_connector", {})
        if qc:
            L += ["## 快接头（Quick Connector）", ""]
            L.append("| 参数 | 值 |")
            L.append("|------|----|")
            if qc.get("fuel_filter_side_feed"):
                L.append(f"| 滤清器侧进油 | {qc['fuel_filter_side_feed']} |")
            if qc.get("fuel_filter_side_return"):
                L.append(f"| 滤清器侧回油 | {qc['fuel_filter_side_return']} |")
            if qc.get("engine_bay_side"):
                L.append(f"| 发动机舱侧 | {qc['engine_bay_side']} |")
            if qc.get("secondary_latch_rule"):
                L.append(f"| 二次锁规则 | {qc['secondary_latch_rule']} |")
            oc = qc.get("operating_conditions", {})
            if oc:
                L.append(f"| 工作压力上限 | {oc.get('pressure_max_bar','')} bar |")
                L.append(f"| 温度范围 | {oc.get('temp_continuous_c',[''])[0]}~{oc.get('temp_continuous_c',['',''])[1]} °C |")
                L.append(f"| 短期温度 | {oc.get('temp_short_term_c','')} °C / {oc.get('temp_short_term_duration_min','')} min |")
            mo = qc.get("o_ring_materials", {})
            if mo:
                L.append(f"| O型圈 燃油接触面 | {mo.get('fuel_contact','')} |")
                L.append(f"| O型圈 外侧 | {mo.get('external','')} |")
            fr = qc.get("functional_requirements", {})
            if fr:
                if fr.get("pull_apart_liquid_new_N_min"):
                    L.append(f"| 拉脱力（液态燃油，新品）| ≥{fr['pull_apart_liquid_new_N_min']} N |")
                if fr.get("burst_liquid_kPa_min"):
                    L.append(f"| 爆破压力（液态）| ≥{fr['burst_liquid_kPa_min']} kPa |")
                if fr.get("dynamic_impact_metallic_J_min"):
                    L.append(f"| 动态冲击（金属型）| ≥{fr['dynamic_impact_metallic_J_min']} J |")
                if fr.get("rocker_cycles_liquid"):
                    L.append(f"| 摇摆测试（液态）| {fr['rocker_cycles_liquid']:,} 次循环 |")
            L.append("")

        # Special characteristics
        sc_list = p.get("special_characteristics", [])
        if sc_list:
            sc = [x for x in sc_list if x.get("type") == "SC"]
            cc = [x for x in sc_list if x.get("type") == "CC"]
            L += ["## 特殊特性（KPC）", ""]
            L.append(f"共 **{len(sc_list)}** 项：CC × {len(cc)}，SC × {len(sc)}")
            L.append("")
            L.append("| 类型 | 参数 | 要求摘要 | 来源 |")
            L.append("|------|------|---------|------|")
            for x in sc_list:
                typ = x.get("type", "")
                sym = "⊗" if typ == "CC" else "△" if typ == "SC" else typ
                req = x.get("requirement", "")
                if len(req) > 50:
                    req = req[:47] + "..."
                src = x.get("source_doc", "")
                if len(src) > 30:
                    src = src[:27] + "..."
                L.append(f"| {sym} {typ} | {x.get('parameter','')} | {req} | {src} |")
            L.append("")

        # Performance requirements summary
        pr_list = p.get("performance_requirements", [])
        if pr_list:
            L += ["## 性能需求摘要", ""]
            L.append(f"共提取 **{len(pr_list)}** 条性能需求。")
            L.append("")
            L.append("| ID | 参数 | 值/要求 | 来源 |")
            L.append("|----|------|---------|------|")
            for pr in pr_list:
                val = pr.get("value", "")
                if len(val) > 40:
                    val = val[:37] + "..."
                L.append(
                    f"| {pr.get('id','')} | {pr.get('parameter','')} | {val} {pr.get('unit','')} "
                    f"| {pr.get('source_doc','')} {pr.get('source_section','')} |"
                )
            L.append("")

        # Test matrix summary
        tm_list = p.get("test_matrix", [])
        if tm_list:
            L += ["## 测试矩阵摘要", ""]
            L.append(f"共 **{len(tm_list)}** 个测试项。")
            L.append("")
            L.append("| 测试名称 | 阶段 | 样本量 | 可靠性目标 |")
            L.append("|---------|------|--------|----------|")
            for t in tm_list:
                L.append(
                    f"| {t.get('test_name','')} | {t.get('phase','')} "
                    f"| {t.get('sample_size','-')} | {t.get('reliability','-')} |"
                )
            L.append("")

        # Standards
        stds = p.get("referenced_standards", [])
        if stds:
            avail = [s for s in stds if s.get("available")]
            missing = [s for s in stds if not s.get("available")]
            L += ["## 引用标准", ""]
            L.append(f"共 **{len(stds)}** 个标准（**{len(avail)}** 个已有，**{len(missing)}** 个缺失）。")
            L.append("")
            if avail:
                L.append("**已有标准：**")
                for s in avail:
                    L.append(f"- ✅ `{s['standard_id']}` — {s.get('title','')}")
                L.append("")
            if missing:
                L.append("**缺失标准（需向客户索取）：**")
                ids = [f"`{s['standard_id']}`" for s in missing]
                # Group in rows of 5 for readability
                for i in range(0, len(ids), 5):
                    L.append("  " + "，".join(ids[i:i+5]))
                L.append("")

        # Deliverables
        deliv = p.get("deliverables_required", [])
        if deliv:
            with_tmpl = [d for d in deliv if d.get("template_available")]
            L += ["## 交付物清单", ""]
            L.append(f"共 **{len(deliv)}** 项交付物，其中 **{len(with_tmpl)}** 项有现成模板。")
            L.append("")
            L.append("| 交付物 | 阶段 | 模板 | 责任节点 |")
            L.append("|--------|------|------|---------|")
            for d in deliv:
                if d.get("template_available") and d.get("template_file"):
                    tmpl = f"✅ `{Path(d['template_file']).name}`"
                else:
                    tmpl = "—"
                responsible = d.get("filled_by_node", "")
                L.append(f"| {d['name']} | {d.get('phase','')} | {tmpl} | {responsible} |")
            L.append("")

        # Quality targets — generic traversal
        qt = p.get("quality_targets", {})
        if qt:
            L += ["## 质量目标", ""]
            L.append("| 指标 | 目标 |")
            L.append("|------|------|")
            for k, v in qt.items():
                if isinstance(v, dict):
                    # Nested dict (e.g. TESIS targets) — flatten to one row
                    summary = ", ".join(f"{sk}: {sv}" for sk, sv in v.items() if sv)
                    if len(summary) > 80:
                        summary = summary[:77] + "..."
                    L.append(f"| {k} | {summary} |")
                elif isinstance(v, bool):
                    L.append(f"| {k} | {'是' if v else '否'} |")
                elif v is not None:
                    L.append(f"| {k} | {v} |")
            L.append("")

        return L

    def _n02_sections(self, p: dict, artifact: dict) -> list[str]:
        L = []

        # ── 汇总 ────────────────────────────────────────────────────────
        version = p.get("drg_version", 1)
        review_n = p.get("review_required_count", 0)
        conflict_n = p.get("conflict_count", 0)
        cats = p.get("categories", [])
        total_indicators = sum(len(c.get("indicators", [])) for c in cats)

        L += [
            "## DRG 指标总览",
            "",
            "| 版本 | 总指标数 | 待审阅 | 冲突 | 分类数 |",
            "|------|---------|------|------|------|",
            f"| v{version} | {total_indicators} | {review_n} | {conflict_n} | {len(cats)} |",
            "",
        ]

        # ── 待审阅汇总（优先展示，方便工程师一次处理）──────────────────────
        review_items = p.get("review_items", [])
        if review_items:
            reason_label = {
                "requirement_descriptive": "描述性要求（无数值）",
                "conflict":               "来源冲突",
                "low_confidence":         "低置信度（AI 推断）",
            }
            L += ["## ⚠️ 待审阅条目", ""]
            L.append("| 指标 ID | 原因 | 说明 |")
            L.append("|---------|------|------|")
            for item in review_items:
                ind_id = item.get("id", item.get("indicator_id", ""))
                reason = item.get("reason", item.get("review_reason", ""))
                detail = item.get("detail", item.get("parameter", ""))
                label = reason_label.get(reason, reason)
                L.append(f"| `{ind_id}` | {label} | {detail} |")
            L.append("")

        # ── 分类指标详情 ─────────────────────────────────────────────────
        L += ["## DRG 指标明细", ""]
        for cat in cats:
            indicators = cat.get("indicators", [])
            if not indicators:
                continue
            L += [f"### {cat.get('id', '')} — {cat.get('name', '')}", ""]
            L.append("| ID | 参数 | 设计目标 | 量化 | 置信度 | 审阅 |")
            L.append("|----|------|---------|------|------|------|")
            for ind in indicators:
                quantified = "✓" if ind.get("quantified") else "—"
                review = "⚠️" if ind.get("needs_review") else "✓"
                conf = ind.get("confidence", "")
                target = ind.get("design_target", "")[:50]  # 截断避免表格过宽
                L.append(
                    f"| `{ind.get('id', '')}` | {ind.get('parameter','')} "
                    f"| {target} | {quantified} | {conf} | {review} |"
                )
            L.append("")

        # ── DFMEA 修正（如有）────────────────────────────────────────────
        dfmea_revised = []
        for cat in cats:
            for ind in cat.get("indicators", []):
                if ind.get("dfmea_correction"):
                    dfmea_revised.append(ind)
        if dfmea_revised:
            L += ["## DFMEA 反馈修正", ""]
            for ind in dfmea_revised:
                dc = ind["dfmea_correction"]
                L += [
                    f"**`{ind.get('id', '')}`** {ind.get('parameter','')}",
                    f"- Gap 来源: `{dc.get('gap_ref','')}`",
                    f"- 原目标: {dc.get('original_target','')}",
                    f"- 修订目标: {dc.get('revised_target','')}",
                    "",
                ]

        return L

    def _n03_sections(self, p: dict, artifact: dict) -> list[str]:
        L = []

        # ── 几何总览 ─────────────────────────────────────────────────────
        version = p.get("geometry_version", 1)
        has_3d = p.get("has_3d_model", False)
        completeness = p.get("completeness_pct", 0)
        components = p.get("components", [])
        interfaces = p.get("assembly_interfaces", [])
        model_str = "✅ 有" if has_3d else "⚠️ 无（fallback 模式）"

        L += [
            "## 几何模型总览",
            "",
            "| 版本 | 3D 模型 | 完整度 | 组件数 | 接口数 |",
            "|------|--------|------|------|------|",
            f"| v{version} | {model_str} | {completeness}% | {len(components)} | {len(interfaces)} |",
            "",
        ]

        # ── 待 3D 模型补充的缺口 ──────────────────────────────────────────
        missing = p.get("missing_from_3d", [])
        if missing:
            L += ["## ⚠️ 待 3D 模型补充", ""]
            for m in missing:
                L.append(f"- {m}")
            L.append("")

        # ── 组件清单 ─────────────────────────────────────────────────────
        if components:
            L += ["## 组件清单", ""]
            L.append("| ID | 名称 | 类型 | 数量 | 材料提示 | 已知尺寸 | 缺失尺寸 |")
            L.append("|----|------|------|------|---------|--------|--------|")
            for c in components:
                dim_count = len(c.get("dimensions", []))
                missing_count = len(c.get("missing_dimensions", []))
                missing_flag = f"⚠️ {missing_count}" if missing_count else "✓"
                mat = (c.get("material_hint") or "")[:30]
                L.append(
                    f"| `{c.get('id', '')}` | {c.get('name', '')} | {c.get('type', '')} "
                    f"| {c.get('quantity', 1)} | {mat} | {dim_count} | {missing_flag} |"
                )
            L.append("")

            # ── 组件尺寸明细 ──────────────────────────────────────────────
            if any(c.get("dimensions") for c in components):
                L += ["## 组件尺寸明细", ""]
            for c in components:
                dims = c.get("dimensions", [])
                if not dims:
                    continue
                L += [f"### {c.get('id', '')} — {c.get('name', '')}", ""]
                L.append("| 参数 | 标称 | 公差+ | 公差- | 单位 | Cpk | 置信度 | 审阅 |")
                L.append("|------|------|-------|-------|------|-----|------|------|")
                for d in dims:
                    review = "⚠️" if d.get("needs_review") else "✓"
                    cpk = d.get("cpk_target") or "—"
                    t_plus = d.get("tolerance_plus")
                    t_minus = d.get("tolerance_minus")
                    t_plus_str = f"+{t_plus}" if t_plus is not None else "—"
                    t_minus_str = f"-{t_minus}" if t_minus is not None else "—"
                    L.append(
                        f"| {d.get('parameter', '')} | {d.get('nominal', '')} "
                        f"| {t_plus_str} | {t_minus_str} | {d.get('unit', '')} "
                        f"| {cpk} | {d.get('confidence', '')} | {review} |"
                    )
                L.append("")

        # ── 装配接口 ─────────────────────────────────────────────────────
        if interfaces:
            L += ["## 装配接口", ""]
            L.append("| ID | 名称 | 类型 | 关联组件 | SC/CC | 审阅 |")
            L.append("|----|------|------|---------|------|------|")
            for intf in interfaces:
                review = "⚠️" if intf.get("needs_review") else "✓"
                comps_str = ", ".join(intf.get("components", []))
                sc_str = ("; ".join(intf.get("sc_cc_refs", [])))[:40] or "—"
                L.append(
                    f"| `{intf.get('id', '')}` | {intf.get('name', '')} | {intf.get('type', '')} "
                    f"| {comps_str} | {sc_str} | {review} |"
                )
            L.append("")

        return L

    def _generic_payload_section(self, p: dict) -> list[str]:
        """Fallback for nodes without a dedicated section builder."""
        if not p:
            return []
        L = ["## 输出摘要", ""]
        for k, v in p.items():
            if isinstance(v, (str, int, float)) and v:
                L.append(f"- **{k}**: {v}")
        L.append("")
        return L
