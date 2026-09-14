# TUSS4470 超声采集子模块 V1

[English](README.md) | [简体中文](README.zh-CN.md)

## 文档说明

本文档是 TUSS4470 独立超声采集子模块 V1.0.1 的中文操作与开发入口，
用于帮助实验人员、上位机开发人员和固件开发人员快速判断系统边界、
启动方式、数据位置，以及每项功能对应的维护代码。协议细节、平台部署、
发布证据和历史开发记录由文末链接的正式文档分别维护。

V1.0.1 增加了 Windows 远程拉起 Jetson 和 Jetson 本机一键启动入口，
默认使用从正式 V1.0.1 源码构建的 `tuss4470-acquisition-core:1.0.1`
镜像。采集运行逻辑和固件没有因此改变，具体发布边界见
[V1.0.1 发布说明](docs/release/v1.0.1-release-notes.md)。

本模块负责配置 TUSS4470、安全执行有界超声采集，并输出未经插值或改写的
原始包络样本及完整采集元数据。峰值、TOF、能量等特征计算以及 SOC/SOH
预测属于未来 BMS 集成层，不属于本模块 V1 的职责。

## 建议的交接阅读顺序

1. 阅读本文档，理解模块边界、组成、运行和数据位置。
2. 阅读 [V1.0.1 发布说明](docs/release/v1.0.1-release-notes.md)和
   [V1 已知限制](docs/release/v1.0.0-known-limitations.md)，确认当前版本可以
   声明和不能声明的能力。
3. 根据使用平台阅读 [Windows 部署](docs/deployment/windows.md)或
   [Jetson 部署](docs/deployment/jetson.md)。
4. 开发通信或上位机功能前阅读 [协议与参数契约](docs/protocol.md)。
5. 先使用模拟器熟悉配置、采集、历史和导出，再接入真实硬件。

`docs/archive/pre-v1/` 保存 M1-M6 的设计历史、故障调查和验收证据，主要用于
追溯原因，不是理解当前 V1.0.1 代码的首要入口。

## 系统组成

- **MSP430 固件**：完成复位安全状态、TUSS4470 配置、有限 Burst、ADC/DMA
  采集、恰好 2048 个未经修改的 `uint16` 样本、周期调度、同步输入、事件、
  STOP 和租约到期处理。
- **Bridge**：独占 USB CDC 设备，校验和转发线协议，处理断线重连，并在
  Core 确认 SQLite 提交前保存 pending 数据。
- **Core**：负责参数策略、采集会话、SQLite 持久化、REST API、CLI 和
  中英文网页工作台。
- **网页工作台**：支持原始/归一化显示、连续样本窗口以及最多 20 条相容
  波形叠加，不修改数据库中的原始样本。

典型数据链路为：

```text
网页 / usac-cli
      │ REST
      ▼
     Core ── SQLite
      │ TCP
      ▼
    Bridge ── pending spool
      │ USB CDC
      ▼
 MSP430 固件 ── TUSS4470 ── TX/RX 换能片
```

## 功能与代码位置对应表

| 功能 | 当前维护位置 |
|---|---|
| Windows 远程拉起 Jetson | [`scripts/start-jetson.ps1`](scripts/start-jetson.ps1) |
| Jetson 启动 Core/Bridge | [`scripts/start-jetson.sh`](scripts/start-jetson.sh) |
| 容器部署 | [`deploy/compose.jetson.yaml`](deploy/compose.jetson.yaml)、[`deploy/Dockerfile.core`](deploy/Dockerfile.core) |
| Core 进程入口 | [`core_server.py`](packages/usac_runtime/src/usac_runtime/core_server.py) |
| REST API 路由 | [`api.py`](packages/usac_runtime/src/usac_runtime/api.py) |
| 采集编排与运行状态 | [`application.py`](packages/usac_runtime/src/usac_runtime/application.py) |
| 参数校验与应用 | [`parameter_service.py`](packages/usac_runtime/src/usac_runtime/parameter_service.py) |
| 周期采集、Sweep 与租约 | [`run_plan.py`](packages/usac_runtime/src/usac_runtime/run_plan.py)、[`periodic_lease.py`](packages/usac_runtime/src/usac_runtime/periodic_lease.py) |
| Core SQLite 持久化 | [`core_store.py`](packages/usac_runtime/src/usac_runtime/core_store.py) |
| Bridge 入口与设备会话 | [`bridge_cli.py`](packages/usac_runtime/src/usac_runtime/bridge_cli.py)、[`bridge_device_client.py`](packages/usac_runtime/src/usac_runtime/bridge_device_client.py) |
| Bridge 转发、重连和 pending spool | [`bridge_session.py`](packages/usac_runtime/src/usac_runtime/bridge_session.py)、[`reconnect.py`](packages/usac_runtime/src/usac_runtime/reconnect.py)、[`spool.py`](packages/usac_runtime/src/usac_runtime/spool.py) |
| REST CLI 与 SQLite 离线导出 | [`client_cli.py`](packages/usac_runtime/src/usac_runtime/client_cli.py)、[`export_cli.py`](packages/usac_runtime/src/usac_runtime/export_cli.py) |
| 网页结构、交互和样式 | [`index.html`](packages/usac_runtime/src/usac_runtime/web/index.html)、[`app.js`](packages/usac_runtime/src/usac_runtime/web/app.js)、[`styles.css`](packages/usac_runtime/src/usac_runtime/web/styles.css) |
| 线协议消息与字节流解析 | [`packages/usac_protocol`](packages/usac_protocol/src/usac_protocol)、[`docs/protocol.md`](docs/protocol.md) |
| 参数名称、范围和依赖关系 | [`tuss4470-parameters-v1.yaml`](protocol/schema/tuss4470-parameters-v1.yaml) |
| 固件入口与命令状态机 | [`main.c`](firmware/src/main.c)、[`usac_firmware_app.c`](firmware/src/usac_firmware_app.c) |
| TUSS4470 寄存器配置 | [`tuss4470_configurator.c`](firmware/src/tuss4470_configurator.c)、[`tuss4470_profile.c`](firmware/src/tuss4470_profile.c) |
| ADC/DMA 采集与 MSP430 硬件绑定 | [`usac_capture.c`](firmware/src/usac_capture.c)、[`usac_acquisition_platform_msp430.c`](firmware/src/usac_acquisition_platform_msp430.c) |
| Burst 安全计划与采集调度 | [`usac_burst_plan.c`](firmware/src/usac_burst_plan.c)、[`usac_capture_schedule.c`](firmware/src/usac_capture_schedule.c) |
| 固件构建、刷写和完整门禁 | [`build-firmware.ps1`](scripts/build-firmware.ps1)、[`flash-firmware.ps1`](scripts/flash-firmware.ps1)、[`test-all.ps1`](scripts/test-all.ps1)、[`test-all.sh`](scripts/test-all.sh) |

## 对外命令

V1 安装后只提供四个正式命令：

- `usac-core`：REST、网页和采集 Core。真实硬件使用 `--backend bridge`，
  离线界面/API 验证使用 `--backend simulator`。
- `usac-bridge`：长期运行的 USB CDC 到 Core 桥接服务，参数直接传给命令，
  不存在 `serve` 子命令。
- `usac-cli`：用于状态、配置、采集、会话、历史和样本下载的 REST 客户端。
- `usac-export`：不启动 Core，直接从 SQLite 查看记录并导出完整 `.usac`、
  `.u16le` 和 `.json` 文件。

## 开发环境与验证

每个检出目录使用自己的仓库内 `.venv`。环境初始化、Windows/Jetson
测试分工和固件检查职责统一由 [CONTRIBUTING.md](CONTRIBUTING.md) 维护。
完整离线门禁不会打开串口、刷写固件或产生 Burst。

## 固件构建与刷写

构建唯一正式固件：

```powershell
./scripts/build-firmware.ps1
```

产物位置：

```text
firmware/build/release/tuss4470-acquisition-fw-0.2.0.2.elf
```

构建不会访问硬件。刷写必须单独执行：

```powershell
./scripts/flash-firmware.ps1 -ExternalVpwrOffConfirmed
```

只有在物理断开外部 VPWR 后才能传入该确认参数。刷写脚本调用 TI DSLite，
不发送串口命令，也不能请求 Burst。

## Windows 使用

在 Windows 操作 Jetson 实机时，先确认外部 VPWR 为 7 V，并在供电稳定后按
一次 S3 `RST`：

```powershell
.\scripts\start-jetson.ps1 -ExternalVpwr7VConfirmed
```

脚本会通过 SSH 调用 Jetson 启动脚本，复用或创建本地隧道，并打开
`http://127.0.0.1:18080/`。它不会自动应用配置、采集或产生 Burst。

Windows 本机 Core/Bridge 和无硬件模拟器仍可通过命令行运行。完整命令、
本机网页/API 地址、数据路径和停止方法统一见
[Windows 部署](docs/deployment/windows.md)。模拟器不会访问 USB/SPI、
刷写固件或产生 Burst。

## Jetson 使用

Jetson 通过稳定的 `/dev/serial/by-id/...` 身份选择 LaunchPad，不应依赖可能
变化的 `/dev/ttyACM*` 序号。确认 7 V 并按过 S3 `RST` 后执行：

```sh
./scripts/start-jetson.sh --confirm-external-vpwr-7v
```

有图形桌面时脚本尝试打开 Jetson 浏览器；纯 SSH 会话则打印本地网址。
宿主机/容器路径、停止方式和手动 Compose 命令见
[Jetson 部署](docs/deployment/jetson.md)。

## 网页工作台语义

- 横轴始终是原始样本序号；V1 不把它表示为经过校准的物理时间。
- 原始模式显示数据库中的 ADC 码值。归一化模式对每条完整 2048 点波形
  使用自身最小值和最大值独立映射到 `0–1`；常量波形显示为零。两种显示
  都不会修改原始样本。
- 只有 `sample_interval_ticks`、`pretrigger_count` 和 `sample_count`
  三项完全相同的波形才能叠加；V1 不进行对齐或插值。
- 同时最多选择 20 个不同的 capture ID。主波形、已隐藏但仍选择的波形、
  以及正在加载的已选择波形都占用名额；只有移除后才释放。
- 查看历史记录只会暂停画布“跟随最新”，不会暂停或停止采集。恢复跟随
  后，画布会以最新帧重新建立显示集合。
- 画布中可见的波形可能仍是临时帧或滚动最新帧；“可见”不等于已经作为
  归档记录持久保存到 SQLite。

## 数据位置和离线导出

运行数据不写入源码仓库：

- Windows SQLite：`D:/Desktop/TUSS4470_data/core/acquisition.sqlite3`
- Windows Bridge spool：`D:/Desktop/TUSS4470_data/bridge/spool`
- Jetson SQLite 宿主目录：`/var/lib/tuss4470/core`
- Jetson Bridge spool 宿主目录：`/var/lib/tuss4470/bridge/spool`

可以使用 `USAC_CORE_DATA_DIR`、`USAC_BRIDGE_SPOOL_DIR` 和
`USAC_SERIAL_DEVICE` 修改部署路径。离线导出的完整命令见 Windows 部署
指南；`usac-export` 可在 Core 停止时直接读取已提交的 SQLite 数据。

## 硬件安全边界

- 已验收拓扑：J2=TX、J3=RX、R12 已移除、J1=8 nF、J4=6.8 nF。
- 发射要求 Standard power、外部 VPWR 约 7.0 V、极性和限流正确、内部
  VDRV 5 V、SPI 回读一致、`VDRV_READY`、无 TUSS 故障、安全配置已应用，
  并取得明确操作授权。
- 仅 USB 供电只用于开发和无 Burst 检查，不能宣称设备已具备发射条件。
- V1 只允许有限脉冲和带租约的周期任务，不允许无边界保持驱动开启。
- 页面中的 `VDRV_READY` 是固件保存的状态，不是持续测量的 VPWR 电压；
  外部 7 V 变化后仍需按操作流程重新确认和复位。
- 不要把采集数据、spool/SQLite、凭据、固件二进制或大型仪器导出提交到
  Git 仓库。

## 正式文档入口

- [协议与参数契约](docs/protocol.md)
- [Windows 部署](docs/deployment/windows.md)
- [Jetson 部署](docs/deployment/jetson.md)
- [V1.0.1 发布说明](docs/release/v1.0.1-release-notes.md)
- [V1 运行基线验收](docs/release/v1.0.0-acceptance.md)
- [V1 已知限制](docs/release/v1.0.0-known-limitations.md)
- [Pre-V1 历史归档](docs/archive/pre-v1/README.md)
- [项目开发规范](CONTRIBUTING.md)
