document.addEventListener('DOMContentLoaded', () => {
    // 状态变量
    let currentVideoId = null;
    let videoWidth = 0;
    let videoHeight = 0;
    let videoFps = 30;
    let videoTotalFrames = 0;
    let canvasWidth = 0;
    let canvasHeight = 0;
    let previewImage = new Image(); // 缓存首帧图像
    let currentJobId = null;
    let pollInterval = null;

    // DOM 元素
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file-input');
    const previewCanvas = document.getElementById('preview-canvas');
    const ctx = previewCanvas.getContext('2d');
    const videoDimsBadge = document.getElementById('video-dims');
    const timelineContainer = document.getElementById('timeline-container');
    const timelineSlider = document.getElementById('timeline-slider');
    const timeDisplay = document.getElementById('time-display');
    const comparisonView = document.getElementById('comparison-view');
    const afterImage = document.getElementById('after-image');
    const btnPreviewFrame = document.getElementById('btn-preview-frame');
    const btnStart = document.getElementById('btn-start');
    const btnResetUpload = document.getElementById('btn-reset-upload');
    const btnRestart = document.getElementById('btn-restart');
    const btnDownload = document.getElementById('btn-download');
    const selectMethod = document.getElementById('select-method');
    const inputFeather = document.getElementById('input-feather');
    const progressFill = document.getElementById('progress-fill');
    const progressPercent = document.getElementById('progress-percent');
    const progressEta = document.getElementById('progress-eta');
    const realtimeImg = document.getElementById('realtime-preview-img');
    const resultVideoPlayer = document.getElementById('result-video-player');
    const ffmpegWarning = document.getElementById('ffmpeg-warning');

    // 新增交互元素
    const canvasLoader = document.getElementById('canvas-loader');
    const canvasLoaderText = document.getElementById('canvas-loader-text');
    const frameLoadingSpinner = document.getElementById('frame-loading-spinner');
    const beforeImage = document.getElementById('before-image');

    // --- 吐司提示系统 ---
    function showToast(message, type = 'error', duration = 4000) {
        let toastContainer = document.getElementById('toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'toast-container';
            toastContainer.className = 'toast-container';
            document.body.appendChild(toastContainer);
        }

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        let iconClass = 'fa-solid fa-circle-exclamation';
        if (type === 'success') iconClass = 'fa-solid fa-circle-check';
        if (type === 'warning') iconClass = 'fa-solid fa-triangle-exclamation';
        if (type === 'info') iconClass = 'fa-solid fa-circle-info';

        toast.innerHTML = `
            <i class="${iconClass} toast-icon"></i>
            <div class="toast-content">${message}</div>
            <button class="toast-close">&times;</button>
        `;

        toastContainer.appendChild(toast);

        // 触发入场动画
        setTimeout(() => {
            toast.classList.add('show');
        }, 10);

        // 定时自动关闭
        let dismissTimeout = setTimeout(() => {
            dismissToast(toast);
        }, duration);

        // 手动关闭按钮
        const closeBtn = toast.querySelector('.toast-close');
        closeBtn.addEventListener('click', () => {
            clearTimeout(dismissTimeout);
            dismissToast(toast);
        });
    }

    function dismissToast(toast) {
        toast.classList.remove('show');
        toast.classList.add('hide');
        const onTransitionEnd = () => {
            toast.remove();
            toast.removeEventListener('transitionend', onTransitionEnd);
        };
        toast.addEventListener('transitionend', onTransitionEnd);
    }

    const steps = {
        upload: document.getElementById('step-upload'),
        configure: document.getElementById('step-configure'),
        processing: document.getElementById('step-processing'),
        result: document.getElementById('step-result')
    };

    // 切换步骤函数
    function showStep(stepName) {
        Object.keys(steps).forEach(key => {
            if (key === stepName) {
                steps[key].classList.add('active');
            } else {
                steps[key].classList.remove('active');
            }
        });
    }

    // --- 步骤 1：文件上传逻辑 ---
    
    // 拖拽文件样式交互
    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });
    
    dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('dragover');
    });
    
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            handleVideoUpload(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleVideoUpload(e.target.files[0]);
        }
    });

    // 统一文件上传处理
    function handleVideoUpload(file) {
        // 创建 FormData 上传
        const formData = new FormData();
        formData.append('file', file);

        // 显示加载态 (优化为 futuristic loader spinner)
        dropzone.innerHTML = `
            <div class="loader-spinner" style="margin: 0 auto 15px;"></div>
            <h3>正在上传并解析视频...</h3>
            <p style="color: var(--text-muted); font-size: 0.9rem;">由于需要读取视频流并生成首帧预览图，请耐心等待几秒钟</p>
        `;

        fetch('/api/upload', {
            method: 'POST',
            body: formData
        })
        .then(res => {
            if (!res.ok) {
                return res.json().then(err => { throw new Error(err.detail || '上传失败') });
            }
            return res.json();
        })
        .then(data => {
            currentVideoId = data.video_id;
            videoWidth = data.width;
            videoHeight = data.height;
            videoFps = data.fps;
            videoTotalFrames = data.total_frames;
            videoDimsBadge.textContent = `${videoWidth} x ${videoHeight} (${data.fps.toFixed(1)} FPS)`;
            
            // 初始化时间轴
            if (videoTotalFrames > 0) {
                timelineSlider.max = videoTotalFrames - 1;
                timelineSlider.value = 0;
                timelineContainer.style.display = 'block';
                updateTimeDisplay(0, videoFps, videoTotalFrames);
            }
            
            // 加载第一帧图像
            previewImage.onload = () => {
                initCanvas();
                showStep('configure');
            };
            previewImage.src = 'data:image/jpeg;base64,' + data.preview_frame;
        })
        .catch(err => {
            showToast('上传解析失败: ' + err.message, 'error');
            // 恢复上传区初始 HTML
            resetUploadZone();
        });
    }

    function resetUploadZone() {
        dropzone.innerHTML = `
            <input type="file" id="file-input" accept="video/*" style="display: none;">
            <div class="upload-icon">
                <i class="fa-solid fa-cloud-arrow-up"></i>
            </div>
            <h3>拖拽视频文件到此处</h3>
            <p>或者 <label for="file-input" class="browse-btn" style="cursor: pointer;">浏览本地文件</label></p>
            <div class="formats-info">支持 MP4, AVI, MOV, MKV 等常见视频格式</div>
        `;
        // 重新绑定 input file 事件
        const newFileInput = document.getElementById('file-input');
        newFileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                handleVideoUpload(e.target.files[0]);
            }
        });
    }

    // --- 步骤 2：画布选区逻辑 ---

    // 初始化画布与选区位置
    function initCanvas() {
        // 设置 Canvas 尺寸（根据容器最大宽度和视频比例自适应）
        const container = document.getElementById('canvas-container');
        const maxDisplayWidth = Math.min(container.parentElement.clientWidth || 600, 680);
        
        const aspect = videoWidth / videoHeight;
        canvasWidth = maxDisplayWidth;
        canvasHeight = maxDisplayWidth / aspect;
        
        previewCanvas.width = canvasWidth;
        previewCanvas.height = canvasHeight;
        
        // 强制容器宽高与 Canvas 像素尺寸一致，保证定位无偏差
        container.style.width = `${canvasWidth}px`;
        container.style.height = `${canvasHeight}px`;
        
        // 绘制图像
        ctx.drawImage(previewImage, 0, 0, canvasWidth, canvasHeight);
        
        // 默认预设：右下角
        applyPreset('bottom-right');
        
    }

    // 预设比例定义
    const presets = {
        'bottom-right': { x: 0.80, y: 0.82, w: 0.18, h: 0.15 },
        'top-right':    { x: 0.80, y: 0.03, w: 0.18, h: 0.15 },
        'bottom-left':  { x: 0.02, y: 0.82, w: 0.18, h: 0.15 }
    };

    function applyPreset(presetName) {
        if (presetName === 'manual') {
            // 自定义居中
            setBoxPercent(0.40, 0.40, 0.20, 0.20);
            return;
        }
        
        const p = presets[presetName];
        if (p) {
            setBoxPercent(p.x, p.y, p.w, p.h);
        }
    }

    // 依据百分比设置选区框的位置和尺寸
    function setBoxPercent(xPct, yPct, wPct, hPct) {
        const x = xPct * canvasWidth;
        const y = yPct * canvasHeight;
        const w = wPct * canvasWidth;
        const h = hPct * canvasHeight;
        
        selectionBoxes.forEach(b => b.remove());
        selectionBoxes = [];
        const box = createSelectionBox();
        box.style.left = `${x}px`;
        box.style.top = `${y}px`;
        box.style.width = `${w}px`;
        box.style.height = `${h}px`;
    }

    // 预设按钮事件绑定
    document.querySelectorAll('.btn-preset').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.btn-preset').forEach(b => b.classList.remove('active'));
            e.currentTarget.classList.add('active');
            const presetName = e.currentTarget.dataset.preset;
            applyPreset(presetName);
        });
    });

    let selectionBoxes = [];
    const canvasContainer = document.getElementById('canvas-container');

    function createSelectionBox() {
        const box = document.createElement('div');
        box.className = 'selection-box';
        box.innerHTML = `
            <div class="resize-handle nw"></div>
            <div class="resize-handle ne"></div>
            <div class="resize-handle sw"></div>
            <div class="resize-handle se"></div>
            <div class="close-btn" style="position:absolute; top:-10px; right:-10px; background:red; color:white; width:20px; height:20px; border-radius:50%; text-align:center; cursor:pointer; font-size:14px; line-height:18px; z-index:100;">&times;</div>
        `;
        canvasContainer.appendChild(box);
        
        const closeBtn = box.querySelector('.close-btn');
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (selectionBoxes.length > 1) {
                box.remove();
                selectionBoxes = selectionBoxes.filter(b => b !== box);
            } else {
                showToast("至少需要保留一个去水印区域！", "warning");
            }
        });

        // Initialize drag & resize for this box
        let isDragging = false;
        let isResizing = false;
        let activeHandle = null;
        let startX, startY, startLeft, startTop, startWidth, startHeight;

        box.addEventListener('mousedown', (e) => {
            if (e.target.classList.contains('close-btn')) return;

            if (e.target.classList.contains('resize-handle')) {
                isResizing = true;
                activeHandle = e.target;
            } else {
                isDragging = true;
                setActivePresetButton('manual');
            }
            
            startX = e.clientX;
            startY = e.clientY;
            startLeft = parseFloat(box.style.left) || 0;
            startTop = parseFloat(box.style.top) || 0;
            startWidth = parseFloat(box.style.width) || 100;
            startHeight = parseFloat(box.style.height) || 50;
            
            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!isDragging && !isResizing) return;
            
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            
            if (isDragging) {
                let left = startLeft + dx;
                let top = startTop + dy;
                
                const maxLeft = canvasWidth - startWidth;
                const maxTop = canvasHeight - startHeight;
                
                left = Math.max(0, Math.min(left, maxLeft));
                top = Math.max(0, Math.min(top, maxTop));
                
                box.style.left = `${left}px`;
                box.style.top = `${top}px`;
            } else if (isResizing) {
                setActivePresetButton('manual');

                let left = startLeft;
                let top = startTop;
                let width = startWidth;
                let height = startHeight;
                
                if (activeHandle.classList.contains('se')) {
                    width = Math.max(20, startWidth + dx);
                    height = Math.max(20, startHeight + dy);
                    width = Math.min(width, canvasWidth - startLeft);
                    height = Math.min(height, canvasHeight - startTop);
                } else if (activeHandle.classList.contains('sw')) {
                    const possibleWidth = startWidth - dx;
                    if (possibleWidth > 20) {
                        const newLeft = Math.max(0, startLeft + dx);
                        width = startWidth + (startLeft - newLeft);
                        left = newLeft;
                    }
                    height = Math.max(20, startHeight + dy);
                    height = Math.min(height, canvasHeight - startTop);
                } else if (activeHandle.classList.contains('ne')) {
                    width = Math.max(20, startWidth + dx);
                    width = Math.min(width, canvasWidth - startLeft);
                    const possibleHeight = startHeight - dy;
                    if (possibleHeight > 20) {
                        const newTop = Math.max(0, startTop + dy);
                        height = startHeight + (startTop - newTop);
                        top = newTop;
                    }
                } else if (activeHandle.classList.contains('nw')) {
                    const possibleWidth = startWidth - dx;
                    if (possibleWidth > 20) {
                        const newLeft = Math.max(0, startLeft + dx);
                        width = startWidth + (startLeft - newLeft);
                        left = newLeft;
                    }
                    const possibleHeight = startHeight - dy;
                    if (possibleHeight > 20) {
                        const newTop = Math.max(0, startTop + dy);
                        height = startHeight + (startTop - newTop);
                        top = newTop;
                    }
                }
                
                box.style.left = `${left}px`;
                box.style.top = `${top}px`;
                box.style.width = `${width}px`;
                box.style.height = `${height}px`;
            }
        });

        document.addEventListener('mouseup', () => {
            if (isDragging || isResizing) {
                isDragging = false;
                isResizing = false;
                activeHandle = null;
            }
        });

        selectionBoxes.push(box);
        return box;
    }

    const btnAddRegion = document.getElementById('btn-add-region');
    if (btnAddRegion) {
        btnAddRegion.addEventListener('click', () => {
            const box = createSelectionBox();
            // Default position in center
            box.style.left = `${canvasWidth * 0.4}px`;
            box.style.top = `${canvasHeight * 0.4}px`;
            box.style.width = `${canvasWidth * 0.2}px`;
            box.style.height = `${canvasHeight * 0.2}px`;
            setActivePresetButton('manual');
        });
    }


    // 辅助切换预设高亮
    function setActivePresetButton(presetName) {
        document.querySelectorAll('.btn-preset').forEach(btn => {
            if (btn.dataset.preset === presetName) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }

    function formatTime(seconds) {
        const m = Math.floor(seconds / 60).toString().padStart(2, '0');
        const s = Math.floor(seconds % 60).toString().padStart(2, '0');
        return `${m}:${s}`;
    }

    function updateTimeDisplay(frameIndex, fps, totalFrames) {
        if (!fps || fps <= 0) fps = 30;
        const currentSec = frameIndex / fps;
        const totalSec = totalFrames / fps;
        timeDisplay.textContent = `${formatTime(currentSec)} / ${formatTime(totalSec)}`;
    }

    let timelineTimeout = null;
    timelineSlider.addEventListener('input', (e) => {
        const frameIndex = parseInt(e.target.value);
        updateTimeDisplay(frameIndex, videoFps, videoTotalFrames);
        
        if (timelineTimeout) clearTimeout(timelineTimeout);
        timelineTimeout = setTimeout(async () => {
            if (!currentVideoId) return;
            
            // 显示微型加载动画
            if (frameLoadingSpinner) frameLoadingSpinner.style.display = 'inline-block';
            
            try {
                const response = await fetch(`/api/frame/${currentVideoId}?frame_index=${frameIndex}`);
                const data = await response.json();
                if (data.success && data.frame) {
                    const tempImg = new Image();
                    tempImg.onload = () => {
                        previewImage = tempImg; // Update the global previewImage
                        ctx.clearRect(0, 0, canvasWidth, canvasHeight);
                        ctx.drawImage(previewImage, 0, 0, canvasWidth, canvasHeight);
                        if (frameLoadingSpinner) frameLoadingSpinner.style.display = 'none';
                    };
                    tempImg.src = 'data:image/jpeg;base64,' + data.frame;
                } else {
                    if (frameLoadingSpinner) frameLoadingSpinner.style.display = 'none';
                    showToast('获取视频帧失败: ' + (data.detail || '未知错误'), 'error');
                }
            } catch (err) {
                if (frameLoadingSpinner) frameLoadingSpinner.style.display = 'none';
                console.error("Failed to fetch frame:", err);
                showToast('网络请求异常，无法加载视频帧', 'error');
            }
        }, 150);
    });

    // --- 修复预览对比滑动条逻辑 ---
    const compSlider = document.getElementById('comp-slider');
    const compHandle = document.getElementById('comp-handle');

    function resetComparisonSlider() {
        if (!compSlider || !compHandle) return;
        
        // 设置默认位置 50%
        compSlider.style.setProperty('--clip-pos', '50%');
        compHandle.style.left = '50%';
        
        // 设置 aspect-ratio
        if (videoWidth && videoHeight) {
            compSlider.style.setProperty('--aspect-ratio', `${videoWidth}/${videoHeight}`);
        }
    }

    if (compSlider && compHandle) {
        let isSliding = false;

        const startSlide = (e) => {
            isSliding = true;
            e.preventDefault();
        };

        const stopSlide = () => {
            isSliding = false;
        };

        const moveSlide = (clientX) => {
            if (!isSliding) return;
            
            const rect = compSlider.getBoundingClientRect();
            const x = clientX - rect.left;
            let percentage = (x / rect.width) * 100;
            
            percentage = Math.max(0, Math.min(percentage, 100));
            
            compSlider.style.setProperty('--clip-pos', `${percentage}%`);
            compHandle.style.left = `${percentage}%`;
        };

        // 鼠标事件
        compHandle.addEventListener('mousedown', startSlide);
        window.addEventListener('mouseup', stopSlide);
        window.addEventListener('mousemove', (e) => moveSlide(e.clientX));

        // 触摸事件 (移动端支持)
        compHandle.addEventListener('touchstart', startSlide);
        window.addEventListener('touchend', stopSlide);
        window.addEventListener('touchmove', (e) => {
            if (e.touches.length > 0) {
                moveSlide(e.touches[0].clientX);
            }
        });

        // 点击 slider 快速定位
        compSlider.addEventListener('click', (e) => {
            if (e.target.closest('#comp-handle')) return;
            isSliding = true;
            moveSlide(e.clientX);
            isSliding = false;
        });
    }

    // 极速单帧预览接口
    btnPreviewFrame.addEventListener('click', async () => {
        if (!currentVideoId || selectionBoxes.length === 0) {
            showToast('请先上传视频并在预览画面上画出至少一个需要去水印的红框区域！', 'warning');
            return;
        }

        const scaleX = videoWidth / canvasWidth;
        const scaleY = videoHeight / canvasHeight;

        const regions = selectionBoxes.map(box => {
            const left = parseFloat(box.style.left) || 0;
            const top = parseFloat(box.style.top) || 0;
            const width = parseFloat(box.style.width) || 100;
            const height = parseFloat(box.style.height) || 100;
            return {
                x: Math.round(left * scaleX),
                y: Math.round(top * scaleY),
                w: Math.round(width * scaleX),
                h: Math.round(height * scaleY)
            };
        });

        const originalText = btnPreviewFrame.innerHTML;
        btnPreviewFrame.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> AI 极速修复中...';
        btnPreviewFrame.disabled = true;

        if (canvasLoader) {
            if (canvasLoaderText) canvasLoaderText.textContent = 'AI 正在分析并重构当前帧...';
            canvasLoader.classList.add('active');
        }

        try {
            const response = await fetch('/api/preview-frame', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    video_id: currentVideoId,
                    regions: regions,
                    method: selectMethod.value,
                    feather: parseInt(inputFeather.value),
                    frame_index: parseInt(timelineSlider.value)
                })
            });

            const data = await response.json();
            if (data.success && data.preview_frame) {
                // 设置对比滑块的数据源
                if (beforeImage) beforeImage.src = previewImage.src;
                afterImage.src = 'data:image/jpeg;base64,' + data.preview_frame;
                
                comparisonView.style.display = 'block';
                
                // 重置并初始化滑块位置
                resetComparisonSlider();
                
                // 平滑滚动到对比视图
                comparisonView.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                showToast('当前帧 AI 预览生成成功！', 'success');
            } else {
                showToast('预览失败: ' + (data.detail || '未知错误'), 'error');
            }
        } catch (error) {
            console.error('Error generating preview:', error);
            showToast('请求预览出现网络异常', 'error');
        } finally {
            btnPreviewFrame.innerHTML = originalText;
            btnPreviewFrame.disabled = false;
            if (canvasLoader) canvasLoader.classList.remove('active');
        }
    });

    // --- 重新上传与重置 ---
    btnResetUpload.addEventListener('click', () => {
        currentVideoId = null;
        comparisonView.style.display = 'none';
        showStep('upload');
        resetUploadZone();
    });

    // --- 启动去水印任务 ---
    btnStart.addEventListener('click', () => {
        if (!currentVideoId) return;

        const scaleX = videoWidth / canvasWidth;
        const scaleY = videoHeight / canvasHeight;

        const regions = selectionBoxes.map(box => {
            const left = parseFloat(box.style.left) || 0;
            const top = parseFloat(box.style.top) || 0;
            const width = parseFloat(box.style.width) || 100;
            const height = parseFloat(box.style.height) || 50;

            const x = Math.max(0, Math.round(left * scaleX));
            const y = Math.max(0, Math.round(top * scaleY));
            const w = Math.min(videoWidth - x, Math.round(width * scaleX));
            const h = Math.min(videoHeight - y, Math.round(height * scaleY));
            
            return { x, y, w, h };
        });

        const payload = {
            video_id: currentVideoId,
            regions: regions,
            method: selectMethod.value,
            feather: parseInt(inputFeather.value)
        };

        // 发送启动任务请求
        fetch('/api/remove-watermark', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(res => {
            if (!res.ok) {
                return res.json().then(err => { throw new Error(err.detail || '任务创建失败') });
            }
            return res.json();
        })
        .then(data => {
            currentJobId = data.job_id;
            showToast('去水印任务创建成功，开始处理视频...', 'success');
            showStep('processing');
            startPollingStatus();
        })
        .catch(err => {
            showToast('去水印任务启动失败: ' + err.message, 'error');
        });
    });

    // --- 步骤 3：进度查询轮询 ---
    function startPollingStatus() {
        // 重置进度UI
        progressFill.style.width = '0%';
        progressPercent.textContent = '0%';
        progressEta.textContent = '剩余时间: 计算中...';
        realtimeImg.src = '';

        if (pollInterval) clearInterval(pollInterval);
        
        pollInterval = setInterval(() => {
            if (!currentJobId) return;
            
            fetch(`/api/status/${currentJobId}`)
            .then(res => res.json())
            .then(data => {
                if (data.status === 'processing') {
                    // 更新进度
                    const progress = data.progress || 0;
                    progressFill.style.width = `${progress}%`;
                    progressPercent.textContent = `${progress}%`;
                    progressEta.textContent = `剩余时间: ${data.eta} 秒`;
                    
                    // 实时绘制画面预览
                    if (data.preview_frame) {
                        realtimeImg.src = 'data:image/jpeg;base64,' + data.preview_frame;
                    }
                } else if (data.status === 'completed') {
                    clearInterval(pollInterval);
                    showToast('视频去水印任务处理完成！', 'success');
                    showSuccess(data.ffmpeg_used);
                } else if (data.status === 'failed') {
                    clearInterval(pollInterval);
                    showToast('处理视频失败: ' + (data.error_message || '未知错误'), 'error');
                    showStep('configure');
                }
            })
            .catch(err => {
                console.error('进度轮询错误: ', err);
                // 轮询中的单次网络波动不弹窗，仅记录控制台，避免影响用户体验
            });
        }, 800);
    }

    // --- 步骤 4：处理成功展示 ---
    function showSuccess(ffmpegUsed) {
        // 设置视频播放源和下载源
        const videoSrc = `/api/download/${currentJobId}`;
        
        resultVideoPlayer.src = videoSrc;
        btnDownload.href = videoSrc;

        // 根据 FFmpeg 状态显示或隐藏音频警告
        if (ffmpegUsed) {
            ffmpegWarning.classList.add('hidden');
        } else {
            ffmpegWarning.classList.remove('hidden');
        }

        showStep('result');
    }

    // 处理新视频重新开始
    btnRestart.addEventListener('click', () => {
        currentVideoId = null;
        currentJobId = null;
        if (pollInterval) clearInterval(pollInterval);
        resultVideoPlayer.pause();
        resultVideoPlayer.src = '';
        showStep('upload');
        resetUploadZone();
    });
});
