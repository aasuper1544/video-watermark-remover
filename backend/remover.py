import os
import cv2
import numpy as np
import time
import subprocess
import shutil
import base64
import threading
import re
import imageio_ffmpeg
import queue

# LaMa ONNX AI 修复模型（懒加载单例）
_lama_session = None
_lama_lock = threading.Lock()

def _download_lama_model(model_path):
    """从 hf-mirror.com 镜像源自动下载 LaMa 权重"""
    import urllib.request
    url = "https://hf-mirror.com/akiyamasho/lama-onnx/resolve/main/lama_fp32.onnx"
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    print(f"\n[AI] 正在自动下载 LaMa AI 修复模型 (约 200MB)，此操作仅在首次启动时执行...")
    print(f"📥 下载链接: {url}")
    
    def progress_hook(count, block_size, total_size):
        downloaded = count * block_size
        percent = int(downloaded * 100 / total_size) if total_size > 0 else 0
        percent = min(100, percent)
        bar = "=" * (percent // 5) + " " * (20 - percent // 5)
        print(f"\r进度: [{bar}] {percent}% ({downloaded / (1024*1024):.1f}MB / {total_size / (1024*1024):.1f}MB)", end="", flush=True)
        
    try:
        urllib.request.urlretrieve(url, model_path, progress_hook)
        print("\n[OK] LaMa 模型下载完成并就位！")
        return True
    except Exception as e:
        print(f"\n[ERROR] 自动下载模型失败: {e}")
        if os.path.exists(model_path):
            try:
                os.remove(model_path)
            except Exception:
                pass
        print("💡 请尝试手动下载该模型，并命名为 lama_fp32.onnx 放入 models/ 文件夹中。")
        return False

def _get_lama_session():
    """懒加载 LaMa ONNX 模型，全局仅加载一次"""
    global _lama_session
    if _lama_session is None:
        with _lama_lock:
            if _lama_session is None:
                try:
                    import onnxruntime as ort
                    model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models', 'lama_fp32.onnx')
                    if not os.path.exists(model_path):
                        # 文件不存在，触发自动下载
                        success = _download_lama_model(model_path)
                        if not success:
                            return None
                    
                    if os.path.exists(model_path):
                        _lama_session = ort.InferenceSession(model_path)
                        print(f"LaMa ONNX 模型加载成功: {model_path}")
                    else:
                        print(f"LaMa 模型文件不存在: {model_path}")
                except ImportError:
                    print("onnxruntime 未安装，LaMa AI 修复不可用")
                except Exception as e:
                    print(f"LaMa 模型加载失败: {e}")
    return _lama_session

# 全局任务状态字典与线程锁
jobs_status = {}
jobs_lock = threading.Lock()

def update_job_status(job_id: str, **kwargs):
    """线程安全地更新任务状态"""
    with jobs_lock:
        if job_id in jobs_status:
            for k, v in kwargs.items():
                jobs_status[job_id][k] = v

def has_active_jobs() -> bool:
    """检查是否有正在进行的去水印任务"""
    with jobs_lock:
        for job in list(jobs_status.values()):
            if job.get("status") == "processing":
                return True
    return False

def cleanup_lama_session(force: bool = False):
    """如果当前没有活动任务（或强制释放），则释放 LaMa ONNX Runtime 会话以释放内存"""
    global _lama_session
    if _lama_session is not None:
        if force or not has_active_jobs():
            with _lama_lock:
                if _lama_session is not None and (force or not has_active_jobs()):
                    _lama_session = None
                    print("[AI] LaMa ONNX Runtime session released to free memory.")
            import gc
            gc.collect()

# 全局先进先出队列
job_queue = queue.Queue()
_worker_thread = None
_worker_lock = threading.Lock()

def _queue_worker():
    """先进先出任务处理消费线程"""
    print("[Queue] Background queue worker thread started.")
    while True:
        try:
            job_info = job_queue.get()
            if job_info is None:
                break
            job_id, regions, method, feather, output_path, video_path, output_dir = job_info
            
            # 判断在开始处理前，任务是否已被用户取消
            with jobs_lock:
                status = jobs_status.get(job_id, {}).get("status")
            if status == "canceled":
                job_queue.task_done()
                continue
                
            # 更新状态为开始处理
            update_job_status(job_id, status="processing")
            
            try:
                # 实例化 WatermarkRemover 并调用逐帧处理
                remover = WatermarkRemover(video_path, output_dir)
                remover._process_via_opencv(job_id, regions, method, feather, output_path)
            except Exception as e:
                print(f"[Queue Error] Job {job_id} failed: {e}")
                with jobs_lock:
                    if jobs_status.get(job_id, {}).get("status") not in ["completed", "canceled"]:
                        jobs_status[job_id]["status"] = "failed"
                        jobs_status[job_id]["error_message"] = str(e)
            finally:
                job_queue.task_done()
        except Exception as e:
            print(f"[Queue Worker Exception] {e}")
            time.sleep(1)

def start_queue_worker():
    """启动全局排队工作线程（单例）"""
    global _worker_thread
    with _worker_lock:
        if _worker_thread is None:
            _worker_thread = threading.Thread(target=_queue_worker)
            _worker_thread.daemon = True
            _worker_thread.start()

# 全局任务状态字典
jobs_status = {}
active_processes = {}
active_processes_lock = threading.Lock()

def get_job_status(job_id: str):
    with jobs_lock:
        status = jobs_status.get(job_id)
        if status is not None:
            return status.copy()
        return {"status": "not_found"}

def cancel_job(job_id: str) -> bool:
    """取消指定的任务"""
    with jobs_lock:
        job = jobs_status.get(job_id)
        if not job:
            return False
        
        if job.get("status") not in ["processing", "pending"]:
            return False
            
        job["status"] = "canceled"
        job["progress"] = 0
        job["error_message"] = "任务已被用户取消"
    
    # 终止关联的子进程
    with active_processes_lock:
        if job_id in active_processes:
            proc = active_processes[job_id]
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception as e:
                print(f"终止子进程 {job_id} 失败: {e}")
                try:
                    proc.kill()
                except:
                    pass
            finally:
                active_processes.pop(job_id, None)
                
    return True

class WatermarkRemover:
    def __init__(self, video_path: str, output_dir: str):
        self.video_path = video_path
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        # 打开视频获取基本属性
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"无法打开视频文件: {video_path}")
            
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = cap.get(cv2.CAP_PROP_FPS)
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        
    def get_preview_frame(self, frame_index: int = 0) -> str:
        """获取指定帧的 Base64 编码 JPEG 图像以供前端显示"""
        cap = cv2.VideoCapture(self.video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            cap = cv2.VideoCapture(self.video_path)
            ret, frame = cap.read()
            cap.release()
            if not ret:
                raise ValueError("无法读取视频帧")
                
        _, buffer = cv2.imencode('.jpg', frame)
        b64_str = base64.b64encode(buffer).decode('utf-8')
        return b64_str

    def generate_preview_frame(self, regions: list, method: str = "inpaint", feather: int = 5, frame_index: int = 0) -> str:
        """生成并返回单帧去水印结果的 Base64"""
        full_mask_mode = False
        if method.endswith("_full"):
            full_mask_mode = True
            method = method.replace("_full", "")
            
        cap = cv2.VideoCapture(self.video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, target_frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, target_frame = cap.read()
            if not ret:
                cap.release()
                raise ValueError("无法读取视频帧用于预览")
        
        # 自动向四周扩展 15 像素以保证膨胀（dilation）有足够的边界空间而不被剪裁
        expanded_regions = []
        for region in regions:
            x, y, w, h = region['x'], region['y'], region['w'], region['h']
            nx = max(0, x - 15)
            ny = max(0, y - 15)
            nw = min(self.width - nx, w + 30)
            nh = min(self.height - ny, h + 30)
            expanded_regions.append({'x': nx, 'y': ny, 'w': nw, 'h': nh})
        regions = expanded_regions

        # 1. 提取全局掩码
        global_mask_est = np.zeros((self.height, self.width), dtype=np.uint8)
        if method in ["inpaint", "lama"]:
            if full_mask_mode:
                for region in regions:
                    rx, ry, rw, rh = region['x'], region['y'], region['w'], region['h']
                    global_mask_est[ry:ry+rh, rx:rx+rw] = 255
            else:
                # 使用时序高频极小值算法 (Temporal Edge Minima) 提取超精细静态水印掩码
                sample_count = min(15, self.total_frames)
                frame_indices = np.linspace(0, self.total_frames - 1, sample_count, dtype=int)
                high_passes = {i: [] for i in range(len(regions))}
                
                for idx in frame_indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    r, f = cap.read()
                    if r:
                        for i, region in enumerate(regions):
                            rx, ry, rw, rh = region['x'], region['y'], region['w'], region['h']
                            roi_gray = cv2.cvtColor(f[ry:ry+rh, rx:rx+rw], cv2.COLOR_BGR2GRAY)
                            roi_blur = cv2.GaussianBlur(roi_gray, (25, 25), 0)
                            roi_hp = cv2.absdiff(roi_gray, roi_blur)
                            high_passes[i].append(roi_hp)
                
                for i, region in enumerate(regions):
                    rx, ry, rw, rh = region['x'], region['y'], region['w'], region['h']
                    region_hps = high_passes[i]
                    if len(region_hps) > 0:
                        temporal_min = np.percentile(region_hps, 30, axis=0).astype(np.uint8)
                        _, mask_est = cv2.threshold(temporal_min, 4, 255, cv2.THRESH_BINARY)
                        
                        kernel_close = np.ones((3, 3), np.uint8)
                        mask_closed = cv2.morphologyEx(mask_est, cv2.MORPH_CLOSE, kernel_close)
                        
                        contours, _ = cv2.findContours(mask_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        mask_filled = np.zeros_like(mask_closed)
                        cv2.drawContours(mask_filled, contours, -1, 255, -1)
                        
                        dilate_size = max(5, feather + 2) 
                        kernel_dilate = np.ones((dilate_size, dilate_size), np.uint8)
                        mask_dilated = cv2.dilate(mask_filled, kernel_dilate, iterations=1)
                        
                        if np.sum(mask_dilated > 0) < (rw * rh * 0.01):
                            mask_dilated = np.ones((rh, rw), dtype=np.uint8) * 255
                        global_mask_est[ry:ry+rh, rx:rx+rw] = mask_dilated
        
        cap.release()
        
        mask = np.zeros((self.height, self.width), dtype=np.uint8)
        if method in ["inpaint", "lama"]:
            mask = global_mask_est.copy()
            for region in regions:
                x, y, w, h = region['x'], region['y'], region['w'], region['h']
                if np.sum(mask[y:y+h, x:x+w]) == 0:
                    mask[y:y+h, x:x+w] = 255
        else:
            for region in regions:
                x, y, w, h = region['x'], region['y'], region['w'], region['h']
                mask[y:y+h, x:x+w] = 255
                
        # 2. 执行修复
        frame = target_frame.copy()
        if method == "inpaint":
            for region in regions:
                x, y, w, h = region['x'], region['y'], region['w'], region['h']
                margin = 15
                ly, lx = max(0, y - margin), max(0, x - margin)
                lh, lw = min(self.height - ly, h + margin * 2), min(self.width - lx, w + margin * 2)
                local_frame = frame[ly:ly+lh, lx:lx+lw]
                local_mask = mask[ly:ly+lh, lx:lx+lw]
                if np.sum(local_mask) > 0:
                    frame[ly:ly+lh, lx:lx+lw] = cv2.inpaint(local_frame, local_mask, inpaintRadius=1, flags=cv2.INPAINT_NS)
        elif method == "lama":
            lama_session = _get_lama_session()
            if lama_session is not None:
                for region in regions:
                    x, y, w, h = region['x'], region['y'], region['w'], region['h']
                    crop_size = 512
                    cx, cy = x + w // 2, y + h // 2
                    cx1, cy1 = max(0, cx - crop_size // 2), max(0, cy - crop_size // 2)
                    cx2, cy2 = min(self.width, cx1 + crop_size), min(self.height, cy1 + crop_size)
                    cx1, cy1 = max(0, cx2 - crop_size), max(0, cy2 - crop_size)
                    
                    crop_mask = mask[cy1:cy2, cx1:cx2]
                    if np.sum(crop_mask) == 0: continue
                    
                    img_tensor = None
                    mask_tensor = None
                    result = None
                    try:
                        crop_bgr = frame[cy1:cy2, cx1:cx2].copy()
                        crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
                        img_tensor = (crop_rgb.astype(np.float32) / 255.0)
                        img_tensor = np.transpose(img_tensor, (2, 0, 1))[np.newaxis, ...]
                        mask_tensor = (crop_mask > 127).astype(np.float32)[np.newaxis, np.newaxis, ...]
                        
                        inp_img = lama_session.get_inputs()[0].name
                        inp_mask = lama_session.get_inputs()[1].name
                        result = lama_session.run(None, {inp_img: img_tensor, inp_mask: mask_tensor})
                        output = np.transpose(result[0][0], (1, 2, 0))
                        output_bgr = cv2.cvtColor(np.clip(output, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
                        mask_bool = crop_mask > 0
                        for c in range(3):
                            crop_bgr[:, :, c][mask_bool] = output_bgr[:, :, c][mask_bool]
                        frame[cy1:cy2, cx1:cx2] = crop_bgr
                    except Exception as e:
                        print(f"[LaMa Preview Error] {e}")
                        # 回退到 OpenCV inpaint 修复
                        margin = 15
                        ly, lx = max(0, y - margin), max(0, x - margin)
                        lh, lw = min(self.height - ly, h + margin * 2), min(self.width - lx, w + margin * 2)
                        local_frame = frame[ly:ly+lh, lx:lx+lw]
                        local_mask = mask[ly:ly+lh, lx:lx+lw]
                        if np.sum(local_mask) > 0:
                            frame[ly:ly+lh, lx:lx+lw] = cv2.inpaint(local_frame, local_mask, inpaintRadius=1, flags=cv2.INPAINT_NS)
                    finally:
                        # 显式清理临时变量以释放内存
                        if 'img_tensor' in locals(): del img_tensor
                        if 'mask_tensor' in locals(): del mask_tensor
                        if 'result' in locals(): del result
                        import gc
                        gc.collect()
            else:
                for region in regions:
                    x, y, w, h = region['x'], region['y'], region['w'], region['h']
                    margin = 15
                    ly, lx = max(0, y - margin), max(0, x - margin)
                    lh, lw = min(self.height - ly, h + margin * 2), min(self.width - lx, w + margin * 2)
                    local_frame = frame[ly:ly+lh, lx:lx+lw]
                    local_mask = mask[ly:ly+lh, lx:lx+lw]
                    if np.sum(local_mask) > 0:
                        frame[ly:ly+lh, lx:lx+lw] = cv2.inpaint(local_frame, local_mask, inpaintRadius=1, flags=cv2.INPAINT_NS)
        
        _, buffer = cv2.imencode('.jpg', frame)
        return base64.b64encode(buffer).decode('utf-8')

    @staticmethod
    def get_ffmpeg_path() -> str:
        """获取 imageio-ffmpeg 提供的 FFmpeg 静态二进制文件路径"""
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            # 备用本地查找
            if shutil.which("ffmpeg"):
                return "ffmpeg"
            return ""

    def process(self, job_id: str, regions: list, method: str = "inpaint", feather: int = 5):
        """
        开始去水印处理（支持多区域）
        """
        # 严格边界限幅，防止超出视频范围导致算法或 FFmpeg 崩溃
        for r in regions:
            r['x'] = max(0, min(r['x'], self.width - 2))
            r['y'] = max(0, min(r['y'], self.height - 2))
            r['w'] = max(2, min(r['w'], self.width - r['x']))
            r['h'] = max(2, min(r['h'], self.height - r['y']))

        final_filename = f"processed_{job_id}.mp4"
        final_output_path = os.path.join(self.output_dir, final_filename)

        # 初始化任务进度，将初始状态设为 pending (排队中)
        with jobs_lock:
            jobs_status[job_id] = {
                "progress": 0,
                "status": "pending",
                "eta": 0,
                "error_message": "",
                "preview_frame": "",
                "ffmpeg_used": False,
                "video_path": self.video_path,
                "output_path": final_output_path
            }
        
        # 将任务投递到先进先出队列，由后台单个 worker 线程消费执行
        job_queue.put((job_id, regions, method, feather, final_output_path, self.video_path, self.output_dir))

    def _process_via_ffmpeg(self, job_id: str, ffmpeg_path: str, x: int, y: int, w: int, h: int, method: str, feather: int, output_path: str):
        """利用 FFmpeg 核心过滤器极速处理视频去水印，并完美保留音轨"""
        
        # 构建去水印滤镜指令
        if method == "inpaint":
            # FFmpeg delogo 滤镜：采用双线性插值算法填补水印区域
            # 将 band 设定为 1，将平滑边缘限制到最小（仅 1 像素），以确保除水印范围之外的其它所有画面像素完全保持不变
            filter_str = f"delogo=x={x}:y={y}:w={w}:h={h}:band=1:show=0"
        elif method == "blur":
            # 裁剪区域 -> 高斯/盒状模糊 -> 覆盖回原视频对应坐标
            blur_size = max(5, feather * 2 + 1)
            filter_str = f"[0:v]crop=w={w}:h={h}:x={x}:y={y},boxblur={blur_size}:{blur_size}[blurred];[0:v][blurred]overlay=x={x}:y={y}"
        elif method == "mosaic":
            # 裁剪区域 -> 缩小再用邻近插值放大制造大颗粒像素马赛克 -> 覆盖回原视频对应坐标
            block_size = max(4, w // 12)
            filter_str = f"[0:v]crop=w={w}:h={h}:x={x}:y={y},scale=w=iw/{block_size}:h=ih/{block_size},scale=w=iw*{block_size}:h=ih*{block_size}:flags=neighbor[mosaic];[0:v][mosaic]overlay=x={x}:y={y}"
        else:
            filter_str = f"delogo=x={x}:y={y}:w={w}:h={h}:band=1:show=0"

        # 方案 A：使用 Visually Lossless（视觉无损）编码（CRF=12），并对音频进行重编码为高兼容性 AAC 音频流，最大化网页播放兼容性
        cmd_a = [
            ffmpeg_path, "-y",
            "-i", self.video_path,
            "-filter_complex" if method in ["blur", "mosaic"] else "-vf", filter_str,
            "-c:v", "libx264",
            "-crf", "12",  # 视觉无损超高质量
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",  # 转码为标准的 AAC，保证主流浏览器兼容
            "-b:a", "192k",
            "-shortest",
            output_path
        ]
        
        print(f"正在尝试 FFmpeg 方案 A (CRF=12, 音频 AAC 重编码)...")
        success = self._run_ffmpeg_cmd(cmd_a, job_id)
        
        if not success:
            # 方案 A 失败，切换为方案 B (无损直接复制音频)
            print("FFmpeg 方案 A 失败，正在尝试方案 B (CRF=12, 音频直接 copy)...")
            cmd_b = [
                ffmpeg_path, "-y",
                "-i", self.video_path,
                "-filter_complex" if method in ["blur", "mosaic"] else "-vf", filter_str,
                "-c:v", "libx264",
                "-crf", "12",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                "-shortest",
                output_path
            ]
            success_b = self._run_ffmpeg_cmd(cmd_b, job_id)
            if not success_b:
                raise RuntimeError("FFmpeg 方案 A 和方案 B 均执行失败，将触发 OpenCV 回退机制")

        # 运行成功，更新状态为完成
        update_job_status(job_id, progress=100, status="completed", eta=0)

    def _run_ffmpeg_cmd(self, cmd: list, job_id: str) -> bool:
        """执行 FFmpeg 命令行并实时解析进度"""
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                universal_newlines=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            with active_processes_lock:
                if jobs_status.get(job_id, {}).get("status") == "canceled":
                    process.terminate()
                    return False
                active_processes[job_id] = process
            
            start_time = time.time()
            
            while True:
                if jobs_status.get(job_id, {}).get("status") == "canceled":
                    process.terminate()
                    process.wait()
                    break
                    
                line = process.stderr.readline()
                if not line:
                    break
                    
                match = re.search(r'frame=\s*(\d+)', line)
                if match:
                    current_frame = int(match.group(1))
                    progress = int((current_frame / self.total_frames) * 100)
                    progress = min(99, progress)
                    
                    elapsed = time.time() - start_time
                    fps_calc = current_frame / elapsed if elapsed > 0 else 1.0
                    eta = int((self.total_frames - current_frame) / fps_calc) if fps_calc > 0 else 0
                    
                    update_job_status(job_id, progress=progress, eta=eta)
                    
            process.wait()
            return process.returncode == 0
            
        except Exception as e:
            print(f"执行 FFmpeg 命令出错: {e}")
            return False
        finally:
            with active_processes_lock:
                active_processes.pop(job_id, None)

    def _process_via_opencv(self, job_id: str, regions: list, method: str, feather: int, output_path: str):
        """OpenCV 逐帧处理"""
        full_mask_mode = False
        if method.endswith("_full"):
            full_mask_mode = True
            method = method.replace("_full", "")
            
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            update_job_status(job_id, status="failed", error_message="无法打开视频源文件")
            return

        temp_filename = f"temp_{job_id}.mp4"
        temp_output_path = os.path.join(self.output_dir, temp_filename)
        
        # 使用 mp4v 编码进行中间处理
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_output_path, fourcc, self.fps, (self.width, self.height))
        if not out.isOpened():
            update_job_status(job_id, status="failed", error_message="无法创建临时输出视频文件，请检查磁盘空间或写入权限")
            cap.release()
            return
        # 自动向四周扩展 15 像素以保证膨胀（dilation）有足够的边界空间而不被剪裁
        expanded_regions = []
        for region in regions:
            x, y, w, h = region['x'], region['y'], region['w'], region['h']
            nx = max(0, x - 15)
            ny = max(0, y - 15)
            nw = min(self.width - nx, w + 30)
            nh = min(self.height - ny, h + 30)
            expanded_regions.append({'x': nx, 'y': ny, 'w': nw, 'h': nh})
        regions = expanded_regions

        # 提取全局静态水印掩码（时序高频极小值算法）
        global_mask_est = np.zeros((self.height, self.width), dtype=np.uint8)
        if method in ["inpaint", "lama"]:
            if full_mask_mode:
                for region in regions:
                    rx, ry, rw, rh = region['x'], region['y'], region['w'], region['h']
                    global_mask_est[ry:ry+rh, rx:rx+rw] = 255
            else:
                sample_count = min(15, self.total_frames)
                frame_indices = np.linspace(0, self.total_frames - 1, sample_count, dtype=int)
                high_passes = {i: [] for i in range(len(regions))}
                
                for idx in frame_indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ret, f = cap.read()
                    if ret:
                        for i, region in enumerate(regions):
                            rx, ry, rw, rh = region['x'], region['y'], region['w'], region['h']
                            roi_gray = cv2.cvtColor(f[ry:ry+rh, rx:rx+rw], cv2.COLOR_BGR2GRAY)
                            roi_blur = cv2.GaussianBlur(roi_gray, (25, 25), 0)
                            roi_hp = cv2.absdiff(roi_gray, roi_blur)
                            high_passes[i].append(roi_hp)
                
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                
                for i, region in enumerate(regions):
                    rx, ry, rw, rh = region['x'], region['y'], region['w'], region['h']
                    region_hps = high_passes[i]
                    if len(region_hps) > 0:
                        temporal_min = np.percentile(region_hps, 30, axis=0).astype(np.uint8)
                        _, mask_est = cv2.threshold(temporal_min, 4, 255, cv2.THRESH_BINARY)
                        
                        kernel_close = np.ones((3, 3), np.uint8)
                        mask_closed = cv2.morphologyEx(mask_est, cv2.MORPH_CLOSE, kernel_close)
                        
                        contours, _ = cv2.findContours(mask_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        mask_filled = np.zeros_like(mask_closed)
                        cv2.drawContours(mask_filled, contours, -1, 255, -1)
                        
                        dilate_size = max(5, feather + 2) 
                        kernel_dilate = np.ones((dilate_size, dilate_size), np.uint8)
                        mask_dilated = cv2.dilate(mask_filled, kernel_dilate, iterations=1)
                        
                        if np.sum(mask_dilated > 0) < (rw * rh * 0.01):
                            mask_dilated = np.ones((rh, rw), dtype=np.uint8) * 255
                        global_mask_est[ry:ry+rh, rx:rx+rw] = mask_dilated
        # 时序克隆特征与参考库初始化
        ref_frames = []
        ref_kp_des = []
        orb = None
        feat_mask = None
        bf = None
        
        if method == "temporal_clone":
            # 1. 预选 6 帧作为参考库
            ref_indices = [int(i) for i in np.linspace(0, self.total_frames - 1, 6)]
            
            # 特征提取的 mask，避开中间运动的物体（如打球的人），只取左边和顶部边缘作为干净背景参考物
            feat_mask = np.zeros((self.height, self.width), dtype=np.uint8)
            # 左部背景区
            feat_mask[int(self.height*0.08):int(self.height*0.9), 0:int(self.width*0.35)] = 255
            # 顶部背景区
            feat_mask[int(self.height*0.08):int(self.height*0.28), int(self.width*0.35):int(self.width*0.8)] = 255
            
            orb = cv2.ORB_create(nfeatures=1000)
            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
            
            for idx in ref_indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret_ref, f_ref = cap.read()
                if not ret_ref:
                    continue
                ref_frames.append((idx, f_ref))
                kp_r, des_r = orb.detectAndCompute(f_ref, mask=feat_mask)
                ref_kp_des.append((kp_r, des_r))
                
            # 重新卷回第 0 帧
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        # 初始化通用 mask
        mask = np.zeros((self.height, self.width), dtype=np.uint8)
        if method in ["inpaint", "lama"]:
            mask = global_mask_est.copy()
        else:
            for region in regions:
                x, y, w, h = region['x'], region['y'], region['w'], region['h']
                mask[y:y+h, x:x+w] = 255
                
        # 模糊的渐变羽化 mask
        feather_mask = np.zeros((self.height, self.width), dtype=np.float32)
        if feather > 0 and method in ["blur", "mosaic"]:
            for region in regions:
                x, y, w, h = region['x'], region['y'], region['w'], region['h']
                feather_mask[y:y+h, x:x+w] = 1.0
            blur_ksize = feather * 2 + 1
            feather_mask = cv2.GaussianBlur(feather_mask, (blur_ksize, blur_ksize), 0)
            feather_mask = np.expand_dims(feather_mask, axis=2)

        start_time = time.time()
        processed_frames = 0
        prev_repaired_crops = {}
        prev_orig_crops = {}
        
        try:
            while True:
                if jobs_status.get(job_id, {}).get("status") == "canceled":
                    raise InterruptedError("任务被用户取消")
                ret, frame = cap.read()
                if not ret:
                    break
                
                # 使用全局预计算的时序极小值掩码，无需逐帧重新计算，极大提高处理速度
                
                if method == "inpaint":
                    # Inpaint 支持全图，但为了效率我们只对各个矩形区域分别做
                    for region in regions:
                        x, y, w, h = region['x'], region['y'], region['w'], region['h']
                        margin = 15
                        ly = max(0, y - margin)
                        lx = max(0, x - margin)
                        lh = min(self.height - ly, h + margin * 2)
                        lw = min(self.width - lx, w + margin * 2)
                        
                        local_frame = frame[ly:ly+lh, lx:lx+lw]
                        local_mask = mask[ly:ly+lh, lx:lx+lw]
                        
                        if np.sum(local_mask) > 0:
                            inpainted_local = cv2.inpaint(local_frame, local_mask, inpaintRadius=1, flags=cv2.INPAINT_NS)
                            frame[ly:ly+lh, lx:lx+lw] = inpainted_local
                            
                elif method == "lama":
                    # LaMa AI 深度修复
                    lama_session = _get_lama_session()
                    if lama_session is not None:
                        for i, region in enumerate(regions):
                            x, y, w, h = region['x'], region['y'], region['w'], region['h']
                            crop_size = 512
                            # 以水印中心为基准，直接从帧中裁出 512x512 区域（无缩放！）
                            cx = x + w // 2
                            cy = y + h // 2
                            cx1 = max(0, cx - crop_size // 2)
                            cy1 = max(0, cy - crop_size // 2)
                            cx2 = min(self.width, cx1 + crop_size)
                            cy2 = min(self.height, cy1 + crop_size)
                            cx1 = max(0, cx2 - crop_size)
                            cy1 = max(0, cy2 - crop_size)
                            
                            # 直接从全帧 mask 裁出 512x512（与帧裁剪完全对齐）
                            crop_mask = mask[cy1:cy2, cx1:cx2]
                            if np.sum(crop_mask) == 0:
                                continue
                            
                            img_tensor = None
                            mask_tensor = None
                            result = None
                            try:
                                # 裁剪帧并转 RGB，归一化到 [0,1]
                                crop_bgr = frame[cy1:cy2, cx1:cx2].copy()
                                orig_crop = crop_bgr.copy()
                                crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
                                img_tensor = (crop_rgb.astype(np.float32) / 255.0)
                                img_tensor = np.transpose(img_tensor, (2, 0, 1))[np.newaxis, ...]
                                
                                mask_tensor = (crop_mask > 127).astype(np.float32)[np.newaxis, np.newaxis, ...]
                                
                                # 推理（输出为 [0,255] 范围）
                                inp_img = lama_session.get_inputs()[0].name
                                inp_mask = lama_session.get_inputs()[1].name
                                result = lama_session.run(None, {inp_img: img_tensor, inp_mask: mask_tensor})
                                
                                output = result[0][0]  # [3, 512, 512]
                                output = np.transpose(output, (1, 2, 0))  # -> [512, 512, 3]
                                output = np.clip(output, 0, 255).astype(np.uint8)
                                output_bgr = cv2.cvtColor(output, cv2.COLOR_RGB2BGR)
                                
                                # 仅替换 mask 区域像素（保留其余原始像素不变）
                                mask_bool = crop_mask > 0
                                for c in range(3):
                                    crop_bgr[:, :, c][mask_bool] = output_bgr[:, :, c][mask_bool]
                                    
                                # 💡 时序动态平滑滤波逻辑：消除独立帧推理引发的水波纹颤动
                                if i in prev_repaired_crops:
                                    diff = cv2.absdiff(orig_crop, prev_orig_crops[i])
                                    mean_diff = np.mean(diff)
                                    alpha = np.clip(mean_diff / 15.0, 0.15, 1.0)
                                    crop_bgr = cv2.addWeighted(crop_bgr, alpha, prev_repaired_crops[i], 1.0 - alpha, 0)
                                    
                                prev_repaired_crops[i] = crop_bgr.copy()
                                prev_orig_crops[i] = orig_crop.copy()
                                
                                frame[cy1:cy2, cx1:cx2] = crop_bgr
                            except Exception as e:
                                print(f"[LaMa Processing Error] {e}")
                                # 回退到 OpenCV inpaint
                                margin_fb = 15
                                ly = max(0, y - margin_fb)
                                lx = max(0, x - margin_fb)
                                lh = min(self.height - ly, h + margin_fb * 2)
                                lw = min(self.width - lx, w + margin_fb * 2)
                                local_frame = frame[ly:ly+lh, lx:lx+lw]
                                local_mask = mask[ly:ly+lh, lx:lx+lw]
                                if np.sum(local_mask) > 0:
                                    inpainted_local = cv2.inpaint(local_frame, local_mask, inpaintRadius=1, flags=cv2.INPAINT_NS)
                                    frame[ly:ly+lh, lx:lx+lw] = inpainted_local
                            finally:
                                # 释放大变量以防内存泄漏
                                if 'img_tensor' in locals(): del img_tensor
                                if 'mask_tensor' in locals(): del mask_tensor
                                if 'result' in locals(): del result
                                import gc
                                gc.collect()
                    else:
                        # LaMa 不可用时回退到 OpenCV inpaint
                        for region in regions:
                            x, y, w, h = region['x'], region['y'], region['w'], region['h']
                            margin_fb = 15
                            ly = max(0, y - margin_fb)
                            lx = max(0, x - margin_fb)
                            lh = min(self.height - ly, h + margin_fb * 2)
                            lw = min(self.width - lx, w + margin_fb * 2)
                            local_frame = frame[ly:ly+lh, lx:lx+lw]
                            local_mask = mask[ly:ly+lh, lx:lx+lw]
                            if np.sum(local_mask) > 0:
                                inpainted_local = cv2.inpaint(local_frame, local_mask, inpaintRadius=1, flags=cv2.INPAINT_NS)
                                frame[ly:ly+lh, lx:lx+lw] = inpainted_local
                    
                elif method == "blur":
                    for region in regions:
                        x, y, w, h = region['x'], region['y'], region['w'], region['h']
                        ksize = max(15, (w // 8) | 1)
                        blurred_roi = cv2.GaussianBlur(frame[y:y+h, x:x+w], (ksize, ksize), 0)
                        
                        if feather > 0:
                            roi = frame[y:y+h, x:x+w].astype(np.float32)
                            broi = blurred_roi.astype(np.float32)
                            f_roi = feather_mask[y:y+h, x:x+w]
                            mixed_roi = broi * f_roi + roi * (1.0 - f_roi)
                            frame[y:y+h, x:x+w] = np.clip(mixed_roi, 0, 255).astype(np.uint8)
                        else:
                            frame[y:y+h, x:x+w] = blurred_roi
                            
                elif method == "mosaic":
                    for region in regions:
                        x, y, w, h = region['x'], region['y'], region['w'], region['h']
                        roi = frame[y:y+h, x:x+w]
                        block_size = max(4, w // 15)
                        small = cv2.resize(roi, (max(1, w // block_size), max(1, h // block_size)), interpolation=cv2.INTER_LINEAR)
                        mosaic_roi = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
                        
                        if feather > 0:
                            roi_f = roi.astype(np.float32)
                            mroi_f = mosaic_roi.astype(np.float32)
                            f_roi = feather_mask[y:y+h, x:x+w]
                            mixed_roi = mroi_f * f_roi + roi_f * (1.0 - f_roi)
                            frame[y:y+h, x:x+w] = np.clip(mixed_roi, 0, 255).astype(np.uint8)
                        else:
                            frame[y:y+h, x:x+w] = mosaic_roi
                
                out.write(frame)
                processed_frames += 1
                
                # LaMa 每帧约2秒较慢，每帧都更新进度；其他方法每15帧更新
                update_interval = 1 if method == "lama" else 15
                if processed_frames % update_interval == 0 or processed_frames == self.total_frames:
                    progress = int((processed_frames / self.total_frames) * 100)
                    elapsed = time.time() - start_time
                    fps_calc = processed_frames / elapsed if elapsed > 0 else 1.0
                    eta = int((self.total_frames - processed_frames) / fps_calc) if fps_calc > 0 else 0
                    
                    preview_h = 180
                    preview_w = int((preview_h / self.height) * self.width)
                    small_frame = cv2.resize(frame, (preview_w, preview_h))
                    _, buf = cv2.imencode('.jpg', small_frame)
                    preview_b64 = base64.b64encode(buf).decode('utf-8')
                    
                    update_job_status(job_id, progress=progress, eta=eta, preview_frame=preview_b64)
                    
            cap.release()
            out.release()
            
            # 使用 FFmpeg 重新打包，对其重新编码为高兼容性 H.264/AAC，保证能在所有 HTML5 网页播放器中流畅播放
            ffmpeg_path = self.get_ffmpeg_path()
            ffmpeg_success = False
            if ffmpeg_path:
                if jobs_status.get(job_id, {}).get("status") == "canceled":
                    raise InterruptedError("任务被用户取消")
                print("正在通过 FFmpeg 合并音轨并导出视觉无损且高兼容性的视频 (H.264/AAC)...")
                # 方案 A：转码为标准的 AAC (保证各浏览器兼容性)
                cmd_a = [
                    ffmpeg_path, "-y",
                    "-i", temp_output_path,
                    "-i", self.video_path,
                    "-map", "0:v",
                    "-map", "1:a?",
                    "-c:v", "libx264",
                    "-crf", "12",  # 视觉无损画质
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",  # 转码为标准的 AAC
                    "-b:a", "192k",
                    "-shortest",
                    output_path
                ]
                
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    
                proc = subprocess.Popen(cmd_a, startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                with active_processes_lock:
                    if jobs_status.get(job_id, {}).get("status") == "canceled":
                        proc.terminate()
                    else:
                        active_processes[job_id] = proc
                
                try:
                    while proc.poll() is None:
                        if jobs_status.get(job_id, {}).get("status") == "canceled":
                            proc.terminate()
                            proc.wait()
                            break
                        time.sleep(0.1)
                finally:
                    with active_processes_lock:
                        active_processes.pop(job_id, None)
                
                if jobs_status.get(job_id, {}).get("status") == "canceled":
                    raise InterruptedError("任务被用户取消")
                
                if proc.returncode == 0 and os.path.exists(output_path):
                    update_job_status(job_id, ffmpeg_used=True)
                    ffmpeg_success = True
                else:
                    # 方案 B：直接复制音频轨道作为备用方案
                    if jobs_status.get(job_id, {}).get("status") == "canceled":
                        raise InterruptedError("任务被用户取消")
                    print("FFmpeg 方案 A (AAC 转码) 失败，尝试方案 B (音频 copy)...")
                    cmd_b = [
                        ffmpeg_path, "-y",
                        "-i", temp_output_path,
                        "-i", self.video_path,
                        "-map", "0:v",
                        "-map", "1:a?",
                        "-c:v", "libx264",
                        "-crf", "12",
                        "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p",
                        "-c:a", "copy",
                        "-shortest",
                        output_path
                    ]
                    proc_b = subprocess.Popen(cmd_b, startupinfo=startupinfo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    with active_processes_lock:
                        if jobs_status.get(job_id, {}).get("status") == "canceled":
                            proc_b.terminate()
                        else:
                            active_processes[job_id] = proc_b
                    
                    try:
                        while proc_b.poll() is None:
                            if jobs_status.get(job_id, {}).get("status") == "canceled":
                                proc_b.terminate()
                                proc_b.wait()
                                break
                            time.sleep(0.1)
                    finally:
                        with active_processes_lock:
                            active_processes.pop(job_id, None)
                            
                    if jobs_status.get(job_id, {}).get("status") == "canceled":
                        raise InterruptedError("任务被用户取消")
                        
                    if proc_b.returncode == 0 and os.path.exists(output_path):
                        update_job_status(job_id, ffmpeg_used=True)
                        ffmpeg_success = True
            
            # 如果 FFmpeg 重新打包成功，清除临时无声文件
            if ffmpeg_success:
                try:
                    os.remove(temp_output_path)
                except:
                    pass
            else:
                # 如果 FFmpeg 重新打包失败或不可用，回退到无声视频
                print("FFmpeg 合并失败或不可用，将回退到无声视频作为最终输出")
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except:
                        pass
                if os.path.exists(temp_output_path):
                    shutil.move(temp_output_path, output_path)
                else:
                    raise RuntimeError("视频帧处理后的临时文件丢失，无法生成最终视频")
            
            if jobs_status.get(job_id, {}).get("status") == "canceled":
                raise InterruptedError("任务被用户取消")
            update_job_status(job_id, progress=100, status="completed", eta=0)
            
        except Exception as e:
            cap.release()
            try:
                out.release()
            except:
                pass
            if os.path.exists(temp_output_path):
                try:
                    os.remove(temp_output_path)
                except Exception:
                    pass
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass
            if jobs_status.get(job_id, {}).get("status") == "canceled":
                pass
            else:
                update_job_status(job_id, status="failed", error_message=str(e))
        finally:
            cleanup_lama_session()
