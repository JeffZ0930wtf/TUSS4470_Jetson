# 已保存记录的实验与分组筛选

## 文档说明

本文归档主机 Web 历史区的两级筛选方案和验收记录。接口、数据结构及归属规则沿用[实验与数据分组设计](../../superpowers/specs/2026-10-09-experiment-data-grouping-design.md)。先完成 Windows 预览，再经用户确认切换 Jetson 候选镜像；当前操作以 [V1.1.2 发布说明](../../release/v1.1.2-release-notes.md)为准。

- [x] 先在 `packages/usac_runtime/tests/test_web_app.cjs` 验证页面仅有「全部记录」和「按实验筛选」，实验选择后默认查全部分组；点击所属组追加 `group_id`，换实验重置组筛选、分页和归组勾选，旧响应不得覆盖新筛选。
- [x] 在 `packages/usac_runtime/src/usac_runtime/web/{index.html,app.js,styles.css}` 实现上述交互，保留中英文、未分组旧记录、批量归组和独立的采集分组。
- [x] 更新中英文 README 与分组设计；Windows 聚合门禁通过。浏览器使用独立模拟库验证全部 5 条（含未分组）、实验内 3 条、指定组 2 条和另一个实验 1 条。
- [x] Jetson 仅切换 Core 至 `tuss4470-acquisition-core:1.1.1-history-161526dd`。实际页面验收全部 13 条、两实验各 2 和 11 条及组内筛选；数据库与切换前快照逐行一致，未改变采集绑定、触发采集或重新刷写。
