# 组合经验：Stellantis × Fuel Line

## 项目历史摘要

- 累计处理次数：4
- 最近一次处理：2026-03-10

## 文档组合模式

Stellantis 发 Fuel Line 类 RFQ 时，文件包典型组成：

```
客户文件包/
├── SSTS {项目代号} Fuel line.xlsx          ← 顶层（含嵌入 CTS + TDR + Deliverables）
├── PF.90197.pdf                            ← 主性能标准（28页）
├── PF.90068.pdf                            ← DEF Line 性能标准（如含 DEF 管路）
├── PF.90298_QC 接头要求.pdf                ← QC 接头标准
├── {项目代号} Fuel line damper description.pptx  ← 产品描述（含 OLE 图纸）
└── STLA-DVPR模板.xlsx                      ← PVP 模板（可能单独提供）
```

SSTS 嵌入层级：
- Layer 0: CTS(.docx) + TDR(.docx) + Deliverables(.xlsx)
- Layer 1/TDR: 5 个 Excel 模板（ED&D/SDT/例外/RASI/BOM）
- Layer 1/CTS: PPTX(产品描述) + Excel(SVP) + 3 个 OLE(JPG特性表 + PDF材料限制 + PDF保护帽)

## 典型例外项

| 例外项 | 频率 | 典型处置 |
|--------|------|---------|
| UG/Teamcenter 3D 能力 | 常见 | 必须有，否则无法参与 |
| 金属管内镀镍 | 常见 | 外协电镀或采购预镀镍管材 |
| 指定阻尼器供应商 | 常见 | 需提前确认供应商配合意愿 |
| 测试能力（脉冲/振动/渗透/腐蚀） | 常见 | 委外第三方实验室（TÜV/SGS） |
| CDS 模板未随 RFQ 提供 | 常见 | 需单独向客户索要 |
| 车辆开发计划未提供 | 常见 | 需单独向客户索要 VP/PS/SOP 日期 |

## 成本参考范围

（本次为首次处理，暂无脱敏参考数据）

- 材料占比预估：35-40%
- 开发费用含：模具 + DV/PV 委外测试 + 工程时间
- 测试委外占开发费用比例较大（脉冲/振动/腐蚀/渗透为长周期测试）

## 历史踩坑记录

1. **OLE 嵌入提取**：CTS 中的 OLE 对象不能直接解压，需用 olefile 库的 `\x01Ole10Native` 流或 `CONTENTS` 流提取。TIFF 图纸在 Ole10Native 中有文件路径头信息，需查找签名定位。
2. **RASI 矩阵巨大**：214×85 的矩阵，openpyxl 读取时可能有 header/footer 警告，不影响数据。只需填写对应 SI Level 的列。
3. **Layer 2 重复**：产品描述 PPTX 中可能嵌入与原始文件相同的图纸，Layer 2 提取前应检查是否重复。
4. **SVP 格式历史**：SVP 模板标题仍写 "FCA GROUP PURCHASING"（历史遗留），实际为 Stellantis 通用格式。
5. **CaCl2 仅 EMEA**：PF.90197 §5.4 明确标注 "EMEA only"，需确认项目目标市场后再决定是否纳入测试计划。
6. **OLE对象图片**：部分OLE对象包含JPG图片，需查找JPEG签名`\xff\xd8\xff`定位数据起始
7. **TDR模板ED&D**：复杂模板包含多sheet，openpyxl处理时注意合并单元格
8. **虚拟数据处理**：RFQ缺失CDS/开发计划时可虚拟填充，但需标注仅供流程演示
9. **TDR 和 CTS 嵌入路径冲突**：两者都嵌入到同一目录（`word/embeddings/`），提取时必须用独立子目录（`_tdr_raw/`、`_cts_raw/`）分开，否则同名文件互相覆盖（ED&D模板会被SVP模板覆盖）
10. **Layer 2/3 重复检测**：KP1 项目中 L2_CTS_产品描述.pptx 与 KP1_Damper_PPTX 各自嵌入一个不同的 TIFF 图纸（大小相差3字节），非重复，需分别提取
11. **DEF 管路同时存在**：KP1 含 DEF Line Assy — Middle，受 PF.90068 独立约束（37页），需单独关注材料/加热/尿素兼容性要求
12. **SVP 模板版本**：Template sheet 数量为 3（FCA (EN) / FCA (EN)(2) / FCA (EN)(3)），分别覆盖环境+物理、机械+功能、安全+耐久，共30个测试项，对应 PF.90197 Annex A 全部条目
13. **PF.90197 版本更新**：2025-04-03 发布 Change Level C（Harmonized），标准编号为 PF.90197<S,E>；原模板内嵌版本日期为 2021-04-19，需更新
