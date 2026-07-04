@echo off
title Antigravity Video Watermark Remover
color 0A

echo =======================================================
echo           Video Watermark Remover (V1.0)
echo =======================================================
echo.
echo [1/3] Switching directory...
cd /d "D:\video-watermark-remover"

echo [2/3] Checking Python dependencies...
python -c "import fastapi, uvicorn, cv2, numpy, multipart, imageio_ffmpeg, onnxruntime" >nul 2>&1
if %errorlevel% neq 0 (
    echo Python dependencies are missing, installing automatically...
    pip install fastapi uvicorn opencv-python numpy python-multipart imageio-ffmpeg onnxruntime
) else (
    echo [OK] Dependencies checked!
)

echo [3/3] Starting backend server...
echo Note: The browser will open http://127.0.0.1:8000 automatically.
echo Please DO NOT close this command window.
echo.

start "" "http://127.0.0.1:8000"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

pause
