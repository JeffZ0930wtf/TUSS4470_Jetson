# ADR 0006：ADC 与 DMA 使用 Timer_B0 分相触发

## 文档说明

本文档记录 MSP430F5529 采集路径的 Timer_B0、ADC12_A 与 DMA 触发决定，
适用于 M3 基线和 M5 可变采样率下的连续2048点采集。它补充正式设计，
不改变TUSS4470配置、Burst数量、DMA数据布局或主机协议。

## 现象与证据

M3 已确认 `TB0.1` 能稳定触发一次真实采集。M5 连续采集验收则两次稳定复现：
复位后的第一帧成功，第二帧中Timer_B与ADC仍运行、`ADC12IFG0`置位，但DMA0
保持2048、DMA1未完成且Burst未启动。完整关闭并重开ADC/DMA后现象不变，
因此不再把`ADC12IFG0`用作长期重复采集的DMA边沿源。

## 决定

- 使用 `TB0CCR0 = sample_interval_ticks - 1` 定义 120 个 SMCLK tick 的采样周期；
- 使用 `TB0CCR1 = 1` 和 `TB0CCTL1 = OUTMOD_3`，每周期产生一个明确的
  TB0.1 上升沿；
- ADC12触发源保持`ADC12SHS_3`（TB0.1）；
- ADC12CLK为SMCLK/6，4个采样保持周期加13个转换周期按102个SMCLK tick预算；
- 固定`TB0CCR2=111`：ADC从tick 1开始，最坏转换完成点为tick 103，之后保留
  8 tick保护间隔；DMA0和DMA1均选择`TB0CCR2.IFG`（DMA trigger 8）；
- `TB0CCTL2.CCIE`必须保持0，使CCIFG可作为DMA触发；ADC12IFG0只作为诊断证据；
- 停止采集时显式关闭TB0.1输出模式并清理TB0CCR2/CCIFG；
- 保持 200 kS/s、2048 点、64 点预触发、DMA0/DMA1 和单脉冲 Burst 不变。

## 备选方案

继续使用ADC12IFG作为DMA触发已在第二帧稳定失效。使用TB0CCR0会把DMA触发、
周期回零和下一周期边界集中在同一位置；拆成两段DMA则会增加ISR切换和采样间隙。
TB0CCR2是数据手册定义的内部DMA触发源，可在ADC完成后、下一周期前产生独立事件，
因此采用同一Timer_B内的分相触发。

## 验收

静态测试必须确认TB0.1、`TB0CCR2=111`、DMA trigger 8、CCIE关闭及逐帧清理，
并要求DMA0中断提供独立的完整块证据，禁止以完成后自动重装的`DMA0SZ`推算成功
点数。完整构建和离线回归通过后，才允许在7 V断电状态刷写；首先恢复连续2帧
门禁，两帧都必须得到恰好2048个未经插值的ADC原始样本，之后才能进入M5参数、
周期及长序列验收。
