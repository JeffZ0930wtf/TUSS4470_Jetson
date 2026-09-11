# Windows V1 部署与运行

## 文档说明

本文档说明 V1 超声采集子模块在 Windows 上的服务边界、启动方式和数据目录，解决 Core、Bridge、模拟器与真实 USB CDC 设备如何组合的问题。它适用于本机实验与功能验证；固件烧写和外部 7 V 供电仍受独立人工安全门禁约束。

## 运行结构

- Core 提供配置、采集任务、SQLite、REST 和 Web 页面。
- Bridge 独占 `COMx`，完成 USB CDC 字节流、协议校验与待交付 spool。
- 真实硬件模式下 Core 使用 `--backend bridge`，Bridge 主动连接 Core 的 `127.0.0.1:8765`。
- 模拟器模式只用于无硬件功能检查，不能作为真实采集依据。

默认宿主数据目录为：

- SQLite：`D:/Desktop/TUSS4470_data/core/acquisition.sqlite3`
- Bridge spool：`D:/Desktop/TUSS4470_data/bridge/spool`

容器内路径分别为 `/var/lib/usac/database` 和 `/var/lib/usac/spool`。宿主路径由 `USAC_CORE_DATA_DIR` 与 `USAC_BRIDGE_SPOOL_DIR` 控制，不写入源码。

## 启动真实服务

先激活仓库虚拟环境，并确认 LaunchPad 对应的 `COMx`。外部 7 V、跳线、极性和限流必须人工确认后，才可给 Bridge 传入供电确认参数。

Core 可直接在 Windows 虚拟环境中运行：

```powershell
usac-core --backend bridge --host 127.0.0.1 --port 8000 --bridge-host 127.0.0.1 --bridge-port 8765 --database D:/Desktop/TUSS4470_data/core/acquisition.sqlite3 --host-database-path D:/Desktop/TUSS4470_data/core/acquisition.sqlite3
```

另开一个已激活同一虚拟环境的终端运行 Bridge：

```powershell
usac-bridge --config config/windows.example.toml --core-host 127.0.0.1 --core-port 8765 --confirm-external-vpwr-7v
```

Web/API 地址为 `http://127.0.0.1:8000/`。停止时先停止采集任务，再用 `Ctrl+C` 结束 Bridge 和 Core。

## 模拟器

不连接硬件、只检查页面或 REST 时运行：

```powershell
usac-core --backend simulator --host 127.0.0.1 --port 8000 --database D:/Desktop/TUSS4470_data/core/simulator.sqlite3 --host-database-path D:/Desktop/TUSS4470_data/core/simulator.sqlite3
```

模拟器不需要 Bridge，也不得被描述为真实波形采集。

## 固件构建与刷写边界

`scripts/build-firmware.ps1` 只编译正式固件，不访问串口或硬件。`scripts/flash-firmware.ps1` 只有在外部 VPWR 已物理关闭，并显式传入 `-ExternalVpwrOffConfirmed` 后才允许调用 TI DSLite；刷写脚本不会发送采集命令或产生 Burst。
