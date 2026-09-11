# Jetson V1 部署与运行

## 文档说明

本文档说明 V1 超声采集子模块在 Jetson 宿主机和容器内的设备、网络与持久目录边界，解决“哪些配置属于宿主机、哪些路径属于容器”的问题。它适用于 V1 的部署、启动、停止和真实设备运行；协议与安全边界分别以 `docs/protocol.md` 和 V1 已知限制为准。

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
3. VPWR 7 V 的极性、限流和实测电压已人工确认；仅 USB 供电时不得启动带 `--confirm-external-vpwr-7v` 的正式 bridge 服务。
4. `USAC_SERIAL_DEVICE` 指向实际的 `/dev/ttyACM*` 或 `/dev/tuss4470`。

`compose.jetson.yaml` 中的确认参数只解除主机侧启动门禁，并不会主动产生 Burst；实际激励仍需经过配置读回、VDRV_READY、故障状态和固件安全状态机。

## 启动结果

在仓库根目录执行：

```sh
export USAC_CORE_IMAGE=tuss4470-acquisition-core:1.0.0
docker compose -f deploy/compose.jetson.yaml up -d
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
