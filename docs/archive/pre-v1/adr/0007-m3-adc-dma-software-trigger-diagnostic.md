# ADR 0007：使用无Burst软件触发隔离M3 ADC/DMA链路

## 文档说明

本文档记录 M3 定时触发连续得到零采样后的最小隔离测试，适用于首次真实波形
调试。它只定义一次性诊断固件，不改变正式 M3 固件、线协议或采集数据格式。

## 目的

区分“Timer_B 没有触发 ADC”和“ADC/DMA 本身没有工作”。诊断固件复用现有
USB、配置和安全回环，但 `CAPTURE_ONCE` 阶段不配置 Timer_B、不切换 IO2，
也不产生超声 Burst。

## 第一层诊断：ADC与DMA整体链路

- ADC 使用 A0、AVCC参考、12位结果和4 MHz ADC时钟；
- 使用 `ADC12SHS_0`、`ADC12MSC`、重复单通道模式，并通过
  `ADC12ENC | ADC12SC` 启动连续软件触发转换；
- DMA0直接将 `ADC12MEM0` 搬运到唯一的2048点波形缓冲；
- DMA1、Timer_B和Burst定时器不参与诊断采集；
- 诊断有意不返回正式采集成功，而是通过现有错误明细报告
  `captured_samples` 和 `dma_remaining`，避免把无Burst数据误认为正式波形。

## 判定

- `detail0=2048, detail1=0`：ADC和DMA链路工作，后续只调查Timer_B触发；
- `detail0=0, detail1=2048`：故障位于ADC启动或DMA配置；
- 其他数值：ADC/DMA曾启动但中途停止，需要结合计数继续定位。

第一层实机结果为 `detail0=0, detail1=2048`。后续确认该结果是DMA块完成后
`DMA0SZ`自动重装为2048导致的报告误判，并不代表零搬运。

## 第二层诊断：单次ADC轮询

复用相同诊断构建入口，临时以单次转换模式执行 `ADC12ENC | ADC12SC`，不配置
DMA，并直接轮询 `ADC12IFG0`。现有错误明细临时解释为：

- `detail0=1`：ADC完成了一次转换；`detail1`是对应的12位原始结果；
- `detail0=0`：等待窗口内未见ADC完成；`detail1`为0。

该层仍不返回正式采集成功，不配置Timer_B、DMA或Burst输出。若ADC完成，则后续
只调查DMA触发；若ADC仍不完成，则调查ADC启动、时钟与寄存器状态。

第二层实机结果为 `detail0=1, detail1=1692`，证明ADC启动、ADC时钟、A0输入和
`ADC12IFG0`均正常，故障已缩小到DMA路径。

## 第三层诊断：DMAREQ软件搬运

复用相同诊断入口，先执行一次已验证的ADC轮询并保存结果，再将DMA0配置为单次
搬运：源为诊断源字，目标为波形缓冲第一个字，触发源为`DMAREQ`。该层不依赖
`ADC12IFGx`，也不启用DMA中断。

- `detail0=1`：DMAIFG置位且目标值与源值一致；`detail1`为目标值；
- `detail0=0`：软件DMA搬运未完成；`detail1`为目标缓冲当前值。

实机返回`detail0=0, detail1=1370`；目标值已从哨兵值改变，证明DMA搬运成功。
`detail0`为0是诊断错误要求完成后的`DMA0SZ==0`，而手册规定该寄存器会重装为
原始长度。由此定位到正式采集的完成报告逻辑，而不是ADC或DMA硬件触发。

刷写前仍要求外部7 V关闭。运行时保留现有TUSS4470配置和安全回环检查，因此
恢复7 V后再执行一次诊断命令，但诊断采集本身不会产生Burst。
