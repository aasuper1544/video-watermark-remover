# 🎬 AI Video Watermark Remover (AI 视频去水印大师)

一款基于前沿 AI 技术的本地视频去水印 Web 应用程序。前端使用现代毛玻璃（Glassmorphism）暗黑风界面，支持可视化鼠标拉框选区，后端集成 **LaMa (Resolution-robust Large Mask Inpainting) 深度学习模型** 与我们首创的 **时序高频极小值算法 (Temporal Edge Minima)**，实现对复杂走动背景、网格纹理以及人像遮挡区域的**完美无痕消除**。

---

## 🌟 核心特色与算法

### 1. 🤖 LaMa AI 深度修复 (Mode A - 强力推荐)
相比传统的 OpenCV 涂抹填充（Telea/NS），本项目集成了著名的 **LaMa (Large Mask Inpainting)** 模型。它拥有强大的感受野和语义脑补能力，能够对遮挡的水印区域进行结构级别的连贯重建（如金属拉丝、大理石纹路、地板网格等），修复后极度自然。

### 2. ⚡ 时序高频极小值算法 (Temporal Edge Minima)
针对很多视频中水印下层背景在走动的难题，本项目内置了**时序高频极小值算法**：
- 采样视频不同时间段的多帧画面，提取高频边缘信息。
- 进行像素级时序极小值（`np.minimum.reduce`）计算。由于视频背景边缘在不断移动，而水印是静止不动的，求极小值后移动的背景噪点会被**彻底过滤**，仅留下 100% 精确的水印细窄笔画掩码。
- **超精细修复**：AI 只需要修复极窄的水印笔画，最大程度保留了背景画面原有的运动细节，避免大面积模糊。

### 3. 🛡️ 边界安全防剪裁机制 (Safety Margin Expansion)
后端自动为您的框选区域四周扩充 15 像素，确保水印的边缘在进行形态学膨胀时不会被框界截断，彻底避免边缘留有“白色重影轮廓”。

---

## 📂 项目结构
```
video-watermark-remover/
├── backend/
│   ├── __init__.py
│   ├── main.py          # FastAPI 接口路由
│   └── remover.py       # 去水印引擎（时序极小值 + LaMa ONNX 推理）
├── frontend/
│   ├── index.html       # 现代暗黑风前端
│   ├── style.css        # 视觉样式与毛玻璃设计
│   └── app.js           # 可视化选区与 API 进度对接交互
├── models/
│   └── (lama_fp32.onnx) # LaMa 模型文件 (Git 已忽略，需手动下载，见下方说明)
├── run.bat              # Windows 一键启动脚本
├── requirements.txt     # Python 依赖库
└── README.md            # 说明文档
```

---

## 🚀 快速启动指南

### 第一步：克隆项目到本地
```bash
git clone https://github.com/您的用户名/video-watermark-remover.git
cd video-watermark-remover
```

### 第二步：下载 LaMa AI 模型文件
由于 AI 模型文件较大（约 200MB），不适合直接上传到 GitHub 代码库，因此已在 `.gitignore` 中忽略。
请您在启动前，点击下方链接下载模型权重，并放入项目的 **`models/`** 文件夹下：
- 🔗 **LaMa FP32 ONNX 官方推荐下载点**：[Hugging Face 下载链接](https://huggingface.co/akiyamasho/lama-onnx/resolve/main/lama_fp32.onnx)
- 📥 **存放路径**：`video-watermark-remover/models/lama_fp32.onnx`

---

### 第三步：运行服务

#### 选项 1：Windows 双击一键启动 (推荐)
在项目根目录下，直接双击 **`run.bat`**。
脚本将自动执行以下操作：
1. 检查并一键安装所需的 Python 依赖。
2. 自动启动后台 Web 接口。
3. 自动在您的浏览器中打开去水印网页（`http://127.0.0.1:8000`）。

#### 选项 2：手动终端启动
如果您使用的是 macOS / Linux，或者倾向于手动命令：
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动 FastAPI 服务
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
启动后在浏览器中访问：`http://127.0.0.1:8000`。

---

## 🎵 自动音频合并与视频转码 (FFmpeg 整合)

本项目已默认集成了 `imageio-ffmpeg`，它在检测到您的操作系统后，会**自动定位和配置**免安装的静态 FFmpeg 可执行文件。
- 处理完成后，程序将**完美保留原视频的音轨**，并自动将去水印后的视频合并为标准的 **H.264 (视频) + AAC (音频)** 编码格式的 MP4。
- 这确保了您导出的视频可以在主流浏览器（Chrome/Edge/Safari）中直接播放和流畅预览！

---

## 📝 开发者贡献与协议
本项目采用 **MIT 开源协议**。如有算法优化或 UI 改进建议，欢迎提交 PR！
