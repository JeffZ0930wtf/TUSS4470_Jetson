# Jetson V1 部署与运行

## 文档说明

本文档说明 V1 超声采集子模块在 Jetson 宿主机和容器内的设备、网络与持久目录边界，解决“哪些配置属于宿主机、哪些路径属于容器”的问题，并记录当前 V1.1.1 主机 UI 缓存修复状态及 V1.1.0 历史实机验证。它适用于 V1 的部署、启动、停止和真实设备运行；协议与安全边界分别以 `docs/protocol.md` 和 V1 已知限制为准。完整真实证据不放入 Git。

## V1.1.1 主机 UI 缓存修复状态

V1.1.1 修复浏览器静态资源混版：API 进程启动时固定 HTML、JavaScript 与
CSS 内容快照，HTML 用 JavaScript/CSS 的完整 SHA-256 生成资源 URL，并对三类
响应设置 `Cache-Control: no-cache`。需要更新资产时须重启 API 进程。该修复不改
实验分组、固件或协议；本次部署未执行采集、配置 Apply 或固件刷写。

Jetson ARM64 已部署并验证镜像 `tuss4470-acquisition-core:1.1.1`，镜像 ID 为
`sha256:acbc213fd0ae3ded2e15196995567e544f576d99efc3516d1a80fd804b2d1a7d`，
OCI revision 为候选源码 `7ab2b19c460b8f6f11ab504cf0ee7fd56d222ad5`。Core 与
Bridge 当前均运行该镜像。备份持久目录前曾停止服务，随后重新创建并启动；启动器使用
`up -d --no-build`，再次启动时要求 Jetson 上已有该镜像。部署/测试范围和缓存
验证细节见 [V1.1.1 发布说明](../release/v1.1.1-release-notes.md)。

## V1.1.0 源码、镜像与实机验证（历史）

不可变源码标签 `v1.1.0` 指向 `7db75e05875848fd02d188ba5196c2c1e06b5f5b`。
Jetson ARM64 镜像 `tuss4470-acquisition-core:1.1.0`（镜像 ID
`sha256:c4eef7032a72d5e359b77bea2afc9507166b4e853506957beab7e350a269abf3`）
由该源码修订构建；该单帧验收期间 Core 与 Bridge 均使用此镜像（不代表当前
V1.1.1 镜像或服务状态）。当时的 Compose/启动器默认值为 1.1.0；V1.1.1 使用
独立镜像标签和候选源码修订，没有改写该标签或已验收镜像。

2026-10-13 在备份 Core 和 Bridge 持久目录后完成数据库升级及一次经授权的
Pulse=1 单次采集。新增记录绑定实验组；既有 7 条归档记录及原始帧字节保持
不变，库存为 8 条（1 条分组、7 条未分组）；新增帧的筛选和 ZIP 导出核验通过，
Bridge pending=0，最终设备状态为 `NORMAL / IDLE`。该实机证据仅覆盖单帧采集、
分组、筛选和 ZIP；不覆盖周期/扫描矩阵、人工浏览器验收、时序校准或长期可靠性。
完整摘要见[历史 V1.1.0 发布说明](../release/v1.1.0-release-notes.md)，机器原件位于
`D:/Desktop/TUSS4470_data/release/v1.1.0/jetson-20261013/`。

## 宿主机与容器边界

| 项目 | Jetson 宿主机 | 容器内 |
|---|---|---|
| LaunchPad USB CDC | `/dev/ttyACM0` 或 udev 稳定别名 | bridge：`/dev/tuss4470` |
| bridge spool | `/var/lib/tuss4470/bridge/spool` | bridge：`/var/lib/usac/spool` |
| core SQLite | `/var/lib/tuss4470/core` | core：`/var/lib/usac/database` |
| bridge→core | Compose 私有网络 | `core:8765` |
| Web/API | 宿主回环 | core：`0.0.0.0:8000` |

bridge 和 core 不共享可写目录。bridge 只拥有串口、协议校验和 pending spool；core 拥有配置策略、SQLite、REST、CLI 与 Web。

## 稳定设备名

不得根据 `/dev/ttyACM0`、`ttyACM1` 或 `ttyACM2` 的编号推断哪个端口是采集
固件。实机重启已经观察到 `MSP430-USB Example` 从 `ttyACM2` 变为
`ttyACM0`，而两个 `MSP Tools Driver` 调试端口占用其余编号。必须同时核对
产品名和本板 32 位小写十六进制序列号。

先用 `udevadm info --attribute-walk --name=/dev/ttyACM0` 核对实际设备的 `idVendor` 和 32 位小写十六进制 USB 序列号。随后可创建 `/etc/udev/rules.d/99-tuss4470.rules`：

```udev
SUBSYSTEM=="tty", ATTRS{idVendor}=="2047", ATTRS{idProduct}=="0300", ATTRS{serial}=="替换为本板32位小写序列号", SYMLINK+="tuss4470", GROUP="dialout", MODE="0660"
```

不得照抄占位序列号。规则加载后重新插拔设备，并确认 `/dev/tuss4470` 指向预期的 `/dev/ttyACM*`。

不创建 udev 别名时，也可把 Compose 变量直接设为经过核对的 `by-id` 路径：

```sh
export USAC_SERIAL_DEVICE=/dev/serial/by-id/usb-Texas_Instruments_MSP430-USB_Example_<本板32位小写十六进制序列号>-if00
docker compose -f deploy/compose.jetson.yaml up -d --force-recreate bridge
```

`devices` 映射在容器创建时确定。修改变量或设备枚举顺序后，仅重启旧容器不会
更新映射，必须重建 bridge 容器；core 和两个持久目录不需要因此重建或删除。

## 启动前提

1. 宿主目录已创建且运行用户可写。
2. J2=TX、J3=RX、R12 已移除，J1=8 nF、J4=6.8 nF。
3. VPWR 7 V 的极性、限流和实测电压已人工确认，并在供电稳定后按过一次 S3 `RST`；仅 USB 供电时不得传入 `--confirm-external-vpwr-7v`。
4. `USAC_SERIAL_DEVICE` 指向实际的 `/dev/ttyACM*` 或 `/dev/tuss4470`。

`compose.jetson.yaml` 中的确认参数只解除主机侧启动门禁，并不会主动产生 Burst；实际激励仍需经过配置读回、VDRV_READY、故障状态和固件安全状态机。

## Jetson 本机一键启动

启动脚本当前默认选择已部署验证的 `tuss4470-acquisition-core:1.1.1`。启动脚本
执行 `up -d --no-build`，不会自动构建，镜像须已存在于 Jetson；更改默认值不会
替换已有容器。Core 与 Bridge 当前均处于运行状态，设备状态为 `NORMAL / IDLE`。
备份持久目录前曾停止服务，备份 SHA-256 为
`63251fd22ae90c22e227f91a0dd052f002310cbb262730136fa2d49ad71e6720`。回退前应保护
新产生的数据并按备份记录恢复匹配版本；V1.1.0 镜像身份与历史证据见上文。

在仓库根目录执行：

```sh
./scripts/start-jetson.sh --confirm-external-vpwr-7v
```

脚本是启动 Core、Bridge 的唯一自动化实现。它会：

1. 检查 Docker Compose、持久目录和唯一的 `MSP430-USB Example` `by-id` 设备；
2. 幂等执行 Jetson Compose，不创建重复服务；
3. 在有限时间内等待健康接口、Bridge 连接、设备 `NORMAL/IDLE` 和启动会话中记录的 `VDRV_READY=1`；
4. 有图形桌面时调用系统浏览器打开 `http://127.0.0.1:8000/`，纯 SSH 会话则只打印网址；
5. 就绪后退出，不持续监控，也不应用配置、采集或产生 Burst。

失败诊断默认写入 `/var/lib/tuss4470/launcher/start-failure-*.log`。可通过 `USAC_SERIAL_DEVICE`、`USAC_CORE_DATA_DIR`、`USAC_BRIDGE_SPOOL_DIR`、`USAC_LAUNCHER_LOG_DIR` 和 `USAC_READY_TIMEOUT_SECONDS` 覆盖路径或等待时间。

`VDRV_READY` 是固件在复位、配置或采集检查时保存的状态，不是页面每次刷新时对 VPWR 的实时测量。因此启动确认必须包含供电稳定后的 S3 `RST`；脚本退出后若 7 V 再掉电，本版不会持续监控或立即更新页面状态。

需要手动启动时仍可执行：

```sh
export USAC_CORE_IMAGE=tuss4470-acquisition-core:1.1.1
export USAC_SERIAL_DEVICE=/dev/serial/by-id/usb-Texas_Instruments_MSP430-USB_Example_<本板32位小写十六进制序列号>-if00
docker compose -f deploy/compose.jetson.yaml up -d --no-build
```

启动后：

- bridge 连接真实 USB CDC，并主动连接 `core:8765`；
- CAPTURE_DATA 先写入 bridge spool，core SQLite COMMIT 后才删除 pending；
- Web/API 仅发布到 Jetson 宿主的 `127.0.0.1:8000`；
- 重建单个容器不会删除另一服务的持久数据。

停止服务使用：

```sh
docker compose -f deploy/compose.jetson.yaml down
```

停止不会删除 `/var/lib/tuss4470/core` 或 `/var/lib/tuss4470/bridge/spool`。
