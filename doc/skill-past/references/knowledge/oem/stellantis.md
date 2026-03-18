# Stellantis OEM 知识

## 文档体系

### 文档编号前缀
| 前缀 | 含义 | 示例 |
|------|------|------|
| PF. | Performance Standard（性能标准） | PF.90197, PF.90068, PF.90298 |
| MS. | Material Specification（材料标准） | MS.50017, MS.50015, MS.90111 |
| CS. | Corporate Standard（企业标准） | CS-9003, CS.00080, CS.00029 |
| LP. | Laboratory Procedure（实验室程序） | LP.7A005, LP.7A004, LP.7M114 |
| SD. | Supplementary Document | SD-11597, SD-M0008/03 |
| Cap. | Capitolato（意大利语：规范） | Cap.9.91220 |

### 文档层级结构
```
SSTS (Supplier System Technical Specification)
├── Product Description sheet (项目总览)
├── Content sheet (内容索引)
├── [嵌入] CTS - Component Technical Specification (零部件技术规范)
│   ├── [嵌入] 产品描述 PPTX（布局图、接头、管径）
│   ├── [嵌入] SVP 验证计划模板 (07740 Annex 2)
│   └── [嵌入] OLE 对象（关键特性表JPG、材料限制PDF、保护帽要求PDF）
├── [嵌入] TDR - Technical Documents Required (交付物清单)
│   ├── [嵌入] ED&D 成本模板
│   ├── [嵌入] SDT 团队名册模板
│   ├── [嵌入] 要求清单（例外事项）模板
│   ├── [嵌入] RASI 职责分配矩阵模板
│   └── [嵌入] BOM 清单模板
└── [嵌入] Deliverables - 交付物时间表
```

### 覆盖规则
- 规范冲突时：CTS 文本 > 引用标准
- 区域差异：CaCl2 测试仅 EMEA 市场（PF.90197 §5.4 标注 "EMEA only"）

## 术语惯例

| Stellantis 用语 | 通用用语 | 说明 |
|----------------|---------|------|
| SSTS | SOR (Statement of Requirements) | 顶层供应商技术规范 |
| CTS | Component Technical Specification | 零部件技术规范 |
| TDR | Technical Documents Required | 交付物清单 |
| SDT | Supplier Development Team | 供应商开发团队 |
| SVP | Supplier Validation Plan | 供应商验证计划（07740 Annex 2） |
| PVP | Process Validation Plan | 过程验证计划 |
| SI Level | Supplier Integration Level | 供应商集成等级（1-5） |
| CCP | Customer Car Profile | 市场故障率指标 |
| QT | Quality Tracking | 质量跟踪 |
| ICP | Initial Customer Perception | 初始客户感知 |
| GML | — | 审批签字 |
| TcAE | Teamcenter Automotive Edition | 3D 数据管理平台 |
| Foglio | Sheet（意大利语） | Excel 模板中的 sheet 名 |

## 交付物命名惯例

TDR 标准交付物编号（15 项）：
1. Native UG/TC capability
2. Co-design cost breakdown (ED&D)
3. Supplier development team (SDT)
4. Components add-on (development cost inclusion)
5. Supplier timing
6. List of exception
7. RASI
8. CAD data for soft tooling prototype
9. Complete 2D Drawings (by TKO)
10. Best practices sharing
11. Product & Process FMEA (by TKO)
12. CAD data at nomination
13. System performance analysis support
14. DV/PV plan
15. SOP assembly plant support

## 客户模板藏匿位置

| 模板 | 藏匿位置 | 层级 |
|------|---------|------|
| ED&D 成本模板 | TDR DOCX 嵌入 | Layer 1 |
| SDT 团队名册 | TDR DOCX 嵌入 | Layer 1 |
| 例外事项清单 | TDR DOCX 嵌入 | Layer 1 |
| RASI 矩阵 | TDR DOCX 嵌入 | Layer 1（非常大，214×85）|
| BOM 清单 | TDR DOCX 嵌入 | Layer 1 |
| SVP 验证计划 | CTS DOCX 嵌入 | Layer 1 |
| 关键产品特性表 | CTS DOCX → OLE → JPG | Layer 1 OLE |
| ELV/REACH 材料限制 | CTS DOCX → OLE → PDF | Layer 1 OLE |
| 保护帽要求 | CTS DOCX → OLE → PDF | Layer 1 OLE |

## 嵌入文件结构树

典型 SSTS 包含 3 层嵌入：
- Layer 0: SSTS → CTS + TDR + Deliverables（3 个 DOCX/XLSX）
- Layer 1: TDR → 5 个 Excel 模板；CTS → PPTX + Excel + 3 个 OLE 对象
- Layer 2: 可能有重复嵌入（如产品描述 PPTX 中嵌入的图纸与原始文件重复）
- PPTX 可能包含 OLE 嵌入的 TIFF 工程图纸

## 处理注意事项

1. **OLE 对象处理**：CTS 中的 OLE 嵌入需要用 olefile 库提取，分 CONTENTS 流和 Ole10Native 流两种情况
2. **Ole10Native 偏移**：TIFF 图纸在 Ole10Native 中有文件路径头信息，需查找 TIFF 签名 `II\x2a\x00` 定位数据起始
3. **意大利语残留**：模板中 sheet 名可能是意大利语（如 Foglio1、Definizione），不可改名
4. **RASI 矩阵极大**：214×85 的矩阵，只需填写对应 SI Level 的列
5. **SVP vs PVP**：可能同时有两个验证计划模板（SVP 在 CTS 嵌入，PVP 可能单独提供）
6. **3D 强制要求**：Stellantis 要求 Native UG + TcAE，不接受其他格式，这是 Deliverable #1
7. **自验证要求**：供应商自验证计划每年重复
8. **碰撞测试**：FMVSS 301 由 Stellantis 负责整车测试，但供应商需配合解决问题
9. **CTS PDF 嵌入不可提取**：CTS 以 PDF 提供时，嵌入附件（DV/PV 模板、FDM、保护帽规格等）均无法提取，需索要原始 Office 版本
10. **CTS vs 性能标准冲突**：同一参数在 CTS 和 PF 标准中可能有不同值，规则：CTS 应用参数 > PF 通用标准，但需双源标注
11. **Product Card 常缺失**：传感器类零件（NTC/WiF）的具体参数由 Product Card 定义，PF/CTS 中仅为示例值
12. **CS.00056 环境分类**：电气/电子零部件需按 CS.00056 进行环境分类（Device type, FC, CI, TC, TN, V, A, SE, IP 等级）
13. **OLE对象图片提取**：部分OLE对象包含JPG图片，需查找JPEG签名`\xff\xd8\xff`定位数据起始
14. **TDR模板处理**：ED&D Cost模板复杂包含多sheet，注意不破坏合并单元格结构
15. **TDR和CTS嵌入分目录提取**：两个 DOCX 嵌入文件均含 `word/embeddings/Microsoft_Excel_Worksheet.xlsx`，必须用独立子目录分别提取，否则 TDR 的 ED&D 模板会被 CTS 的 SVP 模板覆盖
16. **SVP 模板结构（3 sheets）**：`FCA (EN)` / `FCA (EN)(2)` / `FCA (EN)(3)` 分别对应环境+物理、机械+功能、安全+耐久共30个测试项；版本日期 2021-04-19 为旧版，需更新为当前 PF 版本日期
17. **PF.90197 最新版本**：Change Level C，2025-04-03，已 Harmonized（PF.90197<S,E>）；标准作者：Fernando Sada (NA) + Bruno Le Moine (EMEA)
