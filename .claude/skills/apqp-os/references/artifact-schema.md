# Artifact JSON Envelope

Every node produces exactly one `artifacts/nXX-output.json`:

```json
{
  "node": "n02",
  "project": "FC00SAA78530-KP1",
  "status": "ready",
  "produced_at": "2026-03-11T10:30:00Z",
  "confidence_floor": "S1",
  "gaps": [
    {
      "rule": "R-02-02",
      "msg": "annual_volume missing — using S4 default 50,000/yr",
      "severity": "warning",
      "assumption": "annual_volume=50000"
    }
  ],
  "assumptions": [
    {
      "id": "A-01",
      "field": "annual_volume",
      "value": "50000",
      "unit": "件/年",
      "confidence": "S4",
      "rationale": "客户文件未说明年产量，使用行业基准"
    }
  ],
  "payload": {}
}
```

## Status Values

| Value | Meaning |
|-------|---------|
| `pending` | Upstream deps not yet satisfied |
| `blocked` | Hard block (e.g. 3D file not received from customer) |
| `ready` | Usable — may have gaps, but downstream can proceed |
| `waiting_human` | Paused for human input |
| `done` | Consumed by downstream (optional marker) |

## Confidence Levels

| Level | Source | Rule |
|-------|--------|------|
| S1 | Client doc / regulation | Hard requirement — assumption not allowed |
| S2 | Physics / geometry | Derived by calculation |
| S3 | Company history | From internal JSON database |
| S4 | Industry baseline | Must document assumption explicitly |
| S5 | AI inference | Must flag as "待验证（AI推断）" |

`confidence_floor` = lowest level among all items in `payload`.

## source_index

n01 在 payload 中维护一个 `source_index`，为下游节点提供**回查原始文件的路径**。

n01 的结构化 JSON 只捕获可计算字段。图纸、走向示意图、条款上下文等无法 JSON 化的信息仍在原始文件里。下游节点 guide 应通过 `source_index` 的 key 明确引用，而不是硬编码路径。

```python
n01 = store.read('n01')
idx = n01['payload']['source_index']

# 示例：n07 DFMEA 需要看管路走向
routing_file = idx['routing_and_packaging']   # → CTS_fuel_line_requirements.pptx

# 示例：n02 DRG 需要查阅主规范原文
spec_file = idx['main_performance_spec']       # → PF.90197.pdf
```

**常用 key 及含义：**

| Key | 内容 |
|-----|------|
| `main_performance_spec` | 主性能规范 PDF |
| `qc_connector_spec` | QC 接头规范 PDF |
| `routing_and_packaging` | 管路走向 / 尺寸 / 安装约束（L2 PPTX）|
| `kpc_table` | 关键产品特性表（图片）|
| `material_compliance` | 材料受限物质要求 |
| `ssts_top_level` | 采购技术总要求（SSTS）|
| `tdr_deliverable_list` | 交付物清单（TDR）|
| `*_template` | 各交付物的客户模板文件 |

每个节点 guide 应在"Precondition"或"Step 1"中列出本节点需要读取的 `source_index` key。

---

## Deliverable Template Lifecycle

### Two-tier template lookup (priority order)

每个交付物使用模板时，按以下顺序查找：

```
1. 客户模板（优先）  → n01.deliverables_required[id].template_file  (非 null 时使用)
2. 公司内部模板（兜底）→ <APQPOS>/.claude/skills/apqp-os/assets/templates/<type>.xlsx
                         （节点开发时按需创建；暂无则节点从零生成文件）
```

内部模板在各节点 guide 开发时按需添加到 `assets/templates/`，未创建前由节点代码生成标准格式文件。

### n01 deliverable entry schema

```json
{
  "id": "D-02",
  "name": "Codesign cost breakdown",
  "phase": "SOURCING",
  "template_available": true,
  "template_file": "artifacts/_embedded/L2/TDR_ED&D_PBD_template.xlsx",
  "filled_by_node": "n12",
  "fill_instruction": "用公司成本数据填写 ED&D PBD，材料/工时/模具分解",
  "output_file": null
}
```

`output_file` 初始为 null，由 `filled_by_node` 执行后写入实际路径。

### Contract for the responsible node

```python
INTERNAL_TEMPLATE_DIR = Path('/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/assets/templates')

d = n01['payload']['deliverables_required']  # find entry by id

# 客户模板优先；内部模板兜底；都没有则从零生成
customer_tpl  = d.get('template_file')                          # n01 提取的客户模板
internal_tpl  = INTERNAL_TEMPLATE_DIR / f"{d['id']}-<name>.xlsx"
internal_tpl  = internal_tpl if internal_tpl.exists() else None

if customer_tpl:
    base = read_xlsx(customer_tpl)        # 使用客户格式
elif internal_tpl:
    base = read_xlsx(internal_tpl)        # 使用公司内部格式
else:
    base = generate_blank(d['name'])      # 从零生成标准格式

# fill and write
output_path = f"artifacts/{node_id}-{d['id']}-filled.xlsx"
write_xlsx(base, filled_data, output_path)

# write back to n01
d['output_file'] = output_path
store.write('n01', n01)
```

### Contract for n17 (quotation assembler)

- 读所有 `output_file != null` 的条目 → 打包进报价文件夹
- `output_file == null` 的条目 → 报 blocking gap，阻止报价提交

| 交付物 | 责任节点 | 客户模板（本项目）|
|--------|----------|-----------------|
| D-02 ED&D PBD | n12 | ✅ TDR_ED&D_PBD_template.xlsx |
| D-03 SDT | n14 | ✅ TDR_SDT_supplier_dev_team.xlsx |
| D-04 Component test list | n13 | ✅ TDR_component_test_list.xlsx |
| D-06 Exception list | n15 | ✅ TDR_exception_list_template.xlsx |
| D-07 RASI chart | n14 | ✅ TDR_RASI_chart.xlsx |
| D-14 DVPR plan | n13 | ✅ STLA-DVPR模板.xlsx |

---

## Assumptions Schema

每个 assumption 必须是结构化 dict，不能是简单字符串。`reporter.py` 依赖此格式生成报告。

```json
{
  "id": "A-01",
  "field": "annual_volume",
  "value": "50000",
  "unit": "件/年",
  "confidence": "S4",
  "rationale": "客户文件未说明年产量，使用行业基准"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | A-XX 编号，节点内唯一 |
| `field` | 是 | 被假设的 payload 字段名 |
| `value` | 是 | 假设值 |
| `unit` | 否 | 单位 |
| `confidence` | 是 | S3/S4/S5（S1/S2 不允许有假设） |
| `rationale` | 是 | 假设理由 |

---

## Gap Severity

| Severity | Effect |
|----------|--------|
| `error` | S1 field missing — downstream must note this explicitly |
| `warning` | Assumption used — downstream inherits and notes |
| `info` | Expected gap (e.g. no 3D model yet) — no action required |
