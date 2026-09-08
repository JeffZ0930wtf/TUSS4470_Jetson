# Jetson M5 部署说明

## 文档说明

本文档说明 M5 超声采集子模块在 Jetson 宿主机和容器内的设备、网络与持久目录边界，解决“哪些配置属于宿主机、哪些路径属于容器”的问题。它适用于 M5 部署准备和 M6 真实 Jetson 验收；功能目标与关闭条件仍以正式设计文档和实施路线图为准。

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

先用 `udevadm info --attribute-walk --name=/dev/ttyACM0` 核对实际设备的 `idVendor` 和 32 位小写十六进制 USB 序列号。随后可创建 `/etc/udev/rules.d/99-tuss4470.rules`：

```udev
SUBSYSTEM=="tty", ATTRS{idVendor}=="0451", ATTRS{serial}=="替换为本板32位小写序列号", SYMLINK+="tuss4470", GROUP="dialout", MODE="0660"
```

不得照抄占位序列号。规则加载后重新插拔设备，并确认 `/dev/tuss4470` 指向预期的 `/dev/ttyACM*`。

## 启动前提

1. 宿主目录已创建且运行用户可写。
2. J2=TX、J3=RX、R12 已移除，J1=8 nF、J4=6.8 nF。
3. VPWR 7 V 的极性、限流和实测电压已人工确认；仅 USB 供电时不得启动带 `--confirm-external-vpwr-7v` 的正式 bridge 服务。
4. `USAC_SERIAL_DEVICE` 指向实际的 `/dev/ttyACM*` 或 `/dev/tuss4470`。

`compose.jetson.yaml` 中的确认参数只解除主机侧启动门禁，并不会主动产生 Burst；实际激励仍需经过配置读回、VDRV_READY、故障状态和固件安全状态机。

## 启动结果

使用 `docker compose -f deploy/compose.jetson.yaml up` 后：

- bridge 连接真实 USB CDC，并主动连接 `core:8765`；
- CAPTURE_DATA 先写入 bridge spool，core SQLite COMMIT 后才删除 pending；
- Web/API 仅发布到 Jetson 宿主的 `127.0.0.1:8000`；
- 重建单个容器不会删除另一服务的持久数据。
