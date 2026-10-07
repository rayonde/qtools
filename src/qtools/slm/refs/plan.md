qtools/slm/
├── __init__.py
├── backends/
│   ├── base.py          # 通用的SLMBackend
│   ├── __init__.py      # 显式 _BACKEND_MODULES + 逐个 try/except
│   └── holoeye/         # 厂商模型(backend.py + 可选 SDK + calibration 所用的lut)
│   └── simulated/      # 直接使用 slmsuite 中的simualted 来创建一个 simulated slm）
│   └── santec/
├── analysis/        # 放置后处理的一些分析
├── alogritms/        # 相位重构的一些算法 比如 iterative phase retrieval algorithms 这一部分主要是 slmsuite 的 引用，直到使用才会载入 slmsuite 默认载入
├── scripts/          # 一些国定算法 比如 找到 光束中心点的位置 调节 菲涅耳透镜参数优化耦合等，
    └── find_position.py	光斑位置扫描和拟合
├── phase/          # 所有 计算phase 的函数 比如 spiral flat  blaze binary random zernike 
├── slm.py               # slm 主要包含 SLM class 来包含 slm 的主要信息 和对应 屏幕 
├── monitor.py        # 注册表 register slm + list_monitors (重点是 calibration 和加载lut 后正常使用slm 是把它当作第二屏幕， 实验需要连接控制多个屏幕，需要做好 第二屏幕的识别 和slm 的对应， SLM class 的实例也会和固定的monitor 来绑定 载入 displaymask 可以 直接在指定的第二屏幕中显示)
├── display/
    ├── display.py      # 定义 DisplayMask 负责 phasemask 到 diaplymask 的转化 比如 8bit 的灰阶量化 10 bit 灰阶量化   10 bit 灰阶转为RGB 格式 Qt 全屏显示 / Headless 模拟 / RPC 远程显示  QtDisplay / HeadlessDisplay
    ├── server.py	显示服务端
    ├── client.py	RPC 客户端
├── utils.py        # 实用functions 
├── luts.py        # 实用functions LUT 的读写和编码



DisplayMask
    └── 负责图像变换、保存和显示

DisplayInterface
    ├── Display：Qt 实际显示
    └── Client：通过 ipyutils 远程调用


with SLM("holoeye", is_mock=True) as slm:
    canvas = slm.create_canvas()
    phase_mask  = canvas.lens(f=2)  # or canvas += phase.lens(f=2). # canvas 类似一个phase mask 但是是空的一个mask
    display_mask = phase2display(phase_mask, bits=8, rgb= False).  # or. phase_mask.to_display( bit=8, rgb= False)
    slm.load(display_mask)

with SLM("holoeye", is_mock=False) as slm:
    canvas = slm.create_canvas()     # split() 返回普通的 PhaseMask，而是返回带区域信息的 PhaseRegion
                                    # canvas 也是 返回带区域信息的 PhaseRegion

    left, right = canvas.partition( 
        axis="x",
        ratios=(1, 2),
    )

    left_phase = left.spiral(order=1, center=(x, y))
    right_phase = right.spiral(order=2, center=(x, y))

    combined = canvas.compose(left_phase, right_phase)

    slm.load_phase(combined)

slm.load(display_mask)       # 已经是灰度值，直接显示
slm.load_phase(phase_mask)   # 先转换为灰度值，再显示


我希望 qtools.slm 符合以上的代码架构
请将refs/slmutils 中的code 按照上面的架构重构为qtools.slm 的代码， 实现给定目标的subpackage 