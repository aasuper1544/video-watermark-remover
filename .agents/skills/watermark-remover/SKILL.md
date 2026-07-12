---
name: watermark-remover
description: Provides guidelines, architecture, and coding rules for the AI Video Watermark Remover project. Activate this skill when coding, debugging, or extending the watermark remover frontend or backend.
---

# AI Video Watermark Remover - 开发与维护指南

本技能文档（SKILL.md）记录了本项目的核心架构设计、算法规范以及常见开发要求，以确保 AI 助手在协助您开发、调试或重构此项目时，能够完全遵循本项目的规范。

---

## 1. 项目核心架构

### 后端 (FastAPI & python)
*   **入口**：`backend/main.py` 提供 Web 接口。
*   **去水印引擎**：`backend/remover.py`，核心逻辑为：
    1.  **时序高频极小值计算**：提取视频多帧边缘做 `np.minimum.reduce`，提取出精确的水印 Mask。
    2.  **LaMa ONNX 推理**：加载 `models/lama_fp32.onnx` 对 Mask 区域进行深度图像修复。
    3.  **时序融合**：将修复后的区域与原视频帧平滑融合。

### 前端 (Glassmorphism 毛玻璃风)
*   **入口**：`frontend/index.html` (结构)，`frontend/style.css` (毛玻璃样式与暗黑风设计)，`frontend/app.js` (Canvas 可视化拉框与 API 对接)。

---

## 2. 核心开发规范与约束 (Rules)

> [!IMPORTANT]
> **1. ONNX 推理性能与线程安全**
> *   在修改 `backend/remover.py` 时，注意 `onnxruntime.InferenceSession` 应当为全局单例或在类初始化中加载一次，避免每次处理视频都重新加载 200MB 的模型。
> *   注意推理过程中的内存管理，处理大视频时要及时释放 OpenCV 资源（运行 `cap.release()` 等）。

> [!TIP]
> **2. 视频音频流合并规范**
> *   必须确保通过 `imageio-ffmpeg` 保留视频的原始音频轨道。
> *   导出转码必须使用 H.264 编码，以确保生成的文件可以直接在前端网页的 `<video>` 标签中直接流畅播放。

> [!WARNING]
> **3. 前端毛玻璃样式规范**
> *   前端界面的主色调保持暗黑色系，使用毛玻璃模糊滤镜 `backdrop-filter: blur(10px)`。
> *   交互中所有的选区操作要确保自适应屏幕尺寸和缩放比。

---

## 3. 技能迭代机制 (How to update this skill)
当您在与 AI 对话中发现：
1.  AI 给出的代码不符合本项目（例如模型路径写错、跨域报错等）。
2.  或者您对项目做出了重大修改（例如增加了新的 AI 去水印算法，或者更换了前端框架）。
3.  **请直接输入 `/learn`**，让 AI 将最新得出的项目认知或修改意见固化更新到本文件中。
