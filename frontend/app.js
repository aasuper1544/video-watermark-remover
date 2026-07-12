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
        const steps = {
        upload: document.getElementById('step-upload'),
        configure: document.getElementById('step-configure'),
        processing: document.getElementById('step-processing'),
        batchQueue: document.getElementById('step-batch-queue'),
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

    // --- 步骤 1：批量文件上传逻辑 ---
    let uploadedFiles = []; // 保存当前所有已上传或解析就绪的视频对象

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
            handleBatchUpload(Array.from(e.dataTransfer.files));
        }
    });
    
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleBatchUpload(Array.from(e.target.files));
        }
    });

    // 统一处理批量上传
    async function handleBatchUpload(files) {
        const listContainer = document.getElementById('batch-upload-list-container');
        listContainer.classList.remove('hidden');
        
        for (let file of files) {
            // 避免重复添加同名素材
            if (uploadedFiles.some(f => f.name === file.name)) continue;
            
            const fileItem = {
                id: 'file-' + Math.random().toString(36).substr(2, 9),
                name: file.name,
                size: (file.size / (1024 * 1024)).toFixed(2) + ' MB',
                status: 'waiting', // waiting, uploading, ready, failed
                progress: 0,
                videoId: null,
                width: 0,
                height: 0,
                fps: 30,
                totalFrames: 0,
                previewFrame: null,
                selected: true,
                rawFile: file
            };
            uploadedFiles.push(fileItem);
        }
        
        renderBatchFilesTable();
        
        // 依次串行上传所有 waiting 的文件
        for (let fileItem of uploadedFiles) {
            if (fileItem.status === 'waiting') {
                await uploadSingleFileItem(fileItem);
            }
        }
    }

    function renderBatchFilesTable() {
        const tbody = document.getElementById('batch-files-body');
        const countSpan = document.getElementById('batch-upload-count');
        tbody.innerHTML = '';
        countSpan.textContent = uploadedFiles.length;
        
        uploadedFiles.forEach(file => {
            let statusText = '';
            if (file.status === 'waiting') {
                statusText = '<span style="color: var(--text-muted);"><i class="fa-solid fa-hourglass-start"></i> 排队上传...</span>';
            } else if (file.status === 'uploading') {
                statusText = `<span style="color: var(--primary-color);"><i class="fa-solid fa-spinner fa-spin"></i> 上传中 (${file.progress}%)</span>`;
            } else if (file.status === 'ready') {
                statusText = '<span style="color: var(--success-color); font-weight: 600;"><i class="fa-solid fa-circle-check"></i> 解析就绪</span>';
            } else if (file.status === 'failed') {
                statusText = '<span style="color: var(--danger-color);"><i class="fa-solid fa-circle-xmark"></i> 解析失败</span>';
            }
            
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><input type="checkbox" class="chk-file-select" data-id="${file.id}" ${file.selected ? 'checked' : ''} ${file.status === 'ready' ? '' : 'disabled'}></td>
                <td style="word-break: break-all; max-width: 300px; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${file.name}</td>
                <td>${file.size}</td>
                <td>${statusText}</td>
            `;
            tbody.appendChild(tr);
            
            // 绑定单个选择事件
            const chk = tr.querySelector('.chk-file-select');
            chk.addEventListener('change', (e) => {
                file.selected = e.target.checked;
                updateNextButtonVisibility();
            });
        });
        
        updateNextButtonVisibility();
    }

    // 全选按钮事件
    document.getElementById('chk-select-all').addEventListener('change', (e) => {
        const isChecked = e.target.checked;
        uploadedFiles.forEach(file => {
            if (file.status === 'ready') {
                file.selected = isChecked;
            }
        });
        renderBatchFilesTable();
    });

    function updateNextButtonVisibility() {
        const nextBtn = document.getElementById('btn-next-config');
        const hasReadyAndSelected = uploadedFiles.some(f => f.status === 'ready' && f.selected);
        if (hasReadyAndSelected) {
            nextBtn.style.display = 'block';
        } else {
            nextBtn.style.display = 'none';
        }
    }

    async function uploadSingleFileItem(fileItem) {
        fileItem.status = 'uploading';
        fileItem.progress = 0;
        renderBatchFilesTable();
        
        const formData = new FormData();
        formData.append('file', fileItem.rawFile);
        
        try {
            await new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                xhr.open('POST', '/api/upload');
                
                xhr.upload.onprogress = (e) => {
                    if (e.lengthComputable) {
                        fileItem.progress = Math.round((e.loaded / e.total) * 100);
                        renderBatchFilesTable();
                    }
                };
                
                xhr.onload = () => {
                    if (xhr.status === 200) {
                        try {
                            const data = JSON.parse(xhr.responseText);
                            fileItem.status = 'ready';
                            fileItem.videoId = data.video_id;
                            fileItem.width = data.width;
                            fileItem.height = data.height;
                            fileItem.fps = data.fps;
                            fileItem.totalFrames = data.total_frames;
                            fileItem.previewFrame = data.preview_frame;
                            resolve();
                        } catch (e) {
                            reject(new Error('解析返回值失败'));
                        }
                    } else {
                        try {
                            const err = JSON.parse(xhr.responseText);
                            reject(new Error(err.detail || '服务解析出错'));
                        } catch {
                            reject(new Error('HTTP 上传错误: ' + xhr.status));
                        }
                    }
                };
                
                xhr.onerror = () => reject(new Error('网络请求失败'));
                xhr.send(formData);
            });
        } catch (err) {
            fileItem.status = 'failed';
            showToast(`素材 ${fileItem.name} 上传解析失败: ` + err.message, 'error');
        }
        
        renderBatchFilesTable();
    }

    // 下一步配置页面转场事件
    document.getElementById('btn-next-config').addEventListener('click', () => {
        const selected = uploadedFiles.filter(f => f.status === 'ready' && f.selected);
        if (selected.length === 0) return;
        
        const first = selected[0];
        currentVideoId = first.videoId;
        videoWidth = first.width;
        videoHeight = first.height;
        videoFps = first.fps;
        videoTotalFrames = first.total_frames;
        videoDimsBadge.textContent = `${videoWidth} x ${videoHeight} (${videoFps.toFixed(1)} FPS) - [配置模板: ${first.name}]`;
        
        if (videoTotalFrames > 0) {
            timelineSlider.max = videoTotalFrames - 1;
            timelineSlider.value = 0;
            timelineContainer.style.display = 'block';
            updateTimeDisplay(0, videoFps, videoTotalFrames);
        }
        
        previewImage.onload = () => {
            initCanvas();
            showStep('configure');
        };
        previewImage.src = 'data:image/jpeg;base64,' + first.previewFrame;
    });

    function resetUploadZone() {
        uploadedFiles = [];
        const listContainer = document.getElementById('batch-upload-list-container');
        listContainer.classList.add('hidden');
        document.getElementById('batch-files-body').innerHTML = '';
        
        dropzone.innerHTML = `
            <input type="file" id="file-input" accept="video/*" style="display: none;" multiple>
            <div class="upload-icon">
                <i class="fa-solid fa-cloud-arrow-up"></i>
            </div>
            <h3>拖拽视频文件到此处 (支持批量拖入)</h3>
            <p>或者 <label for="file-input" class="browse-btn" style="cursor: pointer;">浏览本地文件</label></p>
            <div class="formats-info">支持 MP4, AVI, MOV, MKV 等常见视频格式</div>
        `;
        
        const newFileInput = document.getElementById('file-input');
        newFileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                handleBatchUpload(Array.from(e.target.files));
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
        if (btnStart) btnStart.disabled = true;

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
            if (btnStart) btnStart.disabled = false;
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
    let queueJobs = []; // 存储排队中的任务对象

    btnStart.addEventListener('click', async () => {
        const selectedFiles = uploadedFiles.filter(f => f.status === 'ready' && f.selected);
        if (selectedFiles.length === 0) {
            showToast('请先选择并上传至少一个解析就绪的视频！', 'warning');
            return;
        }

        const originalText = btnStart.innerHTML;
        btnStart.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 正在创建排队任务...';
        btnStart.disabled = true;
        if (btnPreviewFrame) btnPreviewFrame.disabled = true;

        queueJobs = [];

        // 遍历所有选中的视频，并按照各自的分辨率自适应换算水印位置坐标
        for (let file of selectedFiles) {
            const fileScaleX = file.width / canvasWidth;
            const fileScaleY = file.height / canvasHeight;
            const fileRegions = selectionBoxes.map(box => {
                const left = parseFloat(box.style.left) || 0;
                const top = parseFloat(box.style.top) || 0;
                const width = parseFloat(box.style.width) || 100;
                const height = parseFloat(box.style.height) || 50;

                const x = Math.max(0, Math.round(left * fileScaleX));
                const y = Math.max(0, Math.round(top * fileScaleY));
                const w = Math.min(file.width - x, Math.round(width * fileScaleX));
                const h = Math.min(file.height - y, Math.round(height * fileScaleY));
                
                return { x, y, w, h };
            });

            const payload = {
                video_id: file.videoId,
                regions: fileRegions,
                method: selectMethod.value,
                feather: parseInt(inputFeather.value)
            };

            try {
                const res = await fetch('/api/remove-watermark', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || '接口失败');
                }
                
                const data = await res.json();
                queueJobs.push({
                    jobId: data.job_id,
                    fileName: file.name,
                    progress: 0,
                    status: 'pending',
                    eta: 0
                });
            } catch (err) {
                showToast(`视频 ${file.name} 加入队列失败: ` + err.message, 'error');
            }
        }

        btnStart.innerHTML = originalText;
        btnStart.disabled = false;
        if (btnPreviewFrame) btnPreviewFrame.disabled = false;

        if (queueJobs.length > 0) {
            showToast(`已成功将 ${queueJobs.length} 个视频加入处理队列！`, 'success');
            showStep('batchQueue');
            startBatchQueuePolling();
        }
    });

    // --- 步骤 3.5：批量队列状态轮询与渲染 ---
    function startBatchQueuePolling() {
        if (pollInterval) clearInterval(pollInterval);
        
        renderQueueMonitorTable();

        pollInterval = setInterval(async () => {
            const activeJobs = queueJobs.filter(j => !['completed', 'failed', 'canceled'].includes(j.status));
            if (activeJobs.length === 0) {
                clearInterval(pollInterval);
                showToast('队列中所有任务处理完毕！', 'success');
                return;
            }

            // 并发获取所有当前活动任务的最新状态
            await Promise.all(activeJobs.map(async (job) => {
                try {
                    const res = await fetch(`/api/status/${job.jobId}`);
                    if (res.ok) {
                        const data = await res.json();
                        job.status = data.status;
                        job.progress = data.progress || 0;
                        job.eta = data.eta || 0;
                    }
                } catch (e) {
                    console.error('轮询状态出错:', job.fileName, e);
                }
            }));

            renderQueueMonitorTable();
        }, 1000);
    }

    function renderQueueMonitorTable() {
        const tbody = document.getElementById('queue-monitor-body');
        if (!tbody) return;
        tbody.innerHTML = '';

        queueJobs.forEach(job => {
            const tr = document.createElement('tr');
            
            // 状态 Badge
            let statusBadge = '';
            if (job.status === 'pending') {
                statusBadge = '<span class="badge-status pending"><i class="fa-solid fa-hourglass-half"></i> 排队中</span>';
            } else if (job.status === 'processing') {
                statusBadge = '<span class="badge-status processing"><i class="fa-solid fa-spinner fa-spin"></i> 处理中</span>';
            } else if (job.status === 'completed') {
                statusBadge = '<span class="badge-status completed"><i class="fa-solid fa-check-circle"></i> 已完成</span>';
            } else if (job.status === 'failed') {
                statusBadge = '<span class="badge-status failed"><i class="fa-solid fa-times-circle"></i> 失败</span>';
            } else if (job.status === 'canceled') {
                statusBadge = '<span class="badge-status canceled"><i class="fa-solid fa-ban"></i> 已取消</span>';
            }

            // 进度条渲染
            let progressHtml = '';
            if (job.status === 'pending') {
                progressHtml = '<span style="color: var(--text-muted); font-size: 0.85rem;">等待轮到该任务...</span>';
            } else {
                progressHtml = `
                    <div class="mini-progress-container">
                        <div class="mini-progress-bg">
                            <div class="mini-progress-fill" style="width: ${job.progress}%"></div>
                        </div>
                        <span class="mini-progress-text">${job.progress}%</span>
                    </div>
                `;
            }

            // 操作按钮
            let actionHtml = '';
            if (job.status === 'completed') {
                actionHtml = `
                    <a href="/api/download/${job.jobId}" class="btn btn-success" style="padding: 5px 12px; font-size: 0.8rem;" download>
                        <i class="fa-solid fa-download"></i> 下载
                    </a>
                `;
            } else if (['pending', 'processing'].includes(job.status)) {
                actionHtml = `
                    <button class="btn btn-danger btn-cancel-job" data-id="${job.jobId}" style="padding: 5px 12px; font-size: 0.8rem;">
                        <i class="fa-solid fa-xmark"></i> 取消
                    </button>
                `;
            } else {
                actionHtml = '<span style="color: var(--text-muted); font-size: 0.85rem;">-</span>';
            }

            tr.innerHTML = `
                <td style="word-break: break-all; max-width: 250px; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">${job.fileName}</td>
                <td>${progressHtml}</td>
                <td style="text-align: center;">${statusBadge}</td>
                <td style="text-align: center;">${actionHtml}</td>
            `;

            tbody.appendChild(tr);
        });

        // 绑定取消按钮事件
        tbody.querySelectorAll('.btn-cancel-job').forEach(btn => {
            btn.addEventListener('click', async () => {
                const jid = btn.getAttribute('data-id');
                const res = await fetch(`/api/cancel/${jid}`, { method: 'POST' });
                if (res.ok) {
                    showToast('任务已取消', 'info');
                    const job = queueJobs.find(j => j.jobId === jid);
                    if (job) job.status = 'canceled';
                    renderQueueMonitorTable();
                } else {
                    showToast('取消任务失败', 'error');
                }
            });
        });
    }

    // 全部取消按钮事件
    document.getElementById('btn-cancel-all').addEventListener('click', async () => {
        const active = queueJobs.filter(j => ['pending', 'processing'].includes(j.status));
        if (active.length === 0) return;
        
        for (let job of active) {
            try {
                const res = await fetch(`/api/cancel/${job.jobId}`, { method: 'POST' });
                if (res.ok) {
                    job.status = 'canceled';
                }
            } catch (e) {
                console.error('取消任务异常:', job.fileName, e);
            }
        }
        showToast('所有排队及进行中的任务已成功取消', 'info');
        renderQueueMonitorTable();
    });

    // 从队列页重新开始上传
    document.getElementById('btn-queue-restart').addEventListener('click', () => {
        if (pollInterval) clearInterval(pollInterval);
        showStep('upload');
        resetUploadZone();
    });

    // 窗口尺寸改变自适应处理
    function handleResize() {
        const container = document.getElementById('canvas-container');
        if (!container || !currentVideoId || !videoWidth || !videoHeight) return;
        
        const parentWidth = container.parentElement.clientWidth;
        if (!parentWidth) return;
        
        const maxDisplayWidth = Math.min(parentWidth, 680);
        const aspect = videoWidth / videoHeight;
        
        const newCanvasWidth = maxDisplayWidth;
        const newCanvasHeight = maxDisplayWidth / aspect;
        
        // 尺寸无实质变化则不处理
        if (Math.abs(newCanvasWidth - canvasWidth) < 1 && Math.abs(newCanvasHeight - canvasHeight) < 1) {
            return;
        }
        
        if (canvasWidth === 0 || canvasHeight === 0) return;
        
        const scaleX = newCanvasWidth / canvasWidth;
        const scaleY = newCanvasHeight / canvasHeight;
        
        // 按比例缩放所有选择框
        selectionBoxes.forEach(box => {
            const left = parseFloat(box.style.left) || 0;
            const top = parseFloat(box.style.top) || 0;
            const width = parseFloat(box.style.width) || 0;
            const height = parseFloat(box.style.height) || 0;
            
            box.style.left = `${left * scaleX}px`;
            box.style.top = `${top * scaleY}px`;
            box.style.width = `${width * scaleX}px`;
            box.style.height = `${height * scaleY}px`;
        });
        
        // 更新全局画布尺寸
        canvasWidth = newCanvasWidth;
        canvasHeight = newCanvasHeight;
        
        previewCanvas.width = canvasWidth;
        previewCanvas.height = canvasHeight;
        
        container.style.width = `${canvasWidth}px`;
        container.style.height = `${canvasHeight}px`;
        
        // 重绘图像
        ctx.drawImage(previewImage, 0, 0, canvasWidth, canvasHeight);
    }

    let resizeTimeout = null;
    window.addEventListener('resize', () => {
        if (!currentVideoId) return;
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            handleResize();
        }, 150);
    });
});
