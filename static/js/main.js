// File: static/js/main.js
// Version 2.0.0 (No changes needed, should work with updated HTML)

document.addEventListener('DOMContentLoaded', () => {
    // --- Get Element References (Ensure these IDs exist in the updated index.html) ---
    // --- 获取元素引用（确保这些 ID 存在于更新后的 index.html 中）---
    const workflowSelect = document.getElementById('workflow-select');
    const workflowError = document.getElementById('workflow-error'); // Added to HTML / 已添加到 HTML
    const lineartUpload = document.getElementById('lineart-upload');
    const lineartPreview = document.getElementById('lineart-preview');
    const referenceUpload = document.getElementById('reference-upload');
    const referencePreview = document.getElementById('reference-preview');
    const textPrompt = document.getElementById('text-prompt');
    const controlStrengthSlider = document.getElementById('control-strength');
    const controlStrengthValue = document.getElementById('control-strength-value');
    const batchCountInput = document.getElementById('batch-count');
    const renderButton = document.getElementById('render-button');
    const outputArea = document.getElementById('output-area');
    const statusMessage = document.getElementById('status-message'); // Inside .status-feedback / 在 .status-feedback 内
    const renderError = document.getElementById('render-error');       // Inside .status-feedback / 在 .status-feedback 内
    const progressBarContainer = document.getElementById('progress-bar-container'); // Inside .status-feedback / 在 .status-feedback 内
    const progressBar = document.getElementById('progress-bar');       // Inside .status-feedback / 在 .status-feedback 内
    const progressText = document.getElementById('progress-text');     // Inside .status-feedback / 在 .status-feedback 内
    const progressNode = document.getElementById('progress-node');     // Inside .status-feedback / 在 .status-feedback 内

    let socket = null; // WebSocket connection / WebSocket 连接
    let clientId = null; // Unique ID for this client session / 此客户端会话的唯一 ID

    // --- WebSocket Setup ---
    function connectWebSocket() {
        // Disconnect previous socket if exists / 如果存在，则断开先前的套接字
        if (socket && socket.connected) {
            socket.disconnect();
        }

        // Connect to the Flask-SocketIO server / 连接到 Flask-SocketIO 服务器
        // The URL should match your Flask server address and port / URL 应与您的 Flask 服务器地址和端口匹配
        console.log("Attempting to connect WebSocket..."); // Log connection attempt / 记录连接尝试
        socket = io.connect(window.location.protocol + '//' + document.domain + ':' + location.port);

        socket.on('connect', () => {
            clientId = socket.id; // Store the unique session ID / 存储唯一的会话 ID
            console.log('WebSocket Connected with ID:', clientId); // Log connection / 记录连接
            statusMessage.textContent = '已连接 (Connected)';
            renderError.textContent = ''; // Clear previous errors / 清除以前的错误
            // Enable render button if a workflow is selected / 如果选择了工作流，则启用渲染按钮
            renderButton.disabled = !workflowSelect.value;
        });

        socket.on('disconnect', (reason) => {
            console.log('WebSocket Disconnected:', reason); // Log disconnection / 记录断开连接
            clientId = null;
            statusMessage.textContent = '已断开 (Disconnected)';
            renderError.textContent = '连接已断开，请刷新页面重试。(Connection lost, please refresh.)';
            renderButton.disabled = true; // Disable rendering when disconnected / 断开连接时禁用渲染
        });

        socket.on('connect_error', (error) => {
            console.error('WebSocket Connection Error:', error); // Log connection error / 记录连接错误
            statusMessage.textContent = '连接错误 (Connection Error)';
            renderError.textContent = `无法连接到服务器: ${error.message}. 请确保后端服务正在运行。`;
            renderButton.disabled = true;
        });

        // Listen for results from the backend / 监听来自后端的结果
        socket.on('render_result', (data) => {
            console.log('Render result received:', data); // Log result / 记录结果
            outputArea.innerHTML = ''; // Clear previous results or placeholder / 清除以前的结果或占位符
             if (data.images && data.images.length > 0) {
                 data.images.forEach(imageBase64 => {
                    const imgElement = document.createElement('img');
                    imgElement.src = imageBase64; // Already includes data URI scheme / 已包含数据 URI 方案
                    imgElement.alt = 'Rendered Output';
                    // Styles applied via CSS (.output-section img) / 通过 CSS 应用样式 (.output-section img)
                    outputArea.appendChild(imgElement);
                });
                statusMessage.textContent = '渲染完成 (Render Complete)';
            } else {
                 outputArea.innerHTML = '<p>收到结果但无图像。(Result received but no images)</p>'; // Show message if no images / 如果没有图像则显示消息
                statusMessage.textContent = '收到结果但无图像 (Result received but no images)';
            }
            renderButton.disabled = false; // Re-enable button / 重新启用按钮
            hideProgressBar(); // Hide progress bar on completion / 完成时隐藏进度条
        });

        // Listen for errors from the backend / 监听来自后端的错误
        socket.on('render_error', (data) => {
            console.error('Render error received:', data); // Log error / 记录错误
            renderError.textContent = `渲染错误: ${data.message}`;
            statusMessage.textContent = '错误 (Error)';
            renderButton.disabled = false; // Re-enable button / 重新启用按钮
            hideProgressBar(); // Hide progress bar on error / 出错时隐藏进度条
        });

        // Listen for status updates / 监听状态更新
        socket.on('status_update', (data) => {
            console.log('Status update:', data); // Log status update / 记录状态更新
            let message = '';
            switch(data.status) {
                case 'running':
                    message = '运行中 (Running)';
                    if (data.queue_remaining !== undefined) {
                        message += ` (队列 Queue: ${data.queue_remaining})`;
                    }
                    break;
                case 'executing':
                    message = '执行节点中 (Executing Node)';
                     if (data.node_title) {
                         message += `: ${data.node_title}`;
                    }
                    break;
                case 'finished':
                    message = '处理完成 (Processing Finished)';
                     // Keep waiting for 'render_result' before saying 'Render Complete' / 在说“渲染完成”之前继续等待 'render_result'
                    break;
                default:
                    message = data.status; // Use status directly / 直接使用状态
            }
            statusMessage.textContent = message;
        });

         // Listen for progress updates / 监听进度更新
         socket.on('progress_update', (data) => {
            // console.log('Progress update:', data); // Log progress / 记录进度
            if (data.total > 0) {
                const percent = Math.round((data.progress / data.total) * 100);
                showProgressBar();
                progressBar.value = data.progress;
                progressBar.max = data.total;
                progressText.textContent = `${percent}%`;
                // Ensure progressNode exists before setting textContent / 在设置 textContent 之前确保 progressNode 存在
                 if(progressNode) {
                    progressNode.textContent = data.node_title ? `节点 Node: ${data.node_title}` : 'Overall Progress';
                 }
            } else {
                // Handle indeterminate progress if needed / 如果需要，处理不确定进度
                showProgressBar();
                progressBar.removeAttribute('value');
                progressText.textContent = '';
                 if(progressNode) {
                     progressNode.textContent = data.node_title ? `节点 Node: ${data.node_title}` : 'Processing...';
                 }
            }
         });

    }

    // --- Helper Functions ---
    function readFileAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result); // Returns data URL (includes base64) / 返回数据 URL（包含 base64）
            reader.onerror = (error) => reject(error);
            reader.readAsDataURL(file); // Read as Data URL / 读取为数据 URL
        });
    }

     function previewImage(fileInput, previewElement) {
         // Ensure previewElement exists / 确保 previewElement 存在
         if (!previewElement) return;

        const file = fileInput.files[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = (e) => {
                previewElement.src = e.target.result;
                previewElement.style.display = 'block'; // Show preview / 显示预览
            }
            reader.readAsDataURL(file);
        } else {
            previewElement.src = '#';
            previewElement.style.display = 'none'; // Hide preview / 隐藏预览
        }
    }

    function showProgressBar() {
        // Ensure progressBarContainer exists / 确保 progressBarContainer 存在
        if (progressBarContainer) {
            progressBarContainer.style.display = 'block';
        }
    }
    function hideProgressBar() {
         // Ensure progressBarContainer exists / 确保 progressBarContainer 存在
        if (progressBarContainer) {
            progressBarContainer.style.display = 'none';
            progressBar.value = 0;
            progressText.textContent = '0%';
            if(progressNode) progressNode.textContent = ''; // Clear node name / 清除节点名称
        }
    }


    // --- Event Listeners ---

    // Fetch workflows on page load / 页面加载时获取工作流
    console.log("Fetching workflows from /api/workflows"); // Log fetch start / 记录获取开始
    fetch('/api/workflows')
        .then(response => {
            console.log("Workflow fetch response status:", response.status); // Log response status / 记录响应状态
            if (!response.ok) {
                 // Try to get error message from response body / 尝试从响应体获取错误消息
                 return response.json().then(errData => {
                     throw new Error(errData.error || `HTTP error! status: ${response.status}`);
                 }).catch(() => {
                     // Fallback if response body is not JSON or empty / 如果响应体不是 JSON 或为空，则回退
                     throw new Error(`HTTP error! status: ${response.status}`);
                 });
            }
            return response.json();
        })
        .then(data => {
             console.log("Workflow data received:", data); // Log received data / 记录接收到的数据
            // Ensure workflowError element exists / 确保 workflowError 元素存在
            if (!workflowError) {
                 console.error("workflowError element not found in HTML!"); // Log missing element / 记录缺失元素
                 return;
            }

            if (data.error) {
                 workflowError.textContent = `无法加载工作流: ${data.error}`;
                 console.error("Error fetching workflows:", data.error); // Log error / 记录错误
            } else if (data.workflows && Array.isArray(data.workflows)) {
                workflowError.textContent = ''; // Clear error / 清除错误
                // Clear existing options except the placeholder / 清除现有选项（占位符除外）
                workflowSelect.innerHTML = '<option value="">--请选择--</option>';
                data.workflows.forEach(wf => {
                    const option = document.createElement('option');
                    option.value = wf;
                    option.textContent = wf.replace('.json', ''); // Display cleaner name / 显示更清晰的名称
                    workflowSelect.appendChild(option);
                });
                console.log("Workflows loaded into select:", data.workflows); // Log loaded workflows / 记录已加载的工作流
                 // Initial state for render button / 渲染按钮的初始状态
                 renderButton.disabled = true;
            } else {
                workflowError.textContent = '收到的工作流数据格式无效。';
                 console.error("Invalid workflow data format received:", data); // Log invalid format / 记录无效格式
            }
        })
        .catch(error => {
            console.error('Error fetching workflows:', error); // Log fetch error / 记录获取错误
            // Ensure workflowError element exists / 确保 workflowError 元素存在
            if (workflowError) {
                workflowError.textContent = `加载工作流时出错: ${error.message}. 请检查后端服务和路径配置。`;
            } else {
                 console.error("Cannot display workflow fetch error because workflowError element is missing!"); // Log missing element / 记录缺失元素
            }
            renderButton.disabled = true; // Disable rendering if workflows fail to load / 如果工作流加载失败，禁用渲染
        });

    // Enable/disable render button based on workflow selection / 根据工作流选择启用/禁用渲染按钮
    workflowSelect.addEventListener('change', () => {
         renderButton.disabled = !workflowSelect.value || !socket || !socket.connected;
         // Clear previous output and errors when changing selection / 更改选择时清除以前的输出和错误
         if (outputArea) outputArea.innerHTML = '<p>等待渲染结果... (Waiting for render results...)</p>'; // Reset output area / 重置输出区域
         if (renderError) renderError.textContent = ''; // Clear errors / 清除错误
         if (statusMessage) statusMessage.textContent = (socket && socket.connected) ? '空闲 (Idle)' : '已断开 (Disconnected)';
         hideProgressBar();
    });

    // Image preview listeners / 图像预览监听器
    lineartUpload.addEventListener('change', () => previewImage(lineartUpload, lineartPreview));
    referenceUpload.addEventListener('change', () => previewImage(referenceUpload, referencePreview));

    // Slider value display listener / 滑块值显示监听器
    controlStrengthSlider.addEventListener('input', () => {
        // Ensure controlStrengthValue exists / 确保 controlStrengthValue 存在
        if (controlStrengthValue) {
            controlStrengthValue.textContent = controlStrengthSlider.value;
        }
    });

    // Render button click listener / 渲染按钮点击监听器
    renderButton.addEventListener('click', async () => {
        if (!workflowSelect.value) {
            if(renderError) renderError.textContent = '请先选择一个工作流 (Please select a workflow first).';
            return;
        }
         if (!socket || !socket.connected) {
             if(renderError) renderError.textContent = '未连接到服务器，请刷新页面 (Not connected to server, please refresh).';
             return;
         }
          // Ensure clientId is set / 确保 clientId 已设置
          if (!clientId) {
             if(renderError) renderError.textContent = '客户端 ID 无效，请刷新页面重试。(Invalid client ID, please refresh.)';
             return;
          }

        renderButton.disabled = true; // Disable button during processing / 处理期间禁用按钮
        if (renderError) renderError.textContent = ''; // Clear previous errors / 清除以前的错误
        if (outputArea) outputArea.innerHTML = '<p>准备请求... (Preparing request...)</p>'; // Clear previous results / 清除以前的结果
        if (statusMessage) statusMessage.textContent = '准备中 (Preparing)...';
        showProgressBar(); // Show indeterminate progress initially / 最初显示不确定进度
        progressBar.removeAttribute('value'); // Make it indeterminate / 使其不确定
        if(progressText) progressText.textContent = '';
        if(progressNode) progressNode.textContent = '';


        try {
            // 1. Get workflow and other inputs / 1. 获取工作流和其他输入
            const workflow = workflowSelect.value;
            const text = textPrompt.value;
            const strength = parseFloat(controlStrengthSlider.value);
            const count = parseInt(batchCountInput.value, 10);

            // 2. Read images as Base64 / 2. 将图像读取为 Base64
            let lineartBase64 = null;
            if (lineartUpload.files.length > 0) {
                statusMessage.textContent = '读取线稿图像... (Reading lineart image...)';
                lineartBase64 = await readFileAsBase64(lineartUpload.files[0]);
            }

            let referenceBase64 = null;
            if (referenceUpload.files.length > 0) {
                statusMessage.textContent = '读取参考图像... (Reading reference image...)';
                referenceBase64 = await readFileAsBase64(referenceUpload.files[0]);
            }

            // 3. Prepare data payload for the backend / 3. 准备发送到后端的数据负载
            const payload = {
                clientId: clientId, // Send our WebSocket client ID / 发送我们的 WebSocket 客户端 ID
                workflow: workflow,
                lineart: lineartBase64,
                reference: referenceBase64,
                textPrompt: text,
                controlStrength: strength,
                batchCount: count,
            };

            // 4. Send data to the backend API / 4. 将数据发送到后端 API
            statusMessage.textContent = '发送渲染请求 (Sending Render Request)...';
            console.log("Sending payload to /api/render:", payload); // Log payload before sending / 发送前记录有效负载
            const response = await fetch('/api/render', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });

            const result = await response.json();
            console.log("Response from /api/render:", response.status, result); // Log response / 记录响应

            if (!response.ok) {
                 // Throw error to be caught by the catch block / 抛出错误以被 catch 块捕获
                throw new Error(result.error || `HTTP error! status: ${response.status}`);
            }

            // 5. Backend acknowledged the request, now wait for WebSocket results / 5. 后端已确认请求，现在等待 WebSocket 结果
            console.log('Render request sent successfully:', result); // Log success / 记录成功
            statusMessage.textContent = `排队中 (Queued Prompt ID: ${result.prompt_id})... 等待 ComfyUI (Waiting for ComfyUI)`;
            if (outputArea) outputArea.innerHTML = '<p>正在渲染，请稍候... (Rendering, please wait...)</p>'; // Indicate processing / 指示正在处理

        } catch (error) {
            console.error('Error sending render request:', error); // Log error / 记录错误
            if(renderError) renderError.textContent = `发送请求失败: ${error.message}`;
            if(statusMessage) statusMessage.textContent = '错误 (Error)';
            renderButton.disabled = false; // Re-enable button on error / 出错时重新启用按钮
            hideProgressBar(); // Hide progress bar on error / 出错时隐藏进度条
        }
    });

    // --- Initial Setup ---
    // Ensure all necessary elements are present before connecting / 连接前确保所有必需的元素都存在
    if (workflowSelect && statusMessage && renderButton && outputArea && workflowError && renderError && progressBarContainer && progressBar && progressText && progressNode) {
        connectWebSocket(); // Connect WebSocket on load / 加载时连接 WebSocket
        statusMessage.textContent = '正在连接... (Connecting...)';
    } else {
        console.error("One or more essential HTML elements are missing. Cannot initialize JavaScript correctly."); // Log missing elements / 记录缺失元素
        if(document.body) { // Display error on page if possible / 如果可能，在页面上显示错误
             const errorDiv = document.createElement('div');
             errorDiv.textContent = "页面初始化错误：缺少必要的 HTML 元素。请检查模板文件。 (Page Initialization Error: Missing required HTML elements. Please check the template file.)";
             errorDiv.style.color = 'red';
             errorDiv.style.fontWeight = 'bold';
             errorDiv.style.padding = '20px';
             document.body.prepend(errorDiv); // Add error to the top / 将错误添加到顶部
        }
    }


});