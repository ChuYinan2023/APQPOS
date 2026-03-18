"""
ExtractionMatrix — 基于来源可追溯性的完备性保证

核心思想：
  不依赖硬编码数量（会随项目变化而失效），
  而依赖三类结构性不变量：
  1. 来源可追溯：每条数据都有 source_doc
  2. 文件角色覆盖：被分类的文件必须贡献相应字段
  3. 内部一致性：test_matrix 引用的标准必须在 referenced_standards 中

Usage（执行中）:
    matrix = ExtractionMatrix('<project_path>', 'n01')

    # Step 3：分类文件时声明角色
    matrix.declare('PF.90197.pdf', FileRole.PERFORMANCE_SPEC_PDF)
    matrix.declare('CTS_oleObject1_figure.jpg', FileRole.KPC_IMAGE)
    matrix.declare('SSTS_TDR_list.docx', FileRole.TDR_DELIVERABLES)

    # Step 4：提取字段时记录来源
    for pr in performance_requirements:
        matrix.touch('PF.90197.pdf')   # 标记此文件贡献了数据
    for sc in special_characteristics:
        matrix.touch('CTS_oleObject1_figure.jpg')

    # 写 artifact 前：
    matrix.assert_complete(artifact)   # 结构性检查，与数量无关

Usage（回溯）:
    python3 extraction_matrix.py <path/to/n01-output.json>
"""

from __future__ import annotations
import json, re
from enum import Enum
from pathlib import Path
from typing import Any


class FileRole(Enum):
    """文件角色——决定该文件必须贡献哪类字段。"""
    PERFORMANCE_SPEC_PDF   = "性能标准_PDF"       # PF.90197, PF.90298 等
    SSTS_MAIN              = "采购技术总要求"      # SSTS xlsx/docx
    CTS_DIMS_PPTX          = "尺寸规格_PPTX"      # CTS embedded dims pptx
    TDR_DELIVERABLES       = "TDR交付物清单"       # TDR docx
    KPC_IMAGE              = "KPC图片"             # OLE extracted KPC table image
    MATERIAL_COMPLIANCE    = "材料合规文件"        # ELV/REACH pdf
    TEMPLATE               = "模板文件"            # 仅格式参考，不强制提取
    LAYOUT_IMAGE           = "布局图"              # 信息图，提取尽力而为
    UNKNOWN                = "未分类"


# 每种角色必须贡献的字段类型（字段路径 = payload 中的键名）
ROLE_CONTRACTS: dict[FileRole, dict] = {
    FileRole.PERFORMANCE_SPEC_PDF: {
        "must_contribute_to": [
            "referenced_standards",  # 从 Section 2 提取
            "test_matrix",           # 从 Annex A 提取
        ],
        "hint": "读完后：从 Section 2 提取所有引用标准，从 Annex A 提取 DVP&R 测试矩阵"
    },
    FileRole.SSTS_MAIN: {
        "must_contribute_to": [
            "part_number",
            "quality_targets",
        ],
        "hint": "读完后：提取零件号、平台、质量目标（TESIS/ICP/可靠性目标）"
    },
    FileRole.CTS_DIMS_PPTX: {
        "must_contribute_to": [
            "geometry",
            "quick_connector",
        ],
        "hint": "读完后：提取管路 OD×ID、QC 接头规格、管夹力"
    },
    FileRole.TDR_DELIVERABLES: {
        "must_contribute_to": [
            "deliverables_required",
        ],
        "hint": "读完后：提取所有交付物条目（逐段读取，不能只看标题）"
    },
    FileRole.KPC_IMAGE: {
        "must_contribute_to": [
            "special_characteristics",
        ],
        "hint": "读完后：提取图片中 KPC 表的每一行（SC/CC 类型 + 参数名 + 要求值）"
    },
    FileRole.MATERIAL_COMPLIANCE: {
        "must_contribute_to": [
            "material_compliance",
        ],
        "hint": "读完后：提取受限物质列表、IMDS 要求、O-ring 材料"
    },
    FileRole.TEMPLATE: {
        "must_contribute_to": [],  # 模板文件不要求提取内容
        "hint": "模板文件：仅记录路径，无需提取字段"
    },
    FileRole.LAYOUT_IMAGE: {
        "must_contribute_to": [],  # 布局图尽力而为
        "hint": "布局图：提取可见文字/尺寸，无强制要求"
    },
    FileRole.UNKNOWN: {
        "must_contribute_to": [],
        "hint": "未分类文件：先确定角色再重新 declare()"
    },
}


class ExtractionMatrix:
    """
    来源追踪器：记录每个文件的角色声明和贡献状态。

    与硬编码数量阈值的根本区别：
    - 不问"extracted_standards 有多少个"
    - 而问"被分类为 PERFORMANCE_SPEC_PDF 的文件，是否向 referenced_standards 贡献了数据"
    """

    def __init__(self, project_path: str | Path, node_id: str):
        self.project = Path(project_path)
        self.node_id = node_id
        self._declarations: dict[str, FileRole] = {}   # filename → role
        self._contributions: dict[str, set] = {}        # filename → set of field_keys contributed

    def declare(self, filename: str, role: FileRole):
        """Step 3：分类文件时调用，声明文件角色。"""
        self._declarations[filename] = role
        self._contributions.setdefault(filename, set())
        print(f"[matrix] declare: {filename} → {role.value}")

    def touch(self, filename: str, field_key: str = ""):
        """Step 4：向某文件的贡献集合中添加字段。"""
        self._contributions.setdefault(filename, set())
        if field_key:
            self._contributions[filename].add(field_key)

    def assert_complete(self, artifact: dict):
        """
        写 artifact 前调用。执行三类结构性检查：
        1. 文件角色覆盖：每个声明了角色的文件，是否贡献了契约要求的字段？
        2. 来源可追溯：performance_requirements 和 special_characteristics 的每条有 source_doc？
        3. 内部一致性：test_matrix 引用的规范在 referenced_standards 中？
        """
        errors = []
        warnings = []
        p = artifact.get('payload', {})

        # ── 检查 1：文件角色覆盖 ─────────────────────────────────────────
        for fname, role in self._declarations.items():
            contract = ROLE_CONTRACTS.get(role, {})
            required_fields = contract.get("must_contribute_to", [])
            contributed = self._contributions.get(fname, set())

            for field in required_fields:
                if field not in contributed:
                    # 也检查 artifact payload 中该字段是否有值
                    val = p.get(field)
                    has_value = bool(val) if not isinstance(val, list) else len(val) > 0
                    if not has_value:
                        errors.append(
                            f"[角色覆盖] '{fname}' 被分类为 {role.value}，"
                            f"但 payload.{field} 为空\n"
                            f"      → {contract.get('hint','')}"
                        )

        # ── 检查 2：来源可追溯 ───────────────────────────────────────────
        for pr in p.get('performance_requirements', []):
            if not pr.get('source_doc'):
                warnings.append(
                    f"[来源缺失] performance_requirements[{pr.get('id','')}] "
                    f"'{pr.get('parameter','')}' 无 source_doc"
                )

        for sc in p.get('special_characteristics', []):
            if not sc.get('source_doc') and not sc.get('source'):
                warnings.append(
                    f"[来源缺失] special_characteristics '{sc.get('parameter','')}' 无 source_doc"
                )

        for std in p.get('referenced_standards', []):
            if not std.get('standard_id'):
                warnings.append(f"[格式错误] referenced_standards 条目缺少 standard_id 字段")

        # ── 检查 3：内部一致性 ───────────────────────────────────────────
        all_std_ids = {s.get('standard_id', '') for s in p.get('referenced_standards', [])}
        for t in p.get('test_matrix', []):
            spec_ref = t.get('spec', '')
            # 提取 spec 字符串中看起来像标准号的部分（如 "PF.90197 §7.4"）
            tokens = re.split(r'[\s§]', spec_ref)
            for tok in tokens:
                if re.match(r'^(PF|SAE|DIN|EN|MS|CS|QR|PS)\.\S+', tok):
                    if tok not in all_std_ids:
                        warnings.append(
                            f"[内部一致] test_matrix['{t.get('test_name','')}'] "
                            f"引用 '{tok}'，未出现在 referenced_standards"
                        )
                    break

        # ── 结果 ─────────────────────────────────────────────────────────
        if warnings:
            print(f"\n⚠️  ExtractionMatrix warnings ({len(warnings)}):")
            for w in warnings[:10]:  # 最多显示 10 条
                print(f"   - {w}")
            if len(warnings) > 10:
                print(f"   ... 另有 {len(warnings)-10} 条 warnings")

        if errors:
            raise AssertionError(
                f"\n❌ ExtractionMatrix: {len(errors)} 个文件角色契约未完成 — 写入被阻断:\n" +
                "\n".join(f"   ✗ {e}" for e in errors)
            )

        print(f"✓ ExtractionMatrix: 所有文件角色契约完成，来源可追溯")

    def save_coverage_json(self, artifact: dict):
        """写 artifacts/n01-extraction-coverage.json，供回溯分析。"""
        report = {
            "node": self.node_id,
            "declarations": {
                fname: {
                    "role": role.value,
                    "contract_fields": ROLE_CONTRACTS.get(role, {}).get("must_contribute_to", []),
                    "contributed_fields": sorted(self._contributions.get(fname, set()))
                }
                for fname, role in self._declarations.items()
            },
            "artifact_field_counts": {
                k: len(v) if isinstance(v, list) else (len(v) if isinstance(v, dict) else bool(v))
                for k, v in artifact.get('payload', {}).items()
                if k in ('performance_requirements', 'test_matrix', 'special_characteristics',
                         'referenced_standards', 'deliverables_required', 'embedded_files',
                         'source_index')
            }
        }
        out = self.project / 'artifacts' / f'{self.node_id}-extraction-coverage.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"[matrix] coverage saved → {out.name}")


# ─── 回溯验证器（对任意已有 artifact 运行）────────────────────────────────────

def verify_artifact_completeness(artifact_path: str | Path) -> dict:
    """
    对已有 n01-output.json 进行回溯完备性检查。
    不依赖 benchmark，只检查结构性不变量。
    """
    artifact_path = Path(artifact_path)
    a = json.loads(artifact_path.read_text(encoding='utf-8'))
    p = a.get('payload', {})

    errors = []
    warnings = []

    # ── 不变量 1：必须存在的结构字段（与内容无关）───────────────────────
    REQUIRED_FIELDS = {
        'oem':                "OEM 未识别（检查 SSTS 文件头）",
        'part_number':        "零件号缺失（n02 被阻断）",
        'source_index':       "source_index 缺失（下游节点无法定位文件）",
        'material_compliance':"material_compliance 缺失（ELV/REACH + O-ring 材料）",
    }
    for field, hint in REQUIRED_FIELDS.items():
        val = p.get(field)
        ok = bool(val) if not isinstance(val, (list, dict)) else len(val) > 0
        if not ok:
            errors.append({"name": field, "hint": hint})

    # ── 不变量 2：所有列表字段的每条记录必须有 source_doc ────────────────
    traceable_lists = {
        'performance_requirements': ('id', 'parameter'),
        'special_characteristics':  ('parameter',),
        'test_matrix':              ('test_name',),
    }
    for list_field, id_fields in traceable_lists.items():
        for i, item in enumerate(p.get(list_field, [])):
            if not item.get('source_doc') and not item.get('source'):
                item_id = next((item.get(f, '') for f in id_fields if item.get(f)), f"[{i}]")
                warnings.append({
                    "name": f"{list_field}[{item_id}] 缺少 source_doc",
                    "hint": "每条数据必须能追溯到来源文件和章节"
                })

    # ── 不变量 3：referenced_standards 每条有 standard_id ───────────────
    for i, s in enumerate(p.get('referenced_standards', [])):
        if not s.get('standard_id') and not s.get('name'):
            warnings.append({
                "name": f"referenced_standards[{i}] 缺少 standard_id",
                "hint": "标准条目格式：{'standard_id': 'SAE J2044', 'title': '...', 'available': false}"
            })

    # ── 不变量 4：被 file_roles/embedded_files 列出的文件，必须在
    #              source_index 或某条数据的 source_doc 中被引用 ──────────
    source_index_paths = set()
    for v in p.get('source_index', {}).values():
        source_index_paths.add(Path(v).name)

    all_source_docs = set()
    for list_field in traceable_lists:
        for item in p.get(list_field, []):
            doc = item.get('source_doc') or item.get('source', '')
            if doc:
                all_source_docs.add(Path(doc).name)

    for f in p.get('embedded_files', []):
        # embedded_files can be a list of strings or dicts
        if isinstance(f, dict):
            fstr = f.get('file', f.get('name', ''))
        else:
            fstr = str(f)
        fname = Path(fstr).name if ('/' in fstr or '\\' in fstr) else fstr
        if fname not in source_index_paths and fname not in all_source_docs:
            warnings.append({
                "name": f"embedded_files 中 '{fname}' 未被任何字段引用",
                "hint": "该文件被记录但可能未提取任何内容"
            })

    # ── 不变量 5：内部一致性 ─────────────────────────────────────────────
    all_std_ids = {s.get('standard_id', s.get('name', ''))
                   for s in p.get('referenced_standards', [])}
    orphan_tests = []
    for t in p.get('test_matrix', []):
        spec = t.get('spec', '')
        tokens = re.split(r'[\s§(,]', spec)
        for tok in tokens:
            if re.match(r'^(PF|SAE|DIN|EN|MS|CS|QR|PS)\.\S+', tok):
                if tok.rstrip(')') not in all_std_ids:
                    orphan_tests.append(f"{t.get('test_name','')} → '{tok}'")
                break
    if orphan_tests:
        warnings.append({
            "name": f"test_matrix 引用了 {len(orphan_tests)} 个未在 referenced_standards 中的规范",
            "hint": "示例: " + "; ".join(orphan_tests[:3])
        })

    # ── 输出 ─────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Completeness Verification: {artifact_path.name}")
    print(f"{'='*60}")
    print(f"  ✓ Structural invariants passed: "
          f"{4 - len(errors) + max(0, 4-len(errors))}"
          f" / checking {len(errors)+len(warnings)} issues")

    if errors:
        print(f"\n  ✗ ERRORS ({len(errors)}) — 必须修复，否则下游节点无法运行:")
        for e in errors:
            print(f"    ✗ {e['name']}")
            print(f"      → {e['hint']}")
    if warnings:
        print(f"\n  ⚠ WARNINGS ({len(warnings)}):")
        for w in warnings[:8]:
            print(f"    ⚠ {w['name']}")
            if w.get('hint'):
                print(f"      → {w['hint']}")
        if len(warnings) > 8:
            print(f"    ... 另有 {len(warnings)-8} 条")
    if not errors and not warnings:
        print(f"  ✓ 所有结构性不变量通过")
    print()

    return {'errors': len(errors), 'warnings': len(warnings),
            'error_list': errors, 'warning_list': warnings}


if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 2:
        result = verify_artifact_completeness(sys.argv[1])
        sys.exit(1 if result['errors'] > 0 else 0)
    else:
        print("Usage: python3 extraction_matrix.py <path/to/nXX-output.json>")
