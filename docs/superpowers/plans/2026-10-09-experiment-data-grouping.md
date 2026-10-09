# 实验数据分组实施计划

## 文档说明

本文把已批准的实验数据组织需求拆成顺序实施、测试与复核任务，适用于主机端 Core/SQLite/Web/离线导出增量。正式契约见 [设计文档](../specs/2026-10-09-experiment-data-grouping-design.md)；不重启 M0–M6，不引入新的硬件门禁。

> **For agentic workers:** 使用 subagent-driven-development；明确边界的实施与测试交给 GPT-6 Luna，关键判断与复核交给 Astra。

**Goal:** 建立实验 → 分组 → 采集记录组织，并保证任务归属冻结与原始数据不变。

**Architecture:** 在现有 SQLite 和 Core 上添加元数据，复用交付、会话、历史及导出路径。

**Tech Stack:** Python 3.12 / SQLite / FastAPI / 原生 JavaScript / ZIP 标准库。

## Global Constraints

- 不改固件、线协议、硬件控制或原始样本，不访问串口、不刷写、不产生 Burst。
- 同一 SQLite 保存元数据；group_id 可空，旧客户端和旧记录兼容。
- 任务启动时冻结组归属，正常/rolling/终态/重放路径一致；幂等交付不覆盖人工归组。
- 不做删除、跨实验移动、预测、充放电关联或无关重构；不添加依赖。
- 不改 v1.0.1 正式标签、环境、数据库、Jetson 部署；先离线验证与 Windows 页面验收。
- 每个任务先写真实行为测试确认 RED，再实现确认 GREEN；关键职责/限制写有效注释。

## Task 1: 数据层与冻结元数据

**Ownership:** `core_store.py`、新增轻量 `experiment_metadata.py`（若字段校验/共享实体需要）、`test_core_store.py` 与新增 `test_experiment_store.py`。

- [ ] 添加实验/组 CRUD 和一致的 ID/字段校验；无删除/组移动。
- [ ] 原位迁移三个 group_id 列及索引，现有库重复打开安全、BLOB 不变。
- [ ] `commit_delivery`、归档、rolling finalize、terminal replay 显式传递冻结归属；交付上下文保存组，幂等分支保留已存组。
- [ ] 帧记录/摘要包含组元数据；历史支持实验/组/未分组及既有分页/会话筛选。
- [ ] 原子批量补归组；提供导出所需的单快照、逐帧读取入口，不另建数据库。
- [ ] 测试旧库迁移、名称校验、筛选分页、批量回滚、SAVE_LAST/replay/重复交付保留手工归属；运行数据层相关回归。
- [ ] 提交任务，复核契约与质量后进入 Task 2。

## Task 2: Core/API 与共享整组导出

**Ownership:** `application.py`、`api.py`、`export_cli.py`、新增 `group_export.py` 与相关 Python 测试。仅为集成必要接口可调整 Task 1 文件。

- [ ] 三类开始请求增加可选 group_id，验证后冻结到会话与交付上下文；采集/会话/详情输出一致元数据，临时帧也保留归属。
- [ ] 按设计增加 CRUD、筛选、批量归组与 ZIP API；接口可在设备断线时使用。
- [ ] 共享 ZIP 导出实现，API 临时文件响应及时关闭；CLI group 子命令不影响现有 show/download。
- [ ] 测试三类任务在后续选择变化下仍用原组、SAVE_* 语义、重启重放、404/422、下载清单和二进制逐字节一致、空组及旧 CLI 兼容。
- [ ] 运行受影响 Python 回归并提交；复核后进入 Task 3。

## Task 3: 双语 Web、说明和最终复核

**Ownership:** `web/app.js`、`web/index.html`、`web/styles.css`、`test_web_app.cjs`、`README.md`、`README.zh-CN.md`、`docs/protocol.md`、本计划/设计与验证记录。

- [ ] 实验/组创建编辑、下一任务归属选择、冻结归属提示；迟到组列表不能污染新选择。
- [ ] 独立历史筛选、批量选择/补归组、整组 ZIP 下载；分页结果隔离、切筛选清空选择，不混用叠加状态。
- [ ] 新 UI 文案完整双语，延续当前样式；不改变工作台分析语义。
- [ ] Node 测试任务请求绑定、切组/历史筛选竞态、批量选择与叠加独立、双语及导出入口。
- [ ] 更新 README 功能/代码地图、操作示例、升级备份和协议的主机 metadata 边界。
- [ ] 完整离线主机/Node 回归、平台门禁、diff/link/范围检查；Astra 复核全分支并修复发现。
- [ ] 记录证据，启动隔离模拟器提供 Windows 页面验收；正式库/Jetson/发布仍不动。

## 起始证据与执行记录

- 基线 `e3ec4966ff9a988c1f504f8ab0f6200732ade428`；主工作区 `.obsidian/` 保留不动。
- 隔离工作树 `.worktrees/experiment-data-grouping`，分支 `codex/experiment-data-grouping`，自有 `.venv`，锁文件离线安装。
- 基线：主机/协议 208 项通过，Node PASS，布局/启动脚本 29 项通过。
- 首次基线命令因临时目录父目录未创建、PATH 选中 WSL Bash 及找不到 uv 失败；仅补齐测试环境后以上验证通过，无源码修改。
