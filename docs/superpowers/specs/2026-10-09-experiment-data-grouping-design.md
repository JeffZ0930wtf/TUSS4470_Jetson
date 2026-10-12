# 实验与数据分组设计

## 文档说明

本文定义超声采集子模块的实验、分组和采集记录组织规则，解决多次对比实验的数据混放问题。适用于 V1.0.1 之后的主机端增量开发；不改变现有固件、线协议、采集时序或保存策略。配套实施文件为 [实施计划](../plans/2026-10-09-experiment-data-grouping.md)。

## 1. 范围和不变量

- 层级为“实验 → 分组 → 采集记录”，同一组可包含多次单次、周期或扫描任务。
- 同一帧最多属于一个组；组始终属于一个实验。实验/组使用系统生成的 32 位小写十六进制 UUID，显示名称不是身份。
- 创建、修改实体时名称去除首尾空白后必须为 1–120 字符。实验可填写备注（最多 2000 字符），组可填写电芯编号（最多 120 字符）和备注（最多 2000 字符）；重复名称允许，一个实验因此可对比不同电芯的组。
- 旧记录及未选择组的新任务为“未分组”。Web 保留明确的未分组选项，旧 API 客户端省略 `group_id` 等价于 `null`。
- 任务开始时冻结 `group_id`，页面之后切换选择只影响下次任务。归属不进入设备配置、profile 哈希、CRC 或线协议。
- 原始帧、样本、事件、配置快照不因分组、重命名、导出或补归组而改变，不复制原始波形。
- 保留 SAVE_NONE、SAVE_ALL、SAVE_LAST 及 SQLite 提交后确认 Bridge 的语义。
- 本轮不做删除实体、跨实验移动组、自动电芯状态识别、充放电匹配或权限系统；不改固件、不访问串口、不刷写、不产生 Burst。

## 2. 数据与迁移

沿用一个 SQLite 数据库，新增 `experiments` 和 `experiment_groups` 元数据表。实验字段为 `experiment_id/name/notes/created_utc_ns/updated_utc_ns`；组字段为 `group_id/experiment_id/name/cell_id/notes/created_utc_ns/updated_utc_ns`。

`captures`、`session_latest_captures`、`delivery_policy_contexts` 分别原位增加可空 `group_id`，增加必要查询索引。迁移重复打开安全，已有行保持 `NULL`，不重建采集 BLOB；首次升级正式库前应停止服务并做 SQLite 一致性备份。

开始任务前验证组存在，并将归属写入持久交付上下文、会话摘要及运行中的会话对象。正常提交显式携带冻结归属；SAVE_LAST 的 rolling 行保留该值，终态归档从该行取值，不能从“当前组”或最近一次设备策略反推。Core 重启和迟到 Bridge 重放也沿用持久归属。

帧已存在或已有终态决策时，重复交付不得改写其组。人工补归组只更新已归档帧的 `group_id`，不改历史任务摘要；后者继续说明任务启动时的原始归属。

## 3. 主机接口

所有接口位于 `/api/v1`；本节元数据、历史和导出接口不要求连接设备，采集开始仍遵守既有设备/配置门禁。返回元数据为 JSON，时间为 UTC 纳秒；可空值用 JSON `null`。

| 方法与路径 | 契约 |
| --- | --- |
| GET /experiments | `{items:[实验...]}` |
| POST /experiments | `{name,notes:""}`，返回创建实体 |
| PATCH /experiments/{experiment_id} | 可更新 name/notes，不改变 ID |
| GET /experiments/{experiment_id}/groups | `{items:[组...]}`，组可带已归档记录数 |
| POST /experiments/{experiment_id}/groups | `{name,cell_id:"",notes:""}`，返回组 |
| PATCH /groups/{group_id} | 可更新 name/cell_id/notes，不改变从属实验 |
| POST /captures/group-assignment | `{capture_ids:[32位hex...],group_id:ID或null}`，返回 `{assigned_count:匹配的不同帧数}`；仅已归档记录 |
| GET /groups/{group_id}/export.zip | 导出该组当前已归档记录 |

批量补归组限 1–500 个不同帧 ID；重复 ID 去重，重复提交同一归属返回相同匹配数。任何帧或目标组不存在则整体失败，不部分成功。`null` 将记录移回未分组。不存在资源返回 404，非法字段/长度/相互冲突筛选返回 422；存储未配置沿用现有不可用响应。新的严格小写 ID 规则仅用于实验/组，既有 capture/session ID 的输入规则保持兼容。

三类开始请求增加 `group_id: string | null = null`。采集结果、会话结果、历史摘要、帧详情和导出 JSON 均提供 `grouping_metadata` 对象，含 `group_id/experiment_id/group_name/experiment_name/cell_id` 五字段，包括临时和滚动帧；未分组时五字段均为 `null`。重命名按当前元数据展示，不改变 ID。历史 GET `/captures` 保持现有 `limit/cursor/session_id`，增加 `experiment_id/group_id/ungrouped`：组和实验同时指定须属于同一实验；`ungrouped=true` 不可同时指定实验/组。游标沿用现有 row_id 升序，同一次翻页沿用筛选条件。

## 4. 整组导出

Web 下载 ZIP，离线命令增加 `usac-export group --sqlite ... --group-id ... --output ...`，共享一份导出实现；保留原有 show/download。

ZIP 包含 `manifest.json`（导出时实验/组元数据、帧 ID 与总数）及每帧 `<capture_id>.usac/.u16le/.json`。文件名只使用系统 ID，不使用用户名称拼路径。帧详情 JSON 保留现有元数据并包含配置、run_plan、事件和分组信息。原始两种二进制文件与数据库 BLOB 逐字节相同。

导出仅包含 ARCHIVE，不包含 SAVE_NONE 临时帧或尚未最终归档的 SAVE_LAST rolling 帧。空组可导出仅有 manifest 的 ZIP。导出读取同一个数据库快照，逐帧写 ZIP，避免将全组波形保存在内存；Web 使用临时文件流式响应，在成功、异常和客户端中断后关闭并删除临时文件，不添加第三方依赖。

## 5. Web 行为

- 在采集区域增加实验/组选择、创建和编辑入口，明确显示“本次任务归属”；任务运行时显示已冻结的归属。
- 选择实验后组列表仅来自该实验，切换实验立即清掉旧组；请求结果须校验仍属于当前实验，迟到成功/失败均不能覆盖新选择。
- 历史区域独立设置“全部/未分组/实验/组”筛选，重置游标后加载。筛选选择不改变下一次采集组；旧分页结果不能混入新筛选。
- 历史支持独立的批量勾选和补归组，不复用波形叠加选择；换筛选时清空批量选择。提供目标组及未分组选项，最多一次 500 帧。
- 提供当前组选定的整组 ZIP 下载，显示组名和记录数；数据只保存一次。
- 不改变现有工作台的窗口、跟随/暂停、最多 20 条、采样基准兼容和归一化规则；不同组可在原有兼容条件下叠加。
- 新文案完整中英双语，用户名称通过文本节点输出，不作为 HTML 注入。

## 6. 验收与交付边界

离线验证覆盖原库升级、CRUD 校验、三类任务冻结归属、SAVE_LAST 终态和重启重放、补归组后的幂等重投递、筛选分页、批量事务与导出字节一致性，以及 Web 切组/筛选竞态和双语流程。保留原有主机与 Node 回归。

实现和审查完成后先提供 Windows 模拟器网页验收；不修改已发布 v1.0.1 标签、不自动迁移正式数据库或部署 Jetson。Jetson 的源码同步、镜像切换及版本发布在本次界面验收后按既有流程执行。
