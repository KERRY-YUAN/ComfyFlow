// --- Debounce Function ---
// --- 防抖函数 ---
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// --- Global variables ---
// --- 全局变量 ---
let statusIndicatorTimeout = null; // Timeout for the top-right indicator / 右上角指示器的超时
let comfyUISocket = null; // WebSocket object for ComfyUI connection / 用于 ComfyUI 连接的 WebSocket 对象
let reconnectTimeout = null; // Timeout for WS reconnection attempts / WS 重连尝试的超时
let currentPromptId = null; // ID of the currently running prompt / 当前运行提示的 ID
let currentOutputNodeId = null; // Expected output node ID from the backend / 后端返回的预期输出节点 ID

// --- Configuration ---
// --- 配置 ---
// COMFYUI_API_PORT is injected from Flask template / COMFYUI_API_PORT 由 Flask 模板注入
const COMFYUI_WS_URL = `ws://${window.location.hostname}:${COMFYUI_API_PORT}/ws`;
const COMFYUI_VIEW_URL_BASE = `http://${window.location.hostname}:${COMFYUI_API_PORT}/view`;
const APP_API_BASE = window.location.origin; // Flask app URL / Flask 应用 URL

// --- DOM Element References (declared early for polling functions) ---
// --- DOM 元素引用 (为轮询函数提前声明) ---
const comfyStatusElement = document.getElementById('comfy-connection-status'); // For API connection status / 用于 API 连接状态
const backendLogDisplay = document.getElementById('backend-log-display'); // For WS status / 用于 WS 状态
const renderBtn = document.getElementById('render-btn'); // Render button / 渲染按钮

// --- Function Definitions ---
// --- 函数定义 ---

/** Reads file as Data URL / 将文件读取为 Data URL */
function readFileAsDataURL(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = (error) => reject(error);
        reader.readAsDataURL(file);
    });
}

/** Checks if image element has valid src / 检查图像元素是否具有有效的 src */
function hasValidSrc(imgElement) {
    return imgElement && imgElement.src && !imgElement.src.endsWith('#') && imgElement.src.length > 10;
}

/** Updates top-right status indicator / 更新右上角状态指示器 */
function updateStatusIndicator(message, type = 'busy') {
    const indicator = document.getElementById('comfyui-status-indicator');
    if (!indicator) return;
    indicator.textContent = message;
    indicator.className = 'visible ' + type;
    if (statusIndicatorTimeout) clearTimeout(statusIndicatorTimeout);
    // Hide delay depends on type / 隐藏延迟取决于类型
    const hideDelay = (type === 'ready') ? 5000 : (type === 'error' ? 6000 : 4000);
    statusIndicatorTimeout = setTimeout(() => indicator.classList.remove('visible'), hideDelay);
}

/** Hides top-right status indicator / 隐藏右上角状态指示器 */
function hideStatusIndicator() {
    const indicator = document.getElementById('comfyui-status-indicator');
    if (indicator) {
        if (statusIndicatorTimeout) clearTimeout(statusIndicatorTimeout);
        indicator.className = ''; // Remove all classes to hide / 移除所有类以隐藏
    }
}

/** Updates the log footer WebSocket status text and style / 更新日志页脚 WebSocket 状态文本和样式 */
function updateFooter(text, statusClass = 'idle') {
    if (backendLogDisplay) {
        backendLogDisplay.textContent = text;
        const classes = ['idle', 'connecting', 'connected', 'progress', 'disconnected'];
        backendLogDisplay.classList.remove(...classes);
        if (statusClass) backendLogDisplay.classList.add(statusClass);
    }
}

/**
 * Sends data to the Flask backend to be staged for a specific key.
 * 将数据发送到 Flask 后端以暂存特定键。
 * @param {string} key - The identifier for this data (e.g., 'current_line_draft'). / 此数据的标识符（例如，'current_line_draft'）。
 * @param {'Image'|'Text'|'Float'|'Int'} type - The type of data being sent. / 发送的数据类型。
 * @param {File|string|number} value - The data value (File object for Image, string/number otherwise). / 数据值（图像为 File 对象，否则为字符串/数字）。
 * @param {HTMLElement} [feedbackElement] - Optional element (like upload-box) to apply status classes. / 可选元素（如 upload-box）以应用状态类。
 * @returns {Promise<boolean>} - Promise resolving to true on success, false on failure. / Promise，成功时解析为 true，失败时解析为 false。
 */
async function stageData(key, type, value, feedbackElement = null) {
    const formData = new FormData();
    formData.append('key', key);
    formData.append('type', type);

    if (type === 'Image' && value instanceof File) {
        formData.append('image_file', value, value.name);
    } else if (type === 'Image' && value === null) {
         // Explicitly handle clearing the image
         // 显式处理清除图像
         formData.append('image_file', ''); // Send empty file field
    }
     else {
        formData.append('value', String(value)); // Send other types as string value / 其他类型作为字符串值发送
    }

    console.log(`Staging data for key: ${key}, type: ${type}`);
    if (feedbackElement) feedbackElement.classList.add('uploading');
    if (feedbackElement) feedbackElement.classList.remove('success', 'error');

    try {
        const response = await fetch(`${APP_API_BASE}/api/stage_data`, { method: 'POST', body: formData });
        const result = await response.json();
        if (feedbackElement) feedbackElement.classList.remove('uploading');

        if (!response.ok || !result.success) {
            throw new Error(result.message || `HTTP error ${response.status}`);
        }
        console.log(`Data staged successfully for key: ${key}. Response:`, result);
        if (feedbackElement && value !== null) feedbackElement.classList.add('success'); // Only show success if value exists / 仅当值存在时显示成功
        return true; // Indicate success / 表示成功
    } catch (error) {
        console.error(`Error staging data for key ${key}:`, error);
        if (feedbackElement) feedbackElement.classList.add('error');
        // Show error to user (maybe only for images?) / 向用户显示错误（可能仅适用于图像？）
        if (type === 'Image') updateStatusIndicator(`暂存图像错误 (${key}) / Staging Image Error (${key}): ${error.message}`, 'error');
        return false; // Indicate failure / 表示失败
    }
}


/** Sets up preview and triggers staging on change / 设置预览并在更改时触发暂存 */
function setupInputStaging(inputId, previewId, dataKey, dataType = 'Image') {
    const inputElement = document.getElementById(inputId);
    const imagePreview = previewId ? document.getElementById(previewId) : null;
    const uploadBox = inputElement ? inputElement.closest('.upload-box') : null; // Needed for visual feedback / 需要用于视觉反馈

    if (!inputElement) { console.error(`Init Error: Missing input element: ${inputId}`); return; }
    if (dataType === 'Image' && !imagePreview) { console.error(`Init Error: Missing preview element for image input: ${previewId}`); return; }

    // Use debounce for non-image inputs to avoid spamming the stage API / 对非图像输入使用 debounce 以避免频繁调用暂存 API
    const debounceWait = 300; // ms delay for staging text/numbers / 暂存文本/数字的毫秒延迟
    const debouncedStageData = debounce(stageData, debounceWait);

    inputElement.addEventListener('change', async function(event) {
        let feedbackTarget = uploadBox; // Default feedback element / 默认反馈元素

        if (dataType === 'Image') {
            const file = event.target.files[0];
            // Reset UI first / 首先重置 UI
            if (imagePreview) { imagePreview.src = ''; imagePreview.style.display = 'none'; }
            if (uploadBox) uploadBox.classList.remove('uploading', 'success', 'error');

            if (file && file.type.startsWith('image/')) {
                // Show preview immediately / 立即显示预览
                try {
                    const imageUrl = await readFileAsDataURL(file);
                    if (imagePreview) { imagePreview.src = imageUrl; imagePreview.style.display = 'block'; }
                } catch (readError) { console.error("Preview Error:", readError); return; }
                // Stage the file directly / 直接暂存文件
                stageData(dataKey, 'Image', file, uploadBox); // No debounce for file uploads / 文件上传不使用 debounce
            } else {
                 // Handle file input being cleared or non-image selected
                 // 处理文件输入被清除或选择了非图像文件
                 console.log(`Image input ${inputId} cleared or invalid file.`);
                 stageData(dataKey, 'Image', null, uploadBox); // Send null to signal clearing / 发送 null 以表示清除
            }
        } else {
            // For Text, Float, Int - stage the current value / 对于 Text, Float, Int - 暂存当前值
            const valueToStage = inputElement.value;
            feedbackTarget = null; // No specific visual feedback for these usually / 这些通常没有特定的视觉反馈
            // Use debounced staging for non-image types / 对非图像类型使用 debounced 暂存
            debouncedStageData(dataKey, dataType, valueToStage, feedbackTarget);
        }
    });
}


/** Establishes and manages the WebSocket connection directly to ComfyUI. / 建立并管理直接到 ComfyUI 的 WebSocket 连接。*/
function connectComfyUIWebSocket() {
    // Prevent multiple connections / 防止多个连接
    if (comfyUISocket && (comfyUISocket.readyState === WebSocket.OPEN || comfyUISocket.readyState === WebSocket.CONNECTING)) {
        console.log("WebSocket already open or connecting.");
        return;
    }
    clearTimeout(reconnectTimeout); // Clear any pending reconnection attempt / 清除任何待处理的重连尝试
    console.log(`Attempting to connect to ComfyUI WS: ${COMFYUI_WS_URL}`);
    updateFooter('正在连接 WebSocket...', 'connecting');

    try {
        comfyUISocket = new WebSocket(COMFYUI_WS_URL);
    } catch (error) {
        console.error("Failed to create ComfyUI WS:", error);
        updateFooter('创建 WebSocket 连接失败', 'disconnected');
        reconnectTimeout = setTimeout(connectComfyUIWebSocket, 5000); // Retry after 5s / 5 秒后重试
        return;
    }

    comfyUISocket.onopen = () => {
        console.log("ComfyUI WS connected.");
        updateFooter('WebSocket 连接成功', 'connected');
        // Maybe trigger an immediate API status check upon successful WS connection
        // 也许在 WS 连接成功后立即触发一次 API 状态检查
        checkComfyUIConnection();
    };

    comfyUISocket.onclose = (event) => {
        console.warn(`ComfyUI WS closed. Code: ${event.code}, Reason: ${event.reason}, Clean: ${event.wasClean}`);
        comfyUISocket = null;
        const message = event.wasClean ? 'WebSocket 连接已关闭' : 'WebSocket 连接断开';
        updateFooter(message, 'disconnected');
        // Schedule reconnection attempt only if not closed cleanly or if desired
        // 仅当未干净关闭或需要时才安排重连尝试
        if (!event.wasClean) { // Could add more specific error codes to check here / 可在此处添加更具体的错误代码进行检查
             reconnectTimeout = setTimeout(connectComfyUIWebSocket, 5000); // Retry after 5s / 5 秒后重试
             updateFooter(message + '，5秒后重连...', 'disconnected');
        }
        // Ensure API status reflects disconnection too
        // 确保 API 状态也反映断开连接
        checkComfyUIConnection();
    };

    comfyUISocket.onerror = (error) => {
        console.error("ComfyUI WS Error:", error);
        updateFooter('WebSocket 连接错误', 'disconnected');
        // The onclose event will likely fire after onerror, handling reconnection
        // onclose 事件很可能会在 onerror 之后触发，处理重连
    };

    comfyUISocket.onmessage = (event) => { // Message Handling Logic / 消息处理逻辑
        if (event.data instanceof Blob) return; // Ignore binary previews / 忽略二进制预览
        try {
            const msg = JSON.parse(event.data);
            // console.log("WS MSG:", msg); // Debugging / 调试

            if (msg.type === 'status') {
                const queue = msg.data.status.exec_info.queue_remaining;
                // Update footer based on queue status only if not actively processing our prompt
                // 仅当未主动处理我们的提示时，才根据队列状态更新页脚
                if (!currentPromptId) {
                     if (queue === 0) updateFooter(`WebSocket 空闲 (队列: ${queue})`, 'idle');
                     else updateFooter(`WebSocket 繁忙 (队列: ${queue})`, 'progress');
                }
            } else if (msg.type === 'execution_start') {
                // Only track if it's potentially our prompt (or if we aren't tracking one)
                // 仅当它可能是我们的提示时（或者如果我们没有跟踪提示时）才跟踪
                // We rely on the /api/trigger_prompt response for the *definitive* prompt ID
                // 我们依赖 /api/trigger_prompt 响应来获取 *明确的* 提示 ID
                console.log(`WS Execution started: ${msg.data.prompt_id}. Current tracked: ${currentPromptId}`);
                if (!currentPromptId) currentPromptId = msg.data.prompt_id; // Tentatively track if we don't have one
                updateFooter(`开始执行 (队列: ${msg.data.queue_remaining || 'N/A'})`, 'progress');

            } else if (msg.type === 'executing') {
                 const executingPromptId = msg.data.prompt_id;
                 const nodeId = msg.data.node; // Node currently executing / 当前执行的节点
                 // If this is the prompt we triggered, update status
                 // 如果这是我们触发的提示，则更新状态
                 if (executingPromptId && executingPromptId === currentPromptId) {
                     if (nodeId === null) {
                         // null node usually means the execution flow finished, waiting for final 'executed'
                         // null 节点通常意味着执行流程已完成，等待最终的 'executed'
                         updateFooter(`完成执行中...`, 'progress');
                     } else {
                          // Optionally show which node is running
                          // 可选择显示哪个节点正在运行
                          // updateFooter(`执行中: 节点 ${nodeId}`, 'progress');
                     }
                 }
                 // If execution starts for a prompt ID different from the one we triggered, update our tracked ID
                 // 如果执行开始的提示 ID 与我们触发的不同，则更新我们跟踪的 ID
                 // else if (executingPromptId && !currentPromptId) {
                 //     currentPromptId = executingPromptId;
                 // }

            } else if (msg.type === 'progress') {
                const p = msg.data;
                const pct = p.max ? ((p.value / p.max) * 100).toFixed(0) : 0;
                updateFooter(`进度: ${p.value}/${p.max} (${pct}%)`, 'progress');

            } else if (msg.type === 'executed') {
                 const promptId = msg.data.prompt_id;
                 const executedNodeId = msg.data.node; // The ID of the node that just finished executing / 刚刚执行完毕的节点的 ID
                 console.log(`WS Node ${executedNodeId} executed for prompt ${promptId}. Target Output Node: ${currentOutputNodeId}`);

                 // Check if the executed node is the specific output node we are waiting for
                 // 检查执行的节点是否是我们等待的特定输出节点
                 if (promptId === currentPromptId && executedNodeId && String(executedNodeId) === String(currentOutputNodeId)) {
                     console.log(`Target output node (${currentOutputNodeId}) finished execution for prompt ${promptId}. Fetching results.`);
                     updateFooter(`执行完毕，获取结果...`, 'progress');
                     fetchAndDisplayResults(promptId, currentOutputNodeId); // Pass output node ID / 传递输出节点 ID
                     currentPromptId = null; // Clear tracked prompt ID / 清除跟踪的提示 ID
                     currentOutputNodeId = null; // Clear tracked output node ID / 清除跟踪的输出节点 ID
                 }
                 // Fallback: If output node ID wasn't found/tracked, maybe the *last* executed node is the output?
                 // 回退：如果未找到/跟踪输出节点 ID，也许 *最后* 执行的节点是输出？
                 // This requires checking if the prompt execution is fully complete (e.g., node is null in 'executing' msg earlier)
                 // 这需要检查提示执行是否完全完成（例如，之前 'executing' 消息中的节点为 null）
                 // Or check history when node is null? This part needs careful design based on workflow guarantees.
                 // 或者在节点为 null 时检查历史记录？这部分需要根据工作流保证进行仔细设计。
                 // For now, we strictly rely on matching `currentOutputNodeId`.
                 // 现在，我们严格依赖匹配 `currentOutputNodeId`。

                 // If execution finishes for the prompt we triggered, but it wasn't the target output node
                 // 如果我们触发的提示执行完成，但不是目标输出节点
                 else if (promptId === currentPromptId) {
                     // Check if the whole prompt flow might be done (indicated by previous 'executing' with node=null)
                     // 检查整个提示流程是否可能已完成（由先前节点=null的 'executing' 指示）
                     // Or maybe the backend didn't find the output node ID correctly.
                     // 或者也许后端没有正确找到输出节点 ID。
                     console.log(`Node ${executedNodeId} finished for our prompt ${promptId}, but not the target output node ${currentOutputNodeId}.`);
                     // We could potentially fetch results here if we *know* this is the last node,
                     // but it's safer to rely on the specific output node ID if possible.
                     // 如果我们 *知道* 这是最后一个节点，我们可以在这里获取结果，
                     // 但如果可能，依赖特定的输出节点 ID 更安全。
                 }
                 // If a prompt finishes that we weren't tracking, reset footer if needed
                 // 如果完成了一个我们没有跟踪的提示，则根据需要重置页脚
                 else if (!currentPromptId) {
                      const queue = msg.data?.status?.exec_info?.queue_remaining ?? 0; // Check queue again / 再次检查队列
                      if (queue === 0) updateFooter(`WebSocket 空闲 (队列: 0)`, 'idle');
                 }

            } else if (msg.type === 'execution_interrupted') {
                 const promptId = msg.data.prompt_id;
                 if (promptId === currentPromptId) {
                     console.warn(`Execution interrupted for prompt ${currentPromptId}`);
                     updateFooter('执行已中断', 'idle');
                     updateStatusIndicator('执行已中断', 'error');
                     currentPromptId = null; currentOutputNodeId = null;
                     if (renderBtn) renderBtn.disabled = false; // Re-enable button / 重新启用按钮
                 }
            } else if (msg.type === 'execution_error') {
                 const promptId = msg.data.prompt_id;
                 const node_id = msg.data.node_id;
                 const node_type = msg.data.node_type;
                 const error_message = msg.data.exception_message;
                 console.error(`Execution error in node ${node_id} (${node_type}) for prompt ${promptId}: ${error_message}`);
                 if (promptId === currentPromptId) {
                      updateFooter(`节点错误: ${node_type}`, 'disconnected');
                      updateStatusIndicator(`节点 ${node_type} 错误`, 'error');
                      currentPromptId = null; currentOutputNodeId = null;
                      if (renderBtn) renderBtn.disabled = false; // Re-enable button / 重新启用按钮
                 }
            }
        } catch (e) {
            console.error("Error parsing ComfyUI WS message:", e, "\nData:", event.data);
        }
    };
}

/** Fetches history and finds output for specific node ID / 获取历史记录并查找特定节点 ID 的输出 */
async function fetchAndDisplayResults(promptId, targetOutputNodeId) {
    console.log(`Fetching results for prompt ID: ${promptId}, targeting node: ${targetOutputNodeId}`);
    updateStatusIndicator('正在获取结果...', 'busy');
    const outputPlaceholder = document.getElementById('output-display')?.querySelector('.output-placeholder');
    const resultWrapper = document.querySelector('.output-result-wrapper');
    const resultLayerImg = resultWrapper?.querySelector('#output-result-layer img');

    try {
        // Slight delay might help ensure history is fully written
        // 稍作延迟可能有助于确保历史记录完全写入
        await new Promise(resolve => setTimeout(resolve, 500));
        const response = await fetch(`http://${window.location.hostname}:${COMFYUI_API_PORT}/history/${promptId}`);
        if (!response.ok) throw new Error(`获取历史记录失败 / Failed history fetch: ${response.status}`);
        const historyData = await response.json();
        console.log("History Data:", historyData);

        const promptHistory = historyData[promptId];
        if (!promptHistory || !promptHistory.outputs) throw new Error("历史记录中没有输出 / No outputs in history.");

        let targetOutput = null;
        if (targetOutputNodeId) {
             targetOutput = promptHistory.outputs[targetOutputNodeId];
             console.log(`Found output for target node ${targetOutputNodeId}:`, targetOutput);
        } else {
             // Fallback: If no targetOutputNodeId was provided (e.g., NodeBridge_Output not found)
             // Try to get the output of the *last* node in the history outputs
             // 回退：如果未提供 targetOutputNodeId（例如，未找到 NodeBridge_Output）
             // 尝试获取历史输出中 *最后* 一个节点的输出
             const outputKeys = Object.keys(promptHistory.outputs);
             if (outputKeys.length > 0) {
                 const lastNodeId = outputKeys[outputKeys.length - 1]; // Get the last key/ID / 获取最后一个键/ID
                 targetOutput = promptHistory.outputs[lastNodeId];
                 console.warn(`Output Node ID was missing, using output from last node (${lastNodeId}):`, targetOutput);
             }
        }


        if (!targetOutput || !targetOutput.images || targetOutput.images.length === 0) {
             console.warn(`在目标输出节点中未找到图像 (Node: ${targetOutputNodeId || 'Last Node'}). History:`, promptHistory.outputs);
             updateStatusIndicator('完成但未找到输出图像', 'ready');
             if (outputPlaceholder) outputPlaceholder.style.display = 'flex'; // Show placeholder again / 再次显示占位符
             if(resultWrapper) resultWrapper.style.display = 'none';
             if(resultLayerImg) resultLayerImg.src = '';
             return; // Exit if no images found / 如果未找到图像则退出
        }

        // Use the first image found in the target node's output / 使用在目标节点输出中找到的第一个图像
        const imgInfo = targetOutput.images[0];
        const resultImageUrl = `${COMFYUI_VIEW_URL_BASE}?filename=${encodeURIComponent(imgInfo.filename)}&type=${imgInfo.type}&subfolder=${encodeURIComponent(imgInfo.subfolder || '')}&t=${Date.now()}`; // Add timestamp to prevent caching / 添加时间戳以防止缓存

        if (outputPlaceholder) outputPlaceholder.style.display = 'none'; // Hide placeholder / 隐藏占位符
        updateStatusIndicator('渲染完成', 'ready');

        if (resultLayerImg && resultWrapper) {
            resultLayerImg.src = resultImageUrl;
            resultWrapper.style.display = 'block'; // Make the wrapper visible / 使包装器可见
            console.log("Result image source set:", resultImageUrl);
        } else { console.error("结果图层/图像元素未找到！ / Result layer/image element not found!"); }

    } catch (error) {
        console.error("获取/处理历史记录时出错 / Error fetching/processing history:", error);
        updateStatusIndicator('获取结果失败', 'error');
        if (outputPlaceholder) outputPlaceholder.style.display = 'flex'; // Show placeholder on error / 出错时显示占位符
        if(resultWrapper) resultWrapper.style.display = 'none';
        if(resultLayerImg) resultLayerImg.src = '';
    } finally {
        // Re-enable render button based on current connection status
        // 根据当前连接状态重新启用渲染按钮
        checkComfyUIConnection();
        // Update footer to idle (unless WS is still busy with another prompt)
        // 更新页脚为空闲状态（除非 WS 仍忙于处理另一个提示）
        if (!currentPromptId) { // Only set to idle if no prompt is tracked / 仅当没有跟踪提示时才设置为空闲
             const queue = comfyUISocket?.readyState === WebSocket.OPEN ? (/* try to get queue info */ 0) : 0; // Simplified check / 简化检查
             if (queue === 0) updateFooter('WebSocket 空闲', 'idle');
        }
    }
}

// --- NEW: ComfyUI Reachability Polling (Req 1) ---
// --- 新增：ComfyUI 可达性轮询 (Req 1) ---
/** Updates the display for ComfyUI API connection status / 更新 ComfyUI API 连接状态的显示 */
function updateComfyStatusDisplay(isReachable, message = '') {
    if (!comfyStatusElement) return; // Ensure element exists / 确保元素存在

    if (isReachable) {
        comfyStatusElement.textContent = 'ComfyUI: Connected';
        comfyStatusElement.style.color = '#90ee90'; // Light green / 浅绿色
    } else {
        comfyStatusElement.textContent = `ComfyUI: Disconnected`;
        comfyStatusElement.style.color = '#ff6b6b'; // Light red / 浅红色
        console.warn(`ComfyUI API Status: Disconnected. Reason: ${message}`);
    }

    // Update render button state based on reachability
    // 根据可达性更新渲染按钮状态
    if (renderBtn) {
         const isCurrentlyProcessing = currentPromptId !== null; // Check if we are waiting for a result / 检查是否正在等待结果
         renderBtn.disabled = !isReachable || isCurrentlyProcessing; // Disable if disconnected OR processing / 如果断开连接或正在处理则禁用

         if (!isReachable) {
             renderBtn.textContent = '等待连接... / Waiting...';
         } else if (isCurrentlyProcessing) {
              // Keep the "Requesting..." or similar text if already processing
              // 如果已在处理中，则保留“请求中...”或类似文本
              // The click handler sets the "Requesting..." text
              // 点击处理程序设置“请求中...”文本
         }
          else {
             // Only reset to default text if enabled and not processing
             // 仅当启用且未处理时才重置为默认文本
             renderBtn.textContent = '渲染 / Render';
         }
    }
}

/** Pings the Flask backend to check ComfyUI API reachability / Ping Flask 后端以检查 ComfyUI API 可达性 */
async function checkComfyUIConnection() {
    // console.log("Pinging ComfyUI status..."); // Optional debug log / 可选调试日志
    try {
        const response = await fetch(`${APP_API_BASE}/api/ping_comfyui`, {
             method: 'GET',
             cache: 'no-store' // Prevent browser caching / 阻止浏览器缓存
            });
        // No need to check response.ok here, rely on the success field in JSON
        // 此处无需检查 response.ok，依赖 JSON 中的 success 字段
        const data = await response.json();
        updateComfyStatusDisplay(data.success, data.message);
    } catch (error) {
        // Network error likely means Flask backend itself is down
        // 网络错误可能意味着 Flask 后端本身已关闭
        console.error('Error pinging ComfyUI (Network Error or Flask Down):', error);
        updateComfyStatusDisplay(false, 'Network Error');
    }
}
// --- End NEW Polling Code ---


// --- DOM Initialization ---
// --- DOM 初始化 ---
document.addEventListener('DOMContentLoaded', () => {
    console.log("DOM fully loaded and parsed");

    // --- Get Element References (ensure all exist) ---
    // --- 获取元素引用 (确保都存在) ---
    const outputArea = document.getElementById('output-display');
    const outputPlaceholder = outputArea?.querySelector('.output-placeholder');
    const resultWrapper = document.querySelector('.output-result-wrapper');
    const resultLayerImg = resultWrapper?.querySelector('#output-result-layer img');
    // const workflowSelect = document.getElementById('workflow-select'); // REMOVED / 已移除
    // Render button reference is already available globally (renderBtn) / 渲染按钮引用已全局可用 (renderBtn)
    const lineDraftInput = document.getElementById('line-draft-input');
    const referenceInput = document.getElementById('reference-input');
    const textPromptInput = document.getElementById('text-prompt');
    const controlStrengthSlider = document.getElementById('control-strength');
    const cardCountSlider = document.getElementById('card-count');
    const controlStrengthValue = document.getElementById('control-strength-value');
    const cardCountValue = document.getElementById('card-count-value');
    const saveBtn = document.getElementById('save-btn');
    const saveLargeBtn = document.getElementById('save-large-btn');
    const editToolbarElement = document.getElementById('edit-toolbar');

    // --- Initial UI State ---
    // Render button state is handled by the polling function now / 渲染按钮状态现在由轮询函数处理
    if (renderBtn) {
        renderBtn.disabled = true; // Start disabled / 开始时禁用
        renderBtn.textContent = '检查连接... / Checking...';
    } else { console.error("Init Error: Render button not found."); }
    // updateRenderButtonState(); // REMOVED / 已移除
    // if (workflowSelect) { workflowSelect.removeEventListener('change', updateRenderButtonState); } // REMOVED / 已移除


    // --- Slider Value Display & Staging ---
    if(controlStrengthSlider && controlStrengthValue) {
        stageData('current_strength', 'Float', controlStrengthSlider.value); // Stage initial value / 暂存初始值
        const stageStrength = debounce(() => stageData('current_strength', 'Float', controlStrengthSlider.value), 300);
        controlStrengthSlider.addEventListener('input', (e) => { controlStrengthValue.textContent = parseFloat(e.target.value).toFixed(2); stageStrength(); });
        controlStrengthValue.textContent = parseFloat(controlStrengthSlider.value).toFixed(2); // Set initial display / 设置初始显示
    } else { console.error("Init Error: Strength slider or value span not found."); }

    if(cardCountSlider && cardCountValue) {
         stageData('current_count', 'Int', cardCountSlider.value); // Stage initial value / 暂存初始值
         const stageCount = debounce(() => stageData('current_count', 'Int', cardCountSlider.value), 300);
        cardCountSlider.addEventListener('input', (e) => { cardCountValue.textContent = e.target.value; stageCount(); });
        cardCountValue.textContent = cardCountSlider.value; // Set initial display / 设置初始显示
    } else { console.error("Init Error: Count slider or value span not found."); }

    // --- Text Input Staging ---
     if(textPromptInput) {
         if (textPromptInput.value) { stageData('current_prompt', 'Text', textPromptInput.value); } // Stage initial value / 暂存初始值
         const stagePrompt = debounce(() => stageData('current_prompt', 'Text', textPromptInput.value), 500);
         textPromptInput.addEventListener('input', stagePrompt);
     } else { console.error("Init Error: Text prompt input not found."); }


    // --- Image Upload Logic (using new staging setup) ---
    setupInputStaging('line-draft-input', 'line-draft-preview', 'current_line_draft', 'Image');
    setupInputStaging('reference-input', 'reference-preview', 'current_reference', 'Image');

    // --- Render Button Click Listener ---
    // Ensure all required elements for rendering are available / 确保渲染所需的所有元素都可用
    if (renderBtn && outputPlaceholder && resultWrapper && resultLayerImg) {
        renderBtn.addEventListener('click', async () => {
            if (renderBtn.disabled) return; // Should be prevented by UI state, but double-check / UI 状态应阻止，但再次检查
            console.log("Render button clicked!");
            // const selectedWorkflowKey = workflowSelect.value; // REMOVED / 已移除
            // if (!selectedWorkflowKey) { alert("请先选择工作流。 / Please select a workflow first."); return; } // REMOVED / 已移除

            // --- UI Reset and Feedback ---
            renderBtn.disabled = true; // Disable button during request / 请求期间禁用按钮
            renderBtn.textContent = '请求中... / Requesting...';
            hideStatusIndicator(); // Hide top-right indicator / 隐藏右上角指示器
            outputPlaceholder.style.display = 'flex'; // Show placeholder / 显示占位符
            outputPlaceholder.textContent = '正在触发执行... / Triggering execution...';
            resultWrapper.style.display = 'none'; // Hide previous result / 隐藏先前结果
            resultLayerImg.src = ''; // Clear previous image src / 清除先前图像 src
            currentPromptId = null; currentOutputNodeId = null; // Reset tracking IDs / 重置跟踪 ID
            updateFooter('正在触发工作流...', 'progress'); // Update footer status / 更新页脚状态
            // --- End UI Reset ---

            // --- Trigger prompt via Flask backend (using live workflow) ---
            // --- 通过 Flask 后端触发提示 (使用实时工作流) ---
            const payload = {}; // No specific payload needed now / 现在不需要特定载荷
            console.log('Sending trigger request to backend (using live workflow):', payload);

            try {
                const response = await fetch(`${APP_API_BASE}/api/trigger_prompt`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', },
                    body: JSON.stringify(payload) // Send empty or general data / 发送空数据或通用数据
                });
                const result = await response.json();

                // Handle backend errors during trigger request
                // 处理触发请求期间的后端错误
                if (!response.ok || !result.success) {
                    let errorMsg = result.message || `Trigger API Error ${response.status}`;
                     if (result.details) errorMsg += `\nDetails: ${JSON.stringify(result.details)}`;
                     if (result.node_errors) errorMsg += `\nNode Errors: ${JSON.stringify(result.node_errors)}`;
                    throw new Error(errorMsg); // Throw to be caught below / 抛出以便下面捕获
                }

                // Success! Backend has queued the prompt
                // 成功！后端已将提示排队
                console.log('Backend Trigger Request Success:', result);
                outputPlaceholder.textContent = '任务已提交，等待 ComfyUI 处理... / Job submitted, waiting for ComfyUI...';
                updateStatusIndicator('任务已提交', 'busy'); // Show busy status / 显示繁忙状态
                currentPromptId = result.prompt_id; // Track the definitive prompt ID / 跟踪明确的提示 ID
                currentOutputNodeId = result.output_node_id; // Track the output node ID (can be null) / 跟踪输出节点 ID（可以为 null）
                // The WebSocket listener will now track progress for currentPromptId
                // WebSocket 监听器现在将跟踪 currentPromptId 的进度

            } catch (error) {
                // Handle fetch errors or errors thrown from backend response check
                // 处理 fetch 错误或从后端响应检查中抛出的错误
                console.error('Error triggering prompt:', error);
                outputPlaceholder.textContent = `触发执行失败 / Trigger failed: ${error.message}`;
                updateStatusIndicator('触发失败', 'error');
                updateFooter('触发失败', 'disconnected');
                // Re-enable button based on current connection status (async check)
                // 根据当前连接状态重新启用按钮（异步检查）
                checkComfyUIConnection();
            }
        });
    } else {
        console.error("Init Error: Cannot find required elements for render button listener (renderBtn, outputPlaceholder, resultWrapper, resultLayerImg).");
        if(renderBtn) renderBtn.disabled = true; // Ensure button is disabled if setup fails / 如果设置失败，确保按钮被禁用
    }

    // --- Other Button Listeners ---
    if(saveBtn) saveBtn.addEventListener('click', () => { console.log('Save clicked'); updateStatusIndicator("保存功能未实现 / Save not implemented", "error"); });
    if(saveLargeBtn) saveLargeBtn.addEventListener('click', () => { console.log('Save Large clicked'); updateStatusIndicator("放大并保存功能未实现 / Upscale not implemented", "error"); });
    if (editToolbarElement) { editToolbarElement.querySelectorAll('.edit-icon').forEach((icon, index) => { icon.addEventListener('click', () => { console.log(`Edit Icon ${index + 1} clicked`); updateStatusIndicator(`编辑工具 ${index+1} 未实现 / Edit tool ${index+1} not implemented`, "error"); }); }); }

    // --- Initialize ComfyUI WebSocket Connection ---
    connectComfyUIWebSocket(); // Start WS connection / 启动 WS 连接

    // --- Start Connection Polling (Req 1) ---
    checkComfyUIConnection(); // Perform initial check immediately / 立即执行初始检查
    setInterval(checkComfyUIConnection, 5000); // Start polling every 5 seconds / 每 5 秒开始轮询

}); // End DOMContentLoaded