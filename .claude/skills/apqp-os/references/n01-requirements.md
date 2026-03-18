# NODE-01: Requirements Parser（需求解析）

**Purpose**: Parse all customer RFQ files → structured JSON with extracted engineering fields.
**Input**: `project.json` + files in `inputs/` (or project root if not yet moved)
**Output**: `artifacts/n01-output.json`
**Type**: auto (no human input required)

---

## Precondition Check

```python
import json, sys
from pathlib import Path

sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from logger import NodeLogger

p = Path('<project_path>')
assert (p / 'project.json').exists(), "project.json missing — run orchestrator.py init first"
# Files may be in inputs/ or project root
files = list((p / 'inputs').glob('*')) + [f for f in p.glob('*') if f.is_file() and f.suffix in ('.pdf','.xlsx','.docx','.pptx')]
files = [f for f in files if f.is_file()]
assert files, "No input files found"
print(f"✓ {len(files)} input file(s): {[f.name for f in files]}")

# Start logger — do this ONCE after precondition passes
log = NodeLogger('<project_path>', 'n01')
log.step("Precondition: input files found")
log.info(f"{len(files)} input file(s): {[f.name for f in files]}")
```

---

## Execution Steps

### Step 1: Recursive Embedded File Extraction

**This step is mandatory and must run before any content reading.**

Embedded files in Stellantis RFQ packages routinely contain critical specifications
(CTS PPTX with pipe dimensions, TDR with RASI/templates). Skipping L2+ extraction
causes major data gaps.

#### 1a. Scan and extract (Layer by Layer)

```python
import zipfile, olefile
from pathlib import Path

def extract_office_embeddings(src_path: Path, dest_dir: Path, prefix: str):
    """Extract all /embeddings/ entries from an Office ZIP file."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    try:
        with zipfile.ZipFile(src_path) as z:
            embeds = [f for f in z.namelist() if '/embeddings/' in f]
            for f in embeds:
                fname = Path(f).name
                out = dest_dir / f"{prefix}_{fname}"
                out.write_bytes(z.read(f))
                extracted.append(out)
    except Exception:
        pass
    return extracted

def extract_ole_bin(bin_path: Path, dest_dir: Path):
    """
    Extract recoverable content from OLE .bin files.
    Returns path to extracted file, or None if link-only.

    Lesson learned:
    - CONTENTS stream → usually PDF → extract
    - Ole10Native with no PDF/ZIP signature → link-only, discard
    - Ole10Native with PDF/ZIP signature → extract
    """
    try:
        ole = olefile.OleFileIO(str(bin_path))
        # Priority 1: CONTENTS (most reliable)
        if ole.exists('CONTENTS'):
            raw = ole.openstream('CONTENTS').read()
            idx = raw.find(b'%PDF')
            if idx >= 0:
                out = dest_dir / bin_path.stem.replace('.bin', '_extracted.pdf')
                out.write_bytes(raw[idx:])
                return out
        # Priority 2: Ole10Native
        if ole.exists('\x01Ole10Native'):
            raw = ole.openstream('\x01Ole10Native').read()
            if raw.find(b'%PDF') >= 0:
                idx = raw.find(b'%PDF')
                out = dest_dir / bin_path.stem.replace('.bin', '_extracted.pdf')
                out.write_bytes(raw[idx:])
                return out
            if raw.find(b'PK\x03\x04') >= 0:
                out = dest_dir / bin_path.stem.replace('.bin', '_extracted.zip')
                out.write_bytes(raw)
                return out
            # JPG image (e.g. Stellantis KPC table embedded as image)
            if raw.find(b'\xff\xd8\xff') >= 0:
                idx = raw.find(b'\xff\xd8\xff')
                jpg_data = raw[idx:]
                # Validate before writing: some OLE link objects embed a corrupt
                # thumbnail (header FF D8 FF FF) that Claude's Read tool cannot process.
                try:
                    from PIL import Image
                    import io as _io
                    Image.open(_io.BytesIO(jpg_data)).verify()
                    out = dest_dir / bin_path.stem.replace('.bin', '_extracted.jpg')
                    out.write_bytes(jpg_data)
                    return out
                except Exception:
                    # Corrupt/unreadable image → treat as link-only
                    return None
        # Link-only — discard
        return None
    except Exception:
        return None
```

> **Lesson learned (KP1 run):** Stellantis OLE link objects (`\x01Ole10Native`, type-byte `\x02`)
> embed a garbled thumbnail (`FF D8 FF FF …`) referencing an external TIF on the author's PC.
> PIL validation catches this immediately; the Read tool would crash with
> `API Error 400 – Could not process image` if you pass the file unchecked.

#### 1b. Execute extraction (up to 3 layers)

```
Layer 0 (inputs/):  *.xlsx, *.docx, *.pptx → OLE embeddings → L1/
                    *.pptx                  → ppt/media/ images → L1/pptx_media/   ← 必须
Layer 1 (L1/):      *.xlsx, *.docx, *.pptx → OLE embeddings → L2/
                    *.pptx                  → ppt/media/ images → L2/pptx_media/   ← 必须
                    *.bin                   → OLE extract → L2/
Layer 2 (L2/):      *.pptx                 → OLE embeddings → L3/
                    *.pptx                  → ppt/media/ images → L3/pptx_media/   ← 必须
                    *.bin                   → OLE extract → L3/
```

**`ppt/media/` 提取与 OLE embeddings 提取同等必须，不是"fallback"——两者并行执行。**
原因：OLE 嵌入图片可能 link-only（不可恢复），而 `ppt/media/` 的图片始终有效。

For each layer, process ALL Office files. After extraction, read each file before moving to the next layer.

**Log each layer:**
```python
log.step("Step 1b: Recursive embedded file extraction")
# After each L0 file processed:
log.file("SSTS KP1 Fuel line.xlsx", "采购技术总要求", "L0")
# After L1 extraction from a source:
log.embed("SSTS KP1 Fuel line.xlsx", ["SSTS_CTS_fuel_supply_line.docx", "SSTS_TDR_list.docx"], ["oleObject1.bin"])
# After L2 extraction:
log.embed("SSTS_CTS_fuel_supply_line.docx", ["CTS_fuel_line_requirements.pptx", "CTS_materials_restricted.pdf"], [])
```

#### 1c. Rename extracted files

After each layer, identify file roles and rename:
`{source_doc_shortname}_{content_role}.{ext}`

**⚠️ 兜底规则（强制）：所有提取出的文件必须重命名，不得丢弃。**
若无法判断语义角色，使用序号回退命名：`{parent_prefix}_embed_{n}.{ext}`

```python
def rename_extracted(files: list, parent_prefix: str) -> dict:
    """
    Rename all extracted files. For unrecognized ones, fall back to sequential name.
    Returns {old_path: new_path}.
    """
    renamed = {}
    fallback_idx = 0
    for f in files:
        semantic_name = infer_semantic_name(f, parent_prefix)  # AI判断语义名
        if semantic_name:
            new_path = f.with_name(semantic_name)
        else:
            # 兜底：保留文件，使用序号名，不得静默丢弃
            new_path = f.with_name(f"{parent_prefix}_embed_{fallback_idx}{f.suffix}")
            fallback_idx += 1
            log.info(f"Renamed (fallback): {f.name} → {new_path.name}")
        f.rename(new_path)
        renamed[f] = new_path
    return renamed
```

> 兜底命名的文件后续仍需读取并分类，不可跳过。

**Discard**: OLE bins where neither `CONTENTS` nor `Ole10Native` yields PDF/ZIP (link-only objects).

#### 1d. Read PDF files — 强制三级回退链

每个 PDF **必须**走完整回退链直到成功读取，或明确记录失败原因。

```python
import subprocess
from pdftext.extraction import plain_text_output
from pathlib import Path

def read_pdf_required(pdf_path: Path, log) -> str:
    """
    强制读取 PDF，三级回退。任何一级成功即返回。
    全部失败则 log.error() 并返回空字符串（不允许静默跳过）。
    """
    path_str = str(pdf_path)

    # 级别 1: pdftext（最快，支持数字 PDF）
    try:
        text = plain_text_output(path_str)
        if len(text.strip()) >= 100:
            log.info(f"PDF read OK (pdftext): {pdf_path.name} — {len(text)} chars")
            return text
        log.warn(f"pdftext returned <100 chars for {pdf_path.name}, trying fallback")
    except Exception as e:
        log.warn(f"pdftext failed for {pdf_path.name}: {e}, trying fallback")

    # 级别 2: marker_single（OCR，适合扫描件）
    try:
        out_dir = pdf_path.parent / "_ocr_tmp"
        out_dir.mkdir(exist_ok=True)
        result = subprocess.run(
            ["marker_single", path_str, str(out_dir)],
            capture_output=True, text=True, timeout=120
        )
        md_files = list(out_dir.glob("**/*.md"))
        if md_files:
            text = md_files[0].read_text(encoding="utf-8")
            if len(text.strip()) >= 100:
                log.info(f"PDF read OK (marker OCR): {pdf_path.name} — {len(text)} chars")
                return text
    except Exception as e:
        log.warn(f"marker_single failed for {pdf_path.name}: {e}, trying Read tool")

    # 级别 3: Read tool（≤20 pages/call，适合中文文件名等边界情况）
    # 此级别需要 AI 手动调用 Read tool，无法在 Python 中自动化。
    # 执行到此处时，必须用 Read tool 读取该文件，不可跳过。
    log.error(f"pdftext & OCR both failed for {pdf_path.name} — READ TOOL REQUIRED (≤20 pages/call)")
    return ""  # 调用方必须检查返回值并用 Read tool 补读

# 调用示例：
# for pdf in all_pdfs:
#     text = read_pdf_required(pdf, log)
#     if not text:
#         # 必须在这里用 Read tool 读取 pdf，然后继续
#         pass
#     file_tracker.mark_read(pdf)  # ← 见 §1h 状态追踪
```

> **关键规则**：`read_pdf_required` 返回空字符串时，**必须立即用 Read tool 补读**，
> 不允许继续执行下一个文件。静默跳过 = 数据缺失。

#### 1e. PPTX media 提取（与 OLE 并行，无条件执行）

`ppt/media/` 提取**不是 fallback**，是与 OLE embeddings 并行的必须步骤。
对每个 PPTX 文件，在提取 OLE embeddings 的同时，也提取 `ppt/media/` 的图片。

```python
import zipfile
from pathlib import Path

def extract_pptx_media(pptx_path: Path, dest_dir: Path, prefix: str):
    """
    从 PPTX 的 ppt/media/ 提取所有图片。
    与 OLE embeddings 并行执行，不是"fallback"。
    原因：OLE 嵌入图片可能 link-only（外部 TIF 链接），而 ppt/media/ 始终是有效图片。
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    with zipfile.ZipFile(pptx_path) as z:
        for entry in z.namelist():
            if entry.startswith('ppt/media/') and Path(entry).suffix.lower() in ('.jpg', '.jpeg', '.png'):
                data = z.read(entry)
                out = dest_dir / f"{prefix}_{Path(entry).name}"
                out.write_bytes(data)
                extracted.append(out)
    return extracted

# 调用时机：提取完 OLE embeddings 后，对同一 PPTX 紧接调用：
# media_imgs = extract_pptx_media(pptx_path, layer_dir / "pptx_media", prefix)
# for img in media_imgs:
#     file_tracker.add(img)   # ← 加入待读清单
```

#### 1f. Read-tool image guard

**NEVER pass an image file to the Read tool without first verifying it is readable.**
Passing a corrupt image causes `API Error 400 – Could not process image` and blocks
the entire session.

```python
def is_readable_image(path: Path) -> bool:
    """Return True only if the Read tool can safely open this image."""
    try:
        from PIL import Image
        import io
        Image.open(io.BytesIO(path.read_bytes())).verify()
        return True
    except Exception:
        return False

# Usage before every Read-tool call on an image:
if is_readable_image(img_path):
    # Use Read tool here
    pass
else:
    log.warn(f"{img_path.name}: unreadable image (corrupt/link-only OLE) — skipped")
```

#### 1g. Extraction completion checklist

Before proceeding to Step 2, confirm:
- [ ] All L0 Office files checked for OLE embeddings
- [ ] All L0 PPTX files: `ppt/media/` extracted to `L1/pptx_media/`
- [ ] All L1 files checked for OLE embeddings (→ L2)
- [ ] All L1 PPTX files: `ppt/media/` extracted to `L2/pptx_media/`
- [ ] All L2 files checked for OLE embeddings (→ L3)
- [ ] All L2 PPTX files: `ppt/media/` extracted to `L3/pptx_media/`
- [ ] All OLE .bin files processed (PDF/JPG extracted or discarded as link-only)
- [ ] All extracted files renamed to meaningful names
- [ ] **File tracker unread set is empty** (see §1h)

#### 1h. 执行状态追踪（防止遗漏）

在 Precondition 之后立即建立文件追踪器。每处理完一个文件就划掉。
写 artifact 前必须断言追踪器为空。

```python
class FileTracker:
    """追踪所有需要读取的文件，防止执行中断后遗漏。"""
    def __init__(self):
        self.unread: set = set()
        self.skipped: dict = {}   # path → reason

    def add(self, path):
        """将文件加入待读清单。"""
        self.unread.add(str(path))

    def mark_read(self, path):
        """标记文件已成功读取。"""
        self.unread.discard(str(path))

    def mark_skipped(self, path, reason: str):
        """标记文件已确认跳过（link-only / unreadable），附原因。"""
        self.unread.discard(str(path))
        self.skipped[str(path)] = reason

    def assert_complete(self):
        """调用 store.write() 前必须通过此断言。"""
        if self.unread:
            raise AssertionError(
                f"以下 {len(self.unread)} 个文件尚未读取，禁止写 artifact：\n" +
                "\n".join(f"  - {f}" for f in sorted(self.unread))
            )

# 使用模式：
# file_tracker = FileTracker()
#
# # 提取阶段：每发现一个文件就 add()
# for pdf in all_pdfs:
#     file_tracker.add(pdf)
# for img in media_imgs:
#     file_tracker.add(img)
#
# # 读取阶段：读完就 mark_read()，确认跳过就 mark_skipped()
# text = read_pdf_required(pdf, log)
# if text:
#     file_tracker.mark_read(pdf)
# else:
#     # 用 Read tool 读取后：
#     file_tracker.mark_read(pdf)
#
# if is_readable_image(img):
#     # Read tool 读取图片
#     file_tracker.mark_read(img)
# else:
#     file_tracker.mark_skipped(img, "corrupt OLE thumbnail")
#
# # 写 artifact 前：
# file_tracker.assert_complete()   # ← 未读完则抛出异常，阻止写入
# store.write('n01', artifact)
```

> **为什么需要追踪器？**
> 当 session 因错误中断后重启，AI 无法可靠地判断前次运行处理到哪一步。
> 追踪器在代码层面强制"所有文件读完才能写 artifact"，
> 无论 session 中断多少次都能防止遗漏。

---

### Step 2: Identify OEM

```python
log.step("Step 2: Identify OEM")
```

From document headers, part-number prefixes, terminology, company logos/names:

| Indicator | OEM |
|-----------|-----|
| SSTS, PF.xxxxx | Stellantis |
| Formel-Q, VW-Norm | Volkswagen Group |
| QMT, BMW-norm | BMW |
| CATIA/ENO part numbers | Stellantis or PSA |

If uncertain, ask user before continuing.

```python
log.info(f"OEM identified: {oem}")  # e.g. "OEM identified: Stellantis"
```

---

### Step 3: Classify Each File

```python
log.step("Step 3: Classify all files")
```

Tag every file (original + all extracted, every layer) as one of:

1. **采购技术总要求** (SOR/SSTS) — top-level requirements and project scope
2. **零部件技术规范** (CTS/DTS) — part-specific technical requirements
3. **性能标准** (PF) — test and performance standard
4. **零件描述/BOM** — part structure, materials, assembly
5. **交付物清单** (TDR) — what supplier must submit
6. **报价/交付模板** — fill-in templates (ED&D PBD, SDT, RASI, exception list…)

> **Tip (Stellantis)**: CTS docx typically embeds a PPTX with dimensional specs and a PPTX with
> packaging/routing layout. TDR docx typically embeds 4–6 xlsx templates. Both are S1 data.

After classifying, log each file:
```python
log.file("SSTS KP1 Fuel line.xlsx", "采购技术总要求 (SSTS)", "L0")
log.file("PF.90197.pdf", "性能标准 — 主规范", "L0")
log.file("CTS_fuel_line_requirements.pptx", "零部件技术规范附件 — 管路尺寸 (关键!)", "L2")
```

---

### Step 4: Extract Structured Fields

```python
log.step("Step 4: Extract structured fields")

# ── 在 Step 4 开始时初始化 ExtractionMatrix ──────────────────────────────
import sys
sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from extraction_matrix import ExtractionMatrix

matrix = ExtractionMatrix('<project_path>', 'n01')
# 读取每个文件后调用 matrix.mark(file_type, field, value) 打勾
# file_type 必须是契约定义中的 key：SSTS_main / PF_main_spec / PF_qc_spec /
#   CTS_main_docx / CTS_dims_pptx / TDR_docx / KPC_image / material_compliance_doc
```

Read ALL files (all layers). Extract:

**Part identity**
- `part_number`, `part_name`, `platform`, `vehicle_model`, `engine_type`

**Project timeline**
- `sop_date`, `tko_date`, `rfq_response_date`, `annual_volume`

**Geometry** (often in CTS-embedded PPTX, not in main PPTX):
```json
{
  "feed_line_od_mm": 8, "feed_line_id_mm": 6,
  "return_line_od_mm": 10, "return_line_id_mm": 8,
  "confidence": "S1", "source_doc": "CTS_fuel_line_requirements.pptx"
}
```

**Performance requirements** — one entry per parameter per condition:
```json
{
  "id": "PR-001", "parameter": "Burst pressure",
  "value": "≥36", "unit": "bar", "condition": "@RT (23°C)",
  "confidence": "S1", "source_doc": "PF.90197", "source_section": "§7.4"
}
```
> Multi-condition rule: different values under different conditions → one entry per condition. NEVER merge.

**Test matrix** — one entry per test:
```json
{
  "test_name": "Burst test", "procedure": "SAE J2045 §4.8",
  "acceptance": "≥36 bar @RT", "phase": "DV/PV",
  "source_doc": "PF.90197", "source_section": "§7.4"
}
```

**Special characteristics** (CC/SC):
```json
{
  "type": "SC", "parameter": "Leak-tightness",
  "requirement": "No leak at ≥150 PSI", "confidence": "S1",
  "source_doc": "PF.90197", "source_section": "§7.2"
}
```

> **⚠️ 常见漏洞**：KPC 图片只是起点，必须补充：
> - **Leak-tightness / Pressure Seal** → 来自 PF.90197 §7.2（往往不在 KPC 图片里）
> - **QC secondary latch** → 来自 PF.90298 §1.8（new designs 强制要求）
> - **Static charge dissipation** → 来自 PF.90197 §6.2.5
> - **Key dimensional characteristics (Cpk)** → 来自 PF.90298 §6.2.2 + QR-10012
>
> 判断 SC vs CC 规则（Stellantis）：⊗/钻石符号 = CC；H/圆圈符号 = SC。
> 若 PF 规范把某参数定为"mandatory"但未出现在 KPC 图片 → 补充为 SC，confidence S1，注明来源。

**Referenced standards** — every standard cited anywhere:
```json
{"standard_id": "SAE J2044", "title": "Quick Connect Coupling", "available": false}
```

> **⚠️ 常见漏洞**：只列主要标准会漏掉 20-30 个。**必须**从每份 PF 规范的 Section 2 (REFERENCES / Table X)
> 系统提取全部引用。典型 PF.90197 Section 2 含 10+ 内部标准 + 10+ 外部标准（SAE、DIN、EN、FMVSS）。
>
> **提取方法（对每份 PDF text）**：
> ```python
> import re
> # 找 "2 REFERENCES" 到下一个一级章节之间的区域
> m = re.search(r'2\s+REFERENCES.*?(?=\n\d+\s+[A-Z])', pdf_text, re.DOTALL)
> if m:
>     ref_block = m.group(0)
>     # 提取 表格行：标准号 + 标题 两列
>     rows = re.findall(r'((?:SAE|DIN|EN|CS\.|PF\.|MS\.|PS\.|QR\.|LP\.|SD\.|FMVSS|REACH|ISO)\S+)\s+(.+)', ref_block)
>     for std_id, title in rows:
>         standards.append({"standard_id": std_id.strip(), "title": title.strip()[:80],
>                            "available": std_id in available_in_inputs})
> ```
> 对所有 PF PDF 都执行此步，合并去重。最终 `referenced_standards` 通常 30-40 条。

**Quality targets**: reliability (P99C90 / R95C90), CCP, ICP, PPM/Cpk if stated.

**Material compliance**:
```json
{
  "restricted": ["Pb", "Hg", "Cd", "Cr6+"],
  "standards": ["EU Dir.2000/53/CE", "REACH", "OEM spec"],
  "imds_required": true, "confidence": "S1"
}
```

**Deliverables required**: from TDR — name, phase (SOURCING/TKO/DV/PV/SOP),
`template_available` (true if template found in embedded files), `template_file`.

> **⚠️ 常见漏洞**：TDR docx 必须逐段读取，不能只看标题。Stellantis TDR 典型包含 16 项：
> - CAD 文件（UG/TeamCenter + Parasolid）
> - Co-design cost breakdown
> - CDS Component Development Sheet
> - SDT Supplier Development Team
> - RASI chart
> - Deviation/Exception list
> - DVP&R plan（DV+PV）
> - SVP test plan
> - EDD PBD
> - Additional materials list
> - Product and process FMEA
> - Complete 2D drawings
> - Analysis support (system performance)
> - Support SOP at assembly plant
> - IMDS material data sheet
> - Best practices sharing
>
> 对每项确认：是否有现成模板文件（`template_available=true`），模板路径写入 `template_file`。
>
> **⚠️ 模板关联是强制步骤，不可跳过。** 在提取交付物清单时，不要只提取名称——
> 必须同时检查该交付物描述段落中是否嵌入了 xlsx/docx 模板文件（Step 1 已经提取到 L1/L2/L3），
> 并立即设置 `template_available=true` + `template_file`。
> **如果不在这一步关联，Step 4g 是最后的兜底检查。** 但最佳实践是在读 TDR 时就同步关联。

---

**Build source_index** — 在 Step 4 结束时，将每个有意义的原始文件按语义 key 编入索引。规则：
- 所有 `inputs/` 文件都应有对应 key
- 所有提取出的 L1/L2/L3 文件中，内容有独立价值的（规范附件、KPC 图、材料要求）应有 key
- 模板文件用 `*_template` 命名（已通过 deliverables_required 的 template_file 字段覆盖，source_index 可省略）
- key 名语义化，下游节点 guide 会直接引用这些 key

```python
log.step("Step 4f: Build source_index")
source_index = {
    "main_performance_spec":    "inputs/PF.90197.pdf",
    "routing_and_packaging":    "artifacts/_embedded/L2/CTS_fuel_line_requirements.pptx",
    "kpc_table":                "artifacts/_embedded/L2/CTS_oleObject1_extracted.jpg",
    # ... 所有有价值的文件
}
log.info(f"source_index: {len(source_index)} entries")
```

#### Step 4g: Template Matching（模板关联 — 强制步骤）

**此步骤不可跳过。** 客户提供的模板文件是下游节点填写交付物的基础，漏关联 = 下游从零生成 = 格式不合规。

原理：OEM 的交付物清单文档（如 Stellantis TDR docx、VW Lastenheft）通常会将模板文件作为嵌入对象（xlsx/docx）
内嵌在交付物描述段落旁边。Step 1 已经把这些嵌入文件提取到 L1/L2/L3，但它们只是"提取出来的文件"，
还没有和 `deliverables_required` 中的条目建立关联。

**执行规则：**

```python
log.step("Step 4g: Template matching — 将提取的模板文件关联到交付物")

# 1. 收集所有从"交付物清单文档"提取出的 xlsx/docx 文件
#    （即从 TDR/Lastenheft 类文档嵌入提取的文件，不包括从性能标准提取的）
tdr_source_files = [f for f in embedded_files if f['source_doc_role'] in ('TDR', '交付物清单')]
template_candidates = [f for f in all_extracted_files
                       if f.suffix.lower() in ('.xlsx', '.docx')
                       and f is extracted_from(tdr_source)]

# 2. 对每个候选模板，通过内容匹配确定它属于哪个交付物
#    匹配方法（按优先级）：
#    a. 文件名包含交付物关键词（如 "PBD", "SDT", "RASI", "exception", "DVPR"）
#    b. 读取文件第一个 sheet 的标题行，与 deliverables_required 的 name 做模糊匹配
#    c. 文件在源文档中的位置（紧跟在某个交付物描述段落之后）

# 3. 关联：设置 template_available=True + template_file=提取路径
for d in deliverables_required:
    matched_template = match_template(d['name'], template_candidates)
    if matched_template:
        d['template_available'] = True
        d['template_file'] = str(matched_template.relative_to(project_path))
        log.info(f"Template matched: {d['id']} {d['name']} → {matched_template.name}")
        # 同时写入 source_index
        source_index[f"{d['id'].lower()}_template"] = str(matched_template)

# 4. 检查：输入文件夹中的独立模板文件（如 STLA-DVPR模板.xlsx）也要匹配
for f in inputs_dir.glob('*模板*'):
    # 同样匹配到 deliverables_required
    pass
for f in inputs_dir.glob('*template*'):
    pass

# 5. 日志汇总
matched = sum(1 for d in deliverables_required if d.get('template_available'))
log.info(f"Template matching: {matched}/{len(deliverables_required)} deliverables have customer templates")
if matched == 0:
    log.warn("No customer templates found — downstream nodes will generate from scratch")
```

**关键约束：**
- 从交付物清单文档提取的**每一个 xlsx/docx** 都必须尝试关联，不允许静默忽略
- 即使文件名无法识别，也要读取内容（sheet 名、标题行）再判断
- 未能关联的模板文件记录到 log 中：`log.warn(f"Unmatched template: {f.name} — manual review needed")`
- `inputs/` 中文件名包含"模板"或"template"的文件也要纳入匹配

完成 Step 4 时，在 log 中打 ExtractionMatrix 标记：
```python
# 每个文件读完后立即 mark，不要等到 Step 4 结束再统一 mark
# 示例：
matrix.mark('SSTS_main',         'part_number',            p['part_number'])
matrix.mark('SSTS_main',         'quality_targets',        quality_targets)
matrix.mark('PF_main_spec',      'design_life',            design_life)
matrix.mark('PF_main_spec',      'section2_standards',     pf197_stds)      # list
matrix.mark('PF_main_spec',      'annex_a_test_matrix',    pf197_tests)     # list
matrix.mark('PF_qc_spec',        'qc_operating_conditions', op_conditions)
matrix.mark('PF_qc_spec',        'qc_assembly_force',      asm_force)
matrix.mark('PF_qc_spec',        'qc_pull_apart_force',    pull_apart)
matrix.mark('PF_qc_spec',        'qc_impact_criterion',    impact)
matrix.mark('PF_qc_spec',        'section2_standards',     pf298_stds)      # list
matrix.mark('CTS_main_docx',     'referenced_standards_list', cts_stds)
matrix.mark('CTS_main_docx',     'performance_spec_refs',  spec_refs)
matrix.mark('CTS_dims_pptx',     'geometry_feed_line',     feed_line_geo)
matrix.mark('CTS_dims_pptx',     'qc_connector_spec',      qc_spec)
matrix.mark('TDR_docx',          'deliverables_list',      deliverables)    # list ≥ 8
matrix.mark('KPC_image',         'special_characteristics', sc_list)        # list ≥ 4
matrix.mark('material_compliance_doc', 'restricted_substances', restricted)
matrix.mark('material_compliance_doc', 'imds_required',     True)
```

After extraction, log key counts:
```python
log.info(f"Performance requirements: {len(perf_reqs)}")
log.info(f"Test matrix items: {len(test_matrix)}")
log.info(f"Special characteristics: {len(special_chars)}")
log.info(f"Referenced standards: {len(standards)} ({sum(1 for s in standards if s['available'])} available)")
log.info(f"Deliverables: {len(deliverables)} ({sum(1 for d in deliverables if d.get('template_available'))} with templates)")
if annual_volume is None:
    log.warn("annual_volume not found in any document")
if sop_date is None:
    log.warn("sop_date not found in any document")
```

---

### Step 5: Gap Identification

```python
log.step("Step 5: Gap identification")
```

> **⚠️ 严格遵守以下 gap 表**：不得随意替换 gap ID 或改变 gap 主题。
> 此表是 canonical（权威定义），下游节点按固定 rule ID 消费这些 gap。

| Gap | Rule | Severity | Assumption |
|-----|------|----------|------------|
| `annual_volume` missing | R-01-01 | warning | 50,000/yr (S4) |
| `sop_date` missing | R-01-02 | warning | none（不可假设） |
| Referenced standards not in inputs/ | R-01-03 | error | 列出全部缺失标准 ID |
| No 3D model (OLE link unrecoverable) | R-01-04 | info | handled by n03 |
| `part_number` not found | R-01-05 | error | blocks n02 |
| `geometry` not found | R-01-06 | warning | blocks n06 |
| `tko_date` / `rfq_response_date` missing | R-01-07 | warning | none |
| PF spec type mismatch with product | R-01-08 | warning | 说明差异 |

**R-01-03 必须执行**：将 `referenced_standards` 中 `available=false` 的条目全部列出。
这是报价阶段向客户索要文件的依据，跳过此步会导致后续节点无法获取规范文本。

S1 字段缺失（part_number、geometry）→ severity `error`，禁止用假设填充。

```python
missing_stds = [s['standard_id'] for s in standards if not s['available']]
log.gap("R-01-01", "annual_volume 未在任何文件中说明", "warning", "50,000/年 (S4)")
if sop_date is None:
    log.gap("R-01-02", "sop_date 未在任何文件中说明", "warning")
if missing_stds:
    log.gap("R-01-03",
            f"{len(missing_stds)} 个引用标准未提供于 inputs/: {', '.join(missing_stds[:8])}...",
            "error")
if no_3d_model:
    log.gap("R-01-04", "3D model 不可用 (OLE链接指向外部文件无法恢复)", "info")
```

---

## Output Schema

```json
{
  "node": "n01",
  "project": "<project_id>",
  "status": "ready",
  "produced_at": "<ISO8601>",
  "confidence_floor": "S1",
  "gaps": [
    {
      "rule": "R-01-01",
      "msg": "annual_volume 未在任何文档中说明",
      "severity": "warning",
      "assumption": "50,000/年 (S4)"
    }
  ],
  "assumptions": [],
  "payload": {
    "oem": "Stellantis",
    "product_category": "fuel-supply-line",
    "part_number": "FC00SAA78530",
    "part_name": "Fuel supply line — diesel filter to engine",
    "program": "KP1 A&B",
    "engine": "2.2 diesel",
    "platform": "KP1",
    "annual_volume": null,
    "sop_date": null,
    "working_pressure_bar": 4.5,
    "design_life": "15 years / 150,000 miles",
    "rfq_files": [],
    "file_roles": [],
    "embedded_files": [
      {"file": "L1/SSTS_CTS.docx", "role": "零部件技术规范", "source": "SSTS xlsx"},
      {"file": "L2/CTS_dims.pptx",  "role": "CTS附件 — 管路尺寸 (关键!)", "source": "CTS docx"}
    ],
    "geometry": {},
    "performance_requirements": [],
    "test_matrix": [],
    "special_characteristics": [],
    "referenced_standards": [],
    "quality_targets": {},
    "material_compliance": {},
    "deliverables_required": [],
    "source_index": {
      "main_performance_spec":    "inputs/PF.90197.pdf",
      "routing_and_packaging":    "artifacts/_embedded/L2/CTS_fuel_line_requirements.pptx",
      "kpc_table":                "artifacts/_embedded/L2/CTS_oleObject1_extracted.jpg"
    }
  }
}
```

---

## Close Log

> **⚠️ gaps 字段命名**：`log.done()` 读取 `g['msg']`，**不是** `g['description']`，否则触发 `KeyError`。

```python
import sys
sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from reporter import NodeReport

# 1. 文件完整性门控 — 有未读文件则抛出
file_tracker.assert_complete()

# 2. 字段完整性门控 — 有必填字段未提取则抛出
matrix.assert_complete()   # ← ExtractionMatrix: 7类必填字段全部打勾才通过

# 3. 写 artifact + 关闭执行日志
store.write('n01', artifact)
log.done(artifact)

# 3. 写执行过程总结（AI 根据本次实际执行情况填写，不可省略）
execution_summary = """
### 读取的文件

| 层级 | 文件 | 内容 |
|------|------|------|
| L0 | `<filename>` | <角色描述> |
... （列出所有实际读取的文件，含嵌入文件和图片，跳过的文件也要列出并注明原因）

### 过程中解决的问题

- **<问题名称>**: <原因> → <解决方案>
- 无异常（如本次无问题则写此行）

### 假设与判断

- **<字段>**: <理由>（置信度 Sx）
- 无（如本次无假设则写此行）

### 对 skill 的改进

- <本次对 skill/guide 所做的修改>
- 无（如本次未修改则写此行）
"""

# 4. 保存提取覆盖率报告（供回溯分析）
matrix.save_report(artifact)
# → 写入 artifacts/n01-extraction-coverage.json

# 5. 生成报告文件 + 向用户打印摘要
report = NodeReport('<project_path>', 'n01')
report.write(artifact, execution_summary=execution_summary)
report.print_summary(artifact)
# → 报告写入 reports/n01-report-YYYYMMDD-HHMMSS.md
```

---

## Validation

```python
import json, sys
from pathlib import Path

sys.path.insert(0, '/home/chu2026/Documents/APQPOS/.claude/skills/apqp-os/scripts')
from store import ArtifactStore

store = ArtifactStore('<project_path>')
a = store.read('n01')
p = a['payload']

assert a['status'] == 'ready'
assert p.get('oem'),                       "OEM not identified"
assert p.get('part_number'),               "part_number missing — n02 blocked"
assert p.get('product_category'),          "product_category missing"
assert p.get('program'),                   "program missing"
assert p.get('performance_requirements'),  "No performance requirements extracted"
assert p.get('embedded_files'),            "embedded_files not catalogued"
assert p.get('source_index'),              "source_index missing — downstream nodes blocked"
assert p.get('material_compliance'),       "material_compliance missing"
assert len(p.get('referenced_standards', [])) >= 20, \
    f"referenced_standards only {len(p.get('referenced_standards',[]))} — expected ≥20 (read PF spec Section 2)"
assert len(p.get('deliverables_required', [])) >= 10, \
    f"deliverables_required only {len(p.get('deliverables_required',[]))} — expected ≥10 (read TDR docx fully)"

# Template coverage check — 从 TDR 提取的 xlsx 必须全部关联到交付物
tpl_count = sum(1 for d in p.get('deliverables_required', []) if d.get('template_available'))
assert tpl_count >= 1, \
    "No customer templates linked to deliverables — run Step 4g Template Matching"
# Warning if embedded xlsx exist but few templates linked
embedded_xlsx = [e for e in p.get('embedded_files', []) if '.xlsx' in str(e.get('file', ''))]
if len(embedded_xlsx) > tpl_count + 2:  # allow 2 non-template xlsx (e.g. SSTS附表)
    print(f"⚠ {len(embedded_xlsx)} xlsx files extracted but only {tpl_count} linked as templates — check Step 4g")
assert len(p.get('special_characteristics', [])) >= 8, \
    f"special_characteristics only {len(p.get('special_characteristics',[]))} — supplement from PF spec text"

gap_rules = [g['rule'] for g in a.get('gaps', [])]
assert 'R-01-01' in gap_rules or p.get('annual_volume'), "R-01-01 gap (annual_volume) missing"
assert 'R-01-03' in gap_rules or all(s.get('available') for s in p.get('referenced_standards',[])), \
    "R-01-03 gap (missing standards) missing — every unavailable standard must be flagged"

gaps = {}
for g in a['gaps']:
    gaps.setdefault(g['severity'], []).append(g['rule'])

print(f"✓ n01 valid")
print(f"  Part: {p['part_number']} — {p['part_name']}")
print(f"  Performance requirements : {len(p['performance_requirements'])}")
print(f"  Test items               : {len(p['test_matrix'])}")
print(f"  Special characteristics  : {len(p['special_characteristics'])}")
print(f"  Referenced standards     : {len(p['referenced_standards'])} ({sum(1 for s in p['referenced_standards'] if s.get('available'))} available)")
print(f"  Embedded files           : {len(p['embedded_files'])}")
print(f"  Deliverables             : {len(p['deliverables_required'])} ({sum(1 for d in p['deliverables_required'] if d.get('template_available'))} with templates)")
print(f"  Source index entries     : {len(p['source_index'])}")
print(f"  Confidence floor         : {a['confidence_floor']}")
print(f"  Gaps                     : {gaps}")
```

---

## Optimize Mode

当客户补充了新文件（如更新的规范 PDF、补充的 TDR 文档）时：

1. 读取现有 `artifacts/n01-output.json`
2. 仅对新增/变更文件执行 Step 1（嵌入提取）→ Step 3（分类）→ Step 4（提取）
3. 将新提取的数据**合并**到现有 payload 中（不删除已有数据）
4. 更新 `source_index` 中受影响的条目
5. 重新评估 `confidence_floor`：如果新数据替换了 S4/S5 假设，可提升
6. 从 `gaps` 中移除已解决的条目（如客户补了 annual_volume → 移除 R-01-01）
7. 重新运行 ExtractionMatrix 和 Validation
8. log 中所有 step 标题加 `[Optimize]` 前缀

**注意**：n01 是 DAG 根节点，Optimize 后运行 `orchestrator.py affected n01` 查看下游影响。

---

## Review Mode

仅检查现有 artifact 质量，不修改文件：

1. 读取 `artifacts/n01-output.json`
2. 运行 `python3 extraction_matrix.py artifacts/n01-output.json`
3. 运行上方 Validation 代码段
4. 输出质量摘要：gaps 数量（按 severity）、assumptions 数量、confidence_floor、source_index 覆盖率
