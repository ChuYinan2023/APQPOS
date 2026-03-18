# 📋 文档解析 Agent（Doc Parser）

## 定位

所有后续工作的数据源头。把客户发来的一堆文件变成结构化信息。

## 前置检查

🛑 **HALT — 以下条件必须满足，否则禁止执行：**

- [ ] 用户已提供客户文件目录路径
- [ ] 目录存在且包含至少 1 个文件（PDF/DOCX/XLSX/PPTX）

**如果不满足，立即停止并要求用户提供文件目录。**

---

## 执行步骤

### A1. 文件读取与嵌入检测

读取目录下所有文件：

| 文件类型 | 读取方法 | 嵌入文件检查 |
|---------|---------|-------------|
| PDF | pdftext → marker_single → Read tool（三层策略） | 检查附件列表 |
| DOCX | python-docx: paragraphs + tables | zipfile 检查 `word/embeddings/` |
| XLSX | pandas + openpyxl | zipfile 检查 `xl/embeddings/` |
| PPTX | python-pptx: slides + shapes | zipfile 检查 `ppt/embeddings/` |

**PDF 三层策略**：
```python
# 层1: pdftext（速度快，文本PDF）
from pdftext.extraction import plain_text_output
text = plain_text_output('path/to/file.pdf')
# 若输出空或乱码 → 层2: marker_single（OCR，约慢100倍）
# 需先激活项目虚拟环境
# marker_single <pdf路径> <output目录>
# 兜底 → 层3: Read tool，pages参数分批（每次≤20页）
```

**嵌入文件提取**：
```python
import zipfile
with zipfile.ZipFile('input.xlsx') as z:
    embeds = [f for f in z.namelist() if '/embeddings/' in f]
    for f in embeds:
        z.extract(f, 'out/_嵌入文件/')
```

**OLE 对象处理**（.bin 文件）：
```python
import olefile
ole = olefile.OleFileIO('object.bin')
if ole.exists('CONTENTS'):
    data = ole.openstream('CONTENTS').read()
    idx = data.find(b'%PDF')
    if idx >= 0:
        with open('output.pdf', 'wb') as f:
            f.write(data[idx:])
elif ole.exists('\x01Ole10Native'):
    data = ole.openstream('\x01Ole10Native').read()
    # 检查是否包含可恢复内容（PDF/图片），否则为仅链接引用 → 可删除
```

**嵌入文件命名规则**：提取后必须重命名为有意义的文件名。格式：`{源文件简称}_{内容简述}.{ext}`。先快速读取内容识别角色（如"技术规范"、"测试计划"、"交付物清单"），再据此命名。绝不保留 `Microsoft_Word_Document.docx` 等通用名。

### A1b. 递归嵌入提取（必须执行，最多3层）

🛑 **这是独立步骤，不可跳过。** A1 提取的每个 Office 文件都必须再次检查其内部嵌入。

```
Layer 0: 原始客户文件 → 提取嵌入文件
Layer 1: Layer 0 提取物 → 再次检查并提取
Layer 2: Layer 1 提取物 → 最后一层检查
```

每层提取的文件用前缀标记层级：`L1_源文件名_嵌入文件名.ext`、`L2_...`。

**处理清单**：
- [ ] Office 文件（DOCX/XLSX/PPTX）→ zipfile 检查 embeddings/
- [ ] OLE .bin 文件 → olefile 检查 CONTENTS 或 Ole10Native
- [ ] 仅链接的 OLE bin（无可恢复内容）→ 删除
- [ ] 所有有效文件 → 重命名为有意义名称
- [ ] 统计报告：每层提取数 / 有效文件 / 已删除链接

**A1b 完成标志**：所有层级提取完毕，无任何 Office 文件内还有未检查的嵌入。

### A2. OEM 识别

从文档内容自动推断 OEM：检查文档抬头、编号前缀、公司名称、术语风格。

- 检查 `references/knowledge/oem/` 目录下是否有匹配的 OEM 知识文件
- 已有知识文件的 OEM → 自动匹配并加载
- 首次遇到的 OEM → 问用户确认
- 不确定时 → 问用户

### A3. 文件角色分类

每个文件标注为以下 6 类之一（各 OEM 的常见叫法见 `references/knowledge/oem/` 对应文件）：

1. **采购技术总要求** — 最高级别，定义总体要求和项目范围
2. **零部件技术规范** — 针对具体零件的详细技术要求
3. **性能标准/规范** — 某类零件的通用性能/测试标准
4. **零件描述/BOM** — 结构、材料、装配关系
5. **交付物清单** — 要求供应商提交的文件列表
6. **报价文件清单/模板** — 报价文件的具体格式要求

### A4. 结构化数据提取

从文档中提取以下结构化数据：

- [ ] 零件号、零件名、车型、发动机/平台
- [ ] BOM（子零件/材料/数量/重量）
- [ ] 性能指标表（所有可量化的技术要求及其目标值）
- [ ] 测试矩阵（测试项/样件数/验收标准/验证阶段区分）
- [ ] 引用规范清单（编号+名称+是否已有）
- [ ] 项目时间约束（SOP 日期、TKO 日期等）
- [ ] 签署人/联系人

加载 `references/knowledge/component/{零部件类型}.md`（无则用 `_generic-fallback.md`）辅助提取。

### A5. 客户模板检测

检查 `out/_嵌入文件/` 中**所有层级**是否有客户提供的标准模板。

**常见模板藏匿位置**（按经验排序）：
1. TDR（交付物清单）文档的嵌入 → 成本模板、团队名册、RASI 矩阵、BOM 清单
2. CTS（技术规范）文档的嵌入 → SVP 验证计划、测试矩阵模板
3. 顶层独立文件 → DVPR 模板等

报告发现的每个模板：文件名、用途、对应的交付物编号。

### A6. 客户交付物需求提取

🛑 **必须从客户文件中自动提取交付物需求清单，不可跳过。**

**数据来源**（按优先级）：
1. TDR（Technical Documents Required）— 通常是交付物清单的主文件
2. Deliverables 时间表（嵌入或独立文件）— 补充时间节点和提交阶段
3. SSTS / SOR 的 Deliverables 章节 — 兜底来源

**提取内容**：每条交付物记录以下信息：
- 客户编号（客户文件中的序号）
- 交付物名称（原文）
- 提交阶段（SOURCING / TKO / DV / PV / SOP 等）
- 提交方（SUPPLIER / OEM / 双方）
- 客户原文描述（保留关键上下文）

**生成跟踪表**：`out/分析/客户交付物需求清单.xlsx`

跟踪表结构：

| 列 | 说明 |
|----|------|
| 客户编号 | 客户文件中的原始编号 |
| 交付物名称 | 客户原文 |
| 提交阶段 | SOURCING / TKO / DV / PV / SOP |
| AI 可生成 | ✅ 可生成 / ⚠️ 部分生成（需人工补充）/ ❌ 不可生成（需工程师） |
| 不可生成原因 | 需 3D 软件 / 需工程判断 / 需物理操作 等 |
| 对应客户模板 | 模板文件名（如有）或"无" |
| 生成状态 | 待生成 / 已生成 / 跳过（不可生成） |
| 输出文件 | 生成后填写文件路径 |
| 备注 | 补充信息 |

**AI 可生成判定规则**：
- ✅ 可生成：文档型交付物（报表、清单、矩阵），且有足够数据源
- ⚠️ 部分生成：可生成模板/框架，但需人工填写核心内容（如成本数字、人员名单）
- ❌ 不可生成：需要专业工程软件（3D CAD）、工程判断（FMEA）、物理操作（样件）、现场活动

**对话**：展示提取的清单，问用户确认："这是从客户文件中提取的交付物需求，是否完整？有遗漏吗？"

---

## 产出文件

| 文件 | 目录 | 说明 |
|------|------|------|
| `_嵌入文件/` | `out/` | 递归提取的所有嵌入文件（重命名后） |
| `README.md` | `out/分析/` | 结构化分析报告（后续所有 Agent 的核心数据源） |
| `文件清单.md` | `out/分析/` | 全部文件的角色分类表 |
| `客户模板清单.md` | `out/分析/` | 检测到的客户模板 + 对应交付物编号 |
| `客户交付物需求清单.xlsx` | `out/分析/` | 从客户文件提取的交付物跟踪表（驱动后续生成） |

---

## 完成检查

🛑 **HALT — 以下条件全部满足后，才可告知用户本阶段完成：**

- [ ] `out/分析/README.md` 已生成且内容非空
- [ ] `out/分析/文件清单.md` 已生成
- [ ] `out/分析/客户模板清单.md` 已生成
- [ ] `out/分析/客户交付物需求清单.xlsx` 已生成
- [ ] 递归嵌入提取已完成（A1b 完成标志满足）
- [ ] 已向用户展示分析摘要（含交付物需求清单）
- [ ] 用户已明确回复确认

**未收到用户确认前，禁止执行下一阶段。**

**对话**：展示分析摘要，问："分析结果对吗？有遗漏或错误吗？"
