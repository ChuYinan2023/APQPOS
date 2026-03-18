# Automotive APQP Agent

> AI Agent framework for automotive parts supplier APQP management.
> 面向汽车零部件厂商的 APQP 全流程 AI Agent 框架。

## 当前阶段

**聚焦：报价前阶段（Pre-Quotation Phase）**

从 RFQ 接收到报价包输出的完整 AI 辅助流程。核心定位：**帮人整理信息、降低遗漏，不替人做工程判断**。

## 架构

4 个工具型 Agent 串行执行，由 `main-flow.md` 编排，三层 HALT 保护确保每步用户确认：

```
📋 文档解析 → 🔍 需求分析 → 📊 评估支持 → 📝 交付物生成 → Gate Review
     │              │              │              │
     ▼              ▼              ▼              ▼
  README.md    缺失项/特性/    例外事项/      全套交付物/
  嵌入文件      质量目标       风险提示       一致性检查
  文件清单                                    知识回写
```

| Agent | 做什么 | 不做什么 |
|-------|--------|---------|
| 📋 文档解析 | 读文件、提嵌入、识别OEM、分类、提数据 | — |
| 🔍 需求分析 | 完整性检查、特性提取、质量目标 | — |
| 📊 评估支持 | 能力对比、历史经验匹配、风险汇总 | 不做工程判断 |
| 📝 交付物生成 | 按模板生成文档、一致性检查、知识回写 | 不做工程判断 |

## 路线图

- [ ] Phase 0：报价前阶段（Pre-Quotation） ← **当前**
- [ ] Phase 1：产品设计开发（Product Design & Development）
- [ ] Phase 2：过程设计开发（Process Design & Development）
- [ ] Phase 3：产品和过程验证（Product & Process Validation）
- [ ] Phase 4：量产反馈与持续改进（Launch & Continuous Improvement）

## 项目结构

```
automotive-apqp-agent/
├── .claude/skills/apqp-agent/   # 入口 Skill（触发主工作流）
├── src/
│   ├── agents/                  # 4 个 Agent 定义（.md）
│   │   ├── doc-parser.md        #   📋 文档解析
│   │   ├── req-analyzer.md      #   🔍 需求分析
│   │   ├── assessment.md        #   📊 评估支持
│   │   └── deliverable-gen.md   #   📝 交付物生成
│   ├── workflows/               # 工作流
│   │   └── main-flow.md         #   主流程（串联4个Agent + Gate Review）
│   ├── rules/                   # 共享规则
│   │   ├── excel-style.md       #   Excel 生成样式规范
│   │   ├── template-priority.md #   模板优先级铁律
│   │   ├── deliverable-order.md #   交付物依赖顺序
│   │   └── knowledge-writeback.md # 知识回写规则
│   ├── checklist/               # 独立检查清单
│   │   ├── final-consistency.md #   最终一致性检查（8项）
│   │   └── gate-review.md       #   Gate Review 检查项
│   ├── templates/               # 文档模板
│   └── knowledge/               # 领域知识库
│       ├── oem/                 #   OEM 知识（可回写积累）
│       ├── component/           #   零部件类型知识（可回写积累）
│       ├── combo/               #   OEM × 零件 组合经验（可回写积累）
│       └── standards/           #   行业标准摘要
├── docs/                        # 项目文档
│   ├── architecture/            #   架构设计
│   ├── research/                #   调研与参考
│   └── decisions/               #   架构决策记录（ADR）
└── README.md
```

## 框架参考

本项目架构借鉴 [BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) 的 Agent/Workflow 设计模式，结合 APQP 汽车行业规范（IATF 16949、AIAG APQP Manual）进行垂直化设计。

## License

MIT
