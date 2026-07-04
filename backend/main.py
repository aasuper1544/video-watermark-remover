import os
import uuid
import shutil
import time
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

def cleanup_old_files(max_age_seconds: int = 7200):
    """自动清理上传目录和输出目录中超过 2 小时未被修改的文件"""
    now = time.time()
    for directory in [UPLOAD_DIR, OUTPUT_DIR]:
        if not os.path.exists(directory):
            continue
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            try:
                # 排除正在生成的文件
                if filename.startswith("temp_"):
                    continue
                if os.path.isfile(filepath):
                    if now - os.path.getmtime(filepath) > max_age_seconds:
                        os.remove(filepath)
            except Exception as e:
                print(f"自动清理文件 {filename} 失败: {e}")

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

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    """上传视频，生成首帧预览图并返回视频信息"""
    try:
        cleanup_old_files()
    except Exception as e:
        print(f"自动清理历史文件失败: {e}")
        
    if not file.filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.flv')):
        raise HTTPException(status_code=400, detail="不支持的视频文件格式")
        
    video_id = str(uuid.uuid4())
    file_ext = os.path.splitext(file.filename)[1]
    video_path = os.path.join(UPLOAD_DIR, f"{video_id}{file_ext}")
    
    # 写入磁盘
    with open(video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        remover = WatermarkRemover(video_path, OUTPUT_DIR)
        uploaded_videos[video_id] = video_path
        
        # 获取第一帧的 Base64 编码
        preview_b64 = remover.get_preview_frame(0)
        
        return {
            "success": True,
            "video_id": video_id,
            "width": remover.width,
            "height": remover.height,
            "fps": remover.fps,
            "total_frames": remover.total_frames,
            "preview_frame": preview_b64
        }
    except Exception as e:
        # 清理坏文件
        if os.path.exists(video_path):
            os.remove(video_path)
        raise HTTPException(status_code=500, detail=f"无法解析视频: {str(e)}")

@app.post("/api/remove-watermark")
async def remove_watermark(req: WatermarkRequest):
    """请求去水印处理任务"""
    video_id = req.video_id
    if video_id not in uploaded_videos:
        raise HTTPException(status_code=404, detail="视频未找到，请重新上传")
        
    video_path = uploaded_videos[video_id]
    job_id = str(uuid.uuid4())
    
    try:
        remover = WatermarkRemover(video_path, OUTPUT_DIR)
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

@app.post("/api/preview-frame")
async def preview_frame(req: PreviewRequest):
    video_id = req.video_id
    if video_id not in uploaded_videos:
        raise HTTPException(status_code=404, detail="视频未找到，请重新上传")
        
    video_path = uploaded_videos[req.video_id]
    try:
        print(f"[DEBUG PREVIEW] Received request: regions={req.regions}, method='{req.method}', feather={req.feather}, frame_index={req.frame_index}")
        remover = WatermarkRemover(video_path, OUTPUT_DIR)
        preview_b64 = remover.generate_preview_frame(
            regions=[{"x": r.x, "y": r.y, "w": r.w, "h": r.h} for r in req.regions],
            method=req.method,
            feather=req.feather,
            frame_index=req.frame_index
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
    if video_id not in uploaded_videos:
        raise HTTPException(status_code=404, detail="视频未找到，请重新上传")
        
    video_path = uploaded_videos[video_id]
    try:
        remover = WatermarkRemover(video_path, OUTPUT_DIR)
        b64_str = remover.get_preview_frame(frame_index)
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
    return status_info

@app.get("/api/diag")
async def get_diag():
    """诊断接口：获取内存中的任务列表和视频列表"""
    # 过滤掉 preview_frame（因为非常大）以防日志刷屏
    safe_jobs = {}
    for jid, job in jobs_status.items():
        job_copy = job.copy()
        if "preview_frame" in job_copy:
            job_copy["preview_frame"] = job_copy["preview_frame"][:10] + "..."
        safe_jobs[jid] = job_copy
    return {
        "uploaded_videos": uploaded_videos,
        "jobs_status": safe_jobs
    }

@app.get("/api/download/{job_id}")
async def download_file(job_id: str):
    """下载或在线播放处理完成的视频"""
    status_info = get_job_status(job_id)
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

# 挂载前端静态文件
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>前端页面未生成，请稍后刷新</h1>"

# 备用静态目录挂载（处理 CSS, JS 等）
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
