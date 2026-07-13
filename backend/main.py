import os
import uuid
import shutil
import time
import asyncio
import threading
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from .remover import WatermarkRemover, get_job_status, jobs_status

app = FastAPI(title="Video Watermark Remover API")

# 配置 CORS，允许前端本地直接访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = "D:/video-watermark-remover"
UPLOAD_DIR = os.path.join(BASE_DIR, "temp_uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "processed_outputs")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(FRONTEND_DIR, exist_ok=True)

active_uploads = set()
uploads_lock = threading.Lock()

def cleanup_old_files(max_age_seconds: int = 600):
    """自动清理上传目录、处理结果输出目录中超过 10 分钟未被修改的文件，线程安全且不会删除活跃文件"""
    now = time.time()
    
    # 收集当前所有活跃的文件（上传中、处理中）
    active_files = set()
    
    with uploads_lock:
        for filepath in active_uploads:
            active_files.add(os.path.abspath(filepath).lower())
            
    # 从 remover 模块导入 jobs_status 和 jobs_lock
    from .remover import jobs_status, jobs_lock
    
    with jobs_lock:
        jobs_snapshot = list(jobs_status.items())
        
    for job_id, info in jobs_snapshot:
        if info.get("status") in ["processing", "pending"]:
            # 活跃的输入文件
            v_path = info.get("video_path")
            if v_path:
                active_files.add(os.path.abspath(v_path).lower())
            # 活跃的输出文件
            out_filename = f"processed_{job_id}.mp4"
            out_filepath = os.path.join(OUTPUT_DIR, out_filename)
            active_files.add(os.path.abspath(out_filepath).lower())
            # 活跃的临时文件
            temp_filename = f"temp_{job_id}.mp4"
            temp_filepath = os.path.join(OUTPUT_DIR, temp_filename)
            active_files.add(os.path.abspath(temp_filepath).lower())
            
    # 清理过期文件
    for directory in [UPLOAD_DIR, OUTPUT_DIR, os.path.join(BASE_DIR, "output")]:
        if not os.path.exists(directory):
            continue
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            abs_filepath = os.path.abspath(filepath).lower()
            
            # 如果是活跃文件，跳过清理
            if abs_filepath in active_files:
                continue
                
            try:
                if os.path.isfile(filepath):
                    if now - os.path.getmtime(filepath) > max_age_seconds:
                        os.remove(filepath)
            except Exception as e:
                print(f"自动清理文件 {filename} 失败: {e}")
                
    # 清理 uploaded_videos 中已被物理删除的键值对，防止内存泄露
    with uploads_lock:
        to_delete_ids = []
        for vid, path in list(uploaded_videos.items()):
            if not os.path.exists(path):
                to_delete_ids.append(vid)
        for vid in to_delete_ids:
            uploaded_videos.pop(vid, None)

async def cleanup_scheduler():
    """后台定时任务：每 60 秒运行一次，清理超过 10 分钟的文件和释放空闲模型内存"""
    loop = asyncio.get_running_loop()
    while True:
        try:
            await loop.run_in_executor(None, cleanup_old_files, 600)
        except Exception as e:
            print(f"自动清理历史文件失败: {e}")
            
        try:
            from .remover import cleanup_lama_session
            await loop.run_in_executor(None, cleanup_lama_session)
        except Exception as e:
            print(f"清理 LaMa ONNX 会话内存失败: {e}")
            
        await asyncio.sleep(60)

@app.on_event("startup")
async def start_services():
    asyncio.create_task(cleanup_scheduler())
    from .remover import start_queue_worker
    start_queue_worker()

# 临时视频映射：video_id -> video_file_path
uploaded_videos = {}

from typing import List

class Region(BaseModel):
    x: int
    y: int
    w: int
    h: int

class WatermarkRequest(BaseModel):
    video_id: str
    regions: List[Region]
    method: str = "inpaint"
    feather: int = 5

class PreviewRequest(BaseModel):
    video_id: str
    regions: List[Region]
    method: str = "inpaint"
    feather: int = 5
    frame_index: int = 0

class ZipRequest(BaseModel):
    job_ids: List[str]

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    """上传视频，生成首帧预览图并返回视频信息"""
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, cleanup_old_files)
    except Exception as e:
        print(f"自动清理历史文件失败: {e}")
        
    if not file.filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.flv')):
        raise HTTPException(status_code=400, detail="不支持的视频文件格式")
        
    video_id = str(uuid.uuid4())
    file_ext = os.path.splitext(file.filename)[1]
    video_path = os.path.abspath(os.path.join(UPLOAD_DIR, f"{video_id}{file_ext}"))
    
    with uploads_lock:
        active_uploads.add(video_path)
        
    # 写入磁盘 (分块读取写入，防止大视频内存暴涨)
    chunk_size = 1024 * 1024  # 1MB chunks
    try:
        with open(video_path, "wb") as buffer:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                buffer.write(chunk)
    except Exception as e:
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"视频上传写入失败: {str(e)}")
        
    try:
        # 在 Executor 线程池中初始化 WatermarkRemover 并获取预览帧，避免阻塞 event loop
        remover = await loop.run_in_executor(None, WatermarkRemover, video_path, OUTPUT_DIR)
        with uploads_lock:
            uploaded_videos[video_id] = video_path
        
        # 获取第一帧的 Base64 编码
        preview_b64 = await loop.run_in_executor(None, remover.get_preview_frame, 0)
        
        return {
            "success": True,
            "video_id": video_id,
            "width": remover.width,
            "height": remover.height,
            "fps": remover.fps,
            "total_frames": remover.total_frames,
            "preview_frame": preview_b64
        }
    except ValueError as e:
        # 清理坏文件
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=f"无法解析视频: {str(e)}")
    except Exception as e:
        # 清理坏文件
        if os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"无法解析视频: {str(e)}")
    finally:
        with uploads_lock:
            active_uploads.discard(video_path)

@app.post("/api/remove-watermark")
async def remove_watermark(req: WatermarkRequest):
    """请求去水印处理任务"""
    video_id = req.video_id
    with uploads_lock:
        video_exists = video_id in uploaded_videos
        video_path = uploaded_videos.get(video_id)
        
    if not video_exists:
        raise HTTPException(status_code=404, detail="视频未找到，请重新上传")
        
    job_id = str(uuid.uuid4())
    
    try:
        loop = asyncio.get_running_loop()
        remover = await loop.run_in_executor(None, WatermarkRemover, video_path, OUTPUT_DIR)
        # 启动后台去水印任务
        regions_dicts = [{"x": r.x, "y": r.y, "w": r.w, "h": r.h} for r in req.regions]
        remover.process(
            job_id=job_id,
            regions=regions_dicts,
            method=req.method,
            feather=req.feather
        )
        return {
            "success": True,
            "job_id": job_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"任务启动失败: {str(e)}")

@app.post("/api/cancel/{job_id}")
async def cancel_task(job_id: str):
    """取消进行中的去水印任务"""
    from .remover import cancel_job
    success = cancel_job(job_id)
    if not success:
        status_info = get_job_status(job_id)
        if status_info.get("status") == "not_found":
            raise HTTPException(status_code=404, detail="任务未找到")
        else:
            raise HTTPException(status_code=400, detail=f"无法取消任务，当前状态为: {status_info.get('status')}")
    return {"success": True, "message": "任务已成功取消"}

@app.post("/api/preview-frame")
async def preview_frame(req: PreviewRequest):
    video_id = req.video_id
    with uploads_lock:
        video_exists = video_id in uploaded_videos
        video_path = uploaded_videos.get(video_id)
        
    if not video_exists:
        raise HTTPException(status_code=404, detail="视频未找到，请重新上传")
        
    try:
        print(f"[DEBUG PREVIEW] Received request: regions={req.regions}, method='{req.method}', feather={req.feather}, frame_index={req.frame_index}")
        loop = asyncio.get_running_loop()
        remover = await loop.run_in_executor(None, WatermarkRemover, video_path, OUTPUT_DIR)
        
        regions_list = [{"x": r.x, "y": r.y, "w": r.w, "h": r.h} for r in req.regions]
        preview_b64 = await loop.run_in_executor(
            None,
            remover.generate_preview_frame,
            regions_list,
            req.method,
            req.feather,
            req.frame_index
        )
        print(f"[DEBUG PREVIEW] Success! Generated preview base64 length: {len(preview_b64)}")
        return {
            "success": True,
            "preview_frame": preview_b64
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"预览生成失败: {str(e)}")

@app.get("/api/frame/{video_id}")
async def get_frame(video_id: str, frame_index: int = 0):
    """获取视频任意一帧的 Base64 编码以供前端时间轴显示"""
    with uploads_lock:
        video_exists = video_id in uploaded_videos
        video_path = uploaded_videos.get(video_id)
        
    if not video_exists:
        raise HTTPException(status_code=404, detail="视频未找到，请重新上传")
        
    try:
        loop = asyncio.get_running_loop()
        remover = await loop.run_in_executor(None, WatermarkRemover, video_path, OUTPUT_DIR)
        b64_str = await loop.run_in_executor(None, remover.get_preview_frame, frame_index)
        return {
            "success": True,
            "frame": b64_str
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取帧失败: {str(e)}")

@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """查询任务进度和状态"""
    status_info = get_job_status(job_id)
    if status_info.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="任务未找到")
    return status_info

@app.get("/api/diag")
async def get_diag():
    """诊断接口：获取内存中的任务列表和视频列表"""
    # 过滤掉 preview_frame（因为非常大）以防日志刷屏
    from .remover import jobs_lock
    
    with uploads_lock:
        uploaded_videos_copy = uploaded_videos.copy()
        
    with jobs_lock:
        safe_jobs = {}
        for jid, job in jobs_status.items():
            job_copy = job.copy()
            if "preview_frame" in job_copy:
                job_copy["preview_frame"] = job_copy["preview_frame"][:10] + "..."
            safe_jobs[jid] = job_copy
            
    return {
        "uploaded_videos": uploaded_videos_copy,
        "jobs_status": safe_jobs
    }

@app.get("/api/download/{job_id}")
async def download_file(job_id: str):
    """下载或在线播放处理完成的视频"""
    status_info = get_job_status(job_id)
    if status_info.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="任务未找到")
    if status_info.get("status") != "completed":
        raise HTTPException(status_code=400, detail="视频尚在处理中，无法下载")
        
    filename = f"processed_{job_id}.mp4"
    filepath = os.path.join(OUTPUT_DIR, filename)
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件不存在或已被清理")
        
    # 为了方便浏览器直接播放，如果是 mp4 且 ffmpeg 合并成功，我们返回 video/mp4，否则视情况返回
    return FileResponse(
        path=filepath,
        filename="video_no_watermark.mp4",
        media_type="video/mp4"
    )

@app.post("/api/download-zip")
async def download_zip(req: ZipRequest, background_tasks: BackgroundTasks):
    """打包多个处理完成的视频并作为 ZIP 压缩包下载"""
    import tempfile
    import zipfile
    
    files_to_zip = []
    for job_id in req.job_ids:
        status_info = get_job_status(job_id)
        if status_info.get("status") == "completed":
            filename = f"processed_{job_id}.mp4"
            filepath = os.path.join(OUTPUT_DIR, filename)
            if os.path.exists(filepath):
                # 尝试获取原始视频名，增强打包文件的可读性
                orig_path = status_info.get("video_path")
                orig_name = os.path.basename(orig_path) if orig_path else f"{job_id}.mp4"
                name_base, _ = os.path.splitext(orig_name)
                files_to_zip.append((filepath, f"no_watermark_{name_base}.mp4"))
                
    if not files_to_zip:
        raise HTTPException(status_code=400, detail="没有可用于打包的已完成任务")
        
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_zip_path = temp_zip.name
    temp_zip.close()
    
    def create_zip():
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for filepath, arcname in files_to_zip:
                zipf.write(filepath, arcname)
                
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, create_zip)
    
    def remove_temp_file():
        try:
            if os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)
        except Exception as e:
            print(f"清理临时 ZIP 文件失败: {e}")
            
    background_tasks.add_task(remove_temp_file)
    
    return FileResponse(
        path=temp_zip_path,
        filename="processed_videos.zip",
        media_type="application/zip"
    )

# 挂载前端静态文件
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    
    def read_index():
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                return f.read()
        return None
        
    loop = asyncio.get_running_loop()
    content = await loop.run_in_executor(None, read_index)
    if content is not None:
        return content
    return "<h1>前端页面未生成，请稍后刷新</h1>"

# 备用静态目录挂载（处理 CSS, JS 等）
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
