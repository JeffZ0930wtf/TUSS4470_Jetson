# 实验与分组弹窗实施计划

## 文档说明

本文归档弹窗改进的实施与候选版验收历史。实体字段、归属和接口沿用[实验与数据分组设计](../../superpowers/specs/2026-10-09-experiment-data-grouping-design.md)。当前操作以 [V1.1.2 发布说明](../../release/v1.1.2-release-notes.md)为准。

**目标：** 将新建和编辑集中到按需打开的弹窗，使用者能从对应的下拉框旁直接发起操作。

**方案：** 使用单个原生 HTML `dialog`，按操作显示对应字段；保留采集页的实验和分组选择。相比折叠表单，弹窗能明确区分新建与编辑；相比独立管理页，不需要离开采集页。保持现有仪表风格，并在分组弹窗中明确显示所属实验。

**边界：** 沿用现有 `POST`/`PATCH`，不新增依赖、修改 SQLite 结构、采集协议、固件或运行中任务的绑定。不发布正式版本；实机验收使用独立候选镜像。

### 1. 测试先行

- [x] 在 `packages/usac_runtime/tests/test_web_app.cjs` 覆盖四个入口、空白/回填表单、取消、失败后保留输入、重复提交阻止、保存路由及选择/过期回包保护。运行 `node packages/usac_runtime/tests/test_web_app.cjs`，确认因弹窗尚未打开而失败。

### 2. 实现与文档

- [x] `packages/usac_runtime/src/usac_runtime/web/index.html` 和 `styles.css`：把操作按钮放到对应下拉框旁，弹窗包含标题、字段、取消、保存和可读的错误信息；窄屏能滚动，使用原生焦点管理。
- [x] `packages/usac_runtime/src/usac_runtime/web/app.js`：固定弹窗打开时的编辑目标；新建成功后自动选中新项，编辑成功后保留当前归属。取消不写库；保存中禁止重复提交；失败保留输入；旧响应不能接管新弹窗或选择。中英文均可使用。
- [x] `README.md`、`README.zh-CN.md`：更新实验与分组操作步骤，不更改发布版本。

### 3. 验证

- [x] Node 回归与 `git diff --check` 通过；Windows 聚合门禁 `scripts/test-all.ps1` 通过（261 项 Python 测试、Web 回归、固件编译和安全检查）。模拟器与独立 SQLite 的浏览器验收通过：创建、回填编辑、刷新后持久化、Esc 取消不写入且焦点复位、中英文和 390 px 窄屏。未连接实机或操作正式数据库。

### 4. Jetson 实机验收准备（2026-11-09）

- [x] 基于正式 V1.1.1 镜像替换 `index.html`、`app.js` 和 `styles.css`，构建 ARM64 候选镜像 `tuss4470-acquisition-core:1.1.1-dialogs-e9573e95`（`sha256:eb5e2aae35f8ba3844e992fc4de1f74f83ed3abd7602be097ba435b1c5c60c93`）。Jetson 上正式源码和旧镜像保持原样。
- [x] 用户确认 VPWR 与 S3 复位后，只重建 Core，原 Bridge 容器重连。新版 HTML、资源哈希和 API 验证通过；设备 `NORMAL / IDLE`，正式库中 8 条采集记录、1 个实验、1 个组和 20 个会话与切换前备份逐行一致，spool 待交付为 0。未发起采集、Apply 或刷写。
- [x] 操作者试用后确认可固化；后续筛选实机检查见[历史筛选验收](2026-11-09-experiment-history-filter.md)。
