# Volkswagen AG (VWAG) OEM 知识

## 文档体系

### 文档编号前缀
| 前缀 | 含义 | 示例 |
|------|------|------|
| LAH. | Lastenheft（技术规范） | LAH.3WA.201.B (SyS-LAH 系统规范) |
| LAH.DUM. | Lastenheft Dummy/子规范 | LAH.DUM.201.C (泵性能), LAH.DUM.201.F (传感器) |
| BT-LAH | Basisteil-Lastenheft（采购技术总要求） | BT-LAH (组织与基本条件) |
| Q-LAH | Qualitäts-Lastenheft（质量规范） | Q-LAH LAH.893.910.A (标准软件) |
| NNC. | Nachweis-Norm-Catalogue（试验规范） | NNC.201.021.H (核心试验规范) |
| EP | Erprobungsplan（试验计划） | EP 21xxx.xx |
| TL | Technische Lieferbedingung（技术交付条件） | TL 82253 (管路), TL 82421 (接头) |
| VW | 集团通用标准 | VW 80000 (电气), VW 80106 (连接器), VW 99000 (IP) |

### 文档层级结构
```
BT-LAH (采购技术总要求 — 最高级别)
├── SyS-LAH (系统技术规范 — 零部件级)
│   ├── LAH.DUM.xxx.C/E/F/G (性能子规范 — 按组件)
│   ├── LAH.DUM.xxx.AB (特性值模板 — 供应商填写)
│   └── NNC.xxx.xxx.H (试验规范 — 大量引用)
├── EP 21xxx (试验计划)
├── TL xxxxx (技术交付条件)
└── TDR (交付物清单 — 定义供应商需提交的文件)
```

### 覆盖规则
- BT-LAH 为最高级别，所有子规范不得与其冲突
- SyS-LAH 为项目级规范，针对具体零部件系统
- LAH.DUM.xxx 为组件级子规范，补充 SyS-LAH 中未详述的内容
- 文档版本标记为 `<Kx>` 格式（如 K6 = 第6版）
- Konzernversion = 集团版本（适用 VW/Audi/Porsche 等全品牌）
- 品牌差异在文档中通过品牌标注区分（如油位传感器电阻值 VW vs Audi/Porsche 不同）

## 术语惯例

| VW 术语（德文） | 英文 | 通用用语 |
|----------------|------|---------|
| Systemlastenheft (SyS-LAH) | System Performance Specification | 系统技术规范 |
| Basisteil-Lastenheft (BT-LAH) | Basic Part Specification | 采购技术总要求 |
| Spezifikation | Specification / Characteristic Values | 特性值模板 |
| Freigabereport | Release Report | 释放报告 |
| Fördereinheit | Fuel Supply Module ASSY | 供油模块总成 |
| Kraftstoffpumpenelektronik (KPE) | Fuel Pump Electronics | 燃油泵电子控制单元 |
| Tankgeber | Fuel Level Sensor | 油位传感器 |
| Saugstrahlpumpe | Suction Jet Pump | 射流泵 |
| Druckbegrenzungsventil | Pressure Limitation Valve | 压力限制阀 |
| Druckhalteventil | Pressure Holding Valve | 保压阀 |
| Leckage-Schutzventile | Leakage Protection Valves | 泄漏保护阀 |
| Absaugkäfig | Extraction Strainer | 抽吸滤网 |
| Beschaffung Neuteile (BN) | New Parts Procurement | 新零件采购部门 |
| VOBES | Electrical Interface Description | 电气接口描述表 |
| Nachweis | Evidence / Verification | 验证证据 |
| Entfall | Deleted / Not Applicable | 已删除/不适用 |

## 交付物命名惯例

VW 文档中交付物通过 "Vom AG erwarteter Nachweis"（客户期望的验证证据）列定义，分为：
- **konstruktiver Nachweis** = 设计验证（图纸、分析、计算）
- **versuchstechnischer Nachweis** = 试验验证（测试报告）

典型交付物编号无统一前缀，以文档类型命名：Versuchsbericht（试验报告）、Spezifikation（特性值表）、DIA（设计影响分析）等。

## 客户模板藏匿位置

本次项目仅收到 PDF 格式 SyS-LAH，无嵌入文件。VW 模板通常需要单独索取：
- LAH.DUM.201.AB 特性值模板 → 向 VW 技术部门索取
- DIA 模板 → 向 VW 功能安全部门索取
- Freigabereport Excel → 向 VW 索取
- VOBES 接口描述表 → 向 VW 采购部门索取
- HIS 问卷 → 从 automotive-his.de 自行下载

## 嵌入文件结构树

VW 的 SyS-LAH 为 PDF 格式（非 Office），不含嵌入文件。与 Stellantis 的多层嵌入 XLSX 风格不同。

## 处理注意事项

1. **BT-LAH 是关键依赖** — VW 的 SyS-LAH 几乎每节都引用 BT-LAH，缺失则大量技术要求无法确认
2. **Konzernversion 品牌差异** — 集团版本中同一参数可能有 VW/Audi/Porsche 不同值，需注意品牌标注
3. **PDF 格式为主** — VW 规范多为 PDF，不像 Stellantis 使用 XLSX 嵌入体系
4. **德文/英文混合** — 主体英文但表头和注释常为德文，需双语处理能力
5. **文档版本 Kx** — 注意版本号格式 `<Kx>`，K6 代表第6个主版本
6. **EU7 更新** — 2021年后的文档可能含 EU7 排放法规更新内容（功能安全新增章节等）
7. **联系部门** — 采购部门代号如 BN-F/2（新零件采购燃油系统）、BX3/2（量产采购）
