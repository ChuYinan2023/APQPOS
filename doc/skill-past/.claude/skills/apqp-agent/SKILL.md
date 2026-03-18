---
name: apqp-agent
description: "AI驱动的APQP Phase 0（报价前可行性评审），面向汽车Tier 1供应商。4个Agent按阶段串行执行：文档解析→需求分析→评估支持→交付物生成，最终Gate Review。三层HALT保护确保每步用户确认。触发词：报价准备、APQP、RFQ、询价、报价前、Phase 0、客户文件包、TDR、OEM文件。"
---

读取根目录的 `SKILL.md` 并按其指示执行完整工作流。

知识库位于 `references/knowledge/`，共享规则和检查清单位于 `references/`，Agent 定义位于 `references/`，模板资源位于 `assets/`。
