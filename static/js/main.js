document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('comfyflow-form');
    const lineartInput = document.getElementById('lineart_image');
    const referenceInput = document.getElementById('reference_image');
    const lineartPreview = document.getElementById('lineart_preview');
    const referencePreview = document.getElementById('reference_preview');
    const cnSlider = document.getElementById('control_strength');
    const cnValueSpan = document.getElementById('cn_value');
    const statusDiv = document.getElementById('status');
    const resultsDiv = document.getElementById('results');
    const runButton = document.getElementById('run_button');

    let currentPromptId = null; // Store the latest prompt ID / 存储最新的提示 ID
    let pollingInterval = null; // Interval ID for polling results / 用于轮询结果的间隔 ID

    // Function to preview image / 预览图像函数
    function previewImage(input, previewElement) {
        input.addEventListener('change', function(event) {
            const file = event.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = function(e) {
                    previewElement.src = e.target.result;
                    previewElement.style.display = 'block';
                }
                reader.readAsDataURL(file);
            } else {
                previewElement.src = '#';
                previewElement.style.display = 'none';
            }
        });
    }

    // Setup previews / 设置预览
    previewImage(lineartInput, lineartPreview);
    previewImage(referenceInput, referencePreview);

    // Update slider value display / 更新滑块值显示
    cnSlider.addEventListener('input', function() {
        cnValueSpan.textContent = cnSlider.value;
    });

    // Form submission handler / 表单提交处理程序
    form.addEventListener('submit', function(event) {
        event.preventDefault(); // Prevent default form submission / 阻止默认表单提交
        statusDiv.textContent = '正在提交任务... / Submitting job...';
        resultsDiv.innerHTML = '<h2>成果输出:</h2>'; // Clear previous results / 清除先前结果
        runButton.disabled = true; // Disable button during processing / 处理期间禁用按钮
        stopPolling(); // Stop any previous polling / 停止任何先前的轮询

        const formData = new FormData(form); // Use FormData to handle file uploads / 使用 FormData 处理文件上传

        fetch('/run_workflow', { // Send to Flask backend endpoint / 发送到 Flask 后端端点
            method: 'POST',
            body: formData // Send form data including files / 发送包含文件的表单数据
        })
        .then(response => response.json())
        .then(data => {
            if (data.success && data.prompt_id) {
                currentPromptId = data.prompt_id;
                statusDiv.textContent = `任务已提交 (ID: ${currentPromptId})，等待执行... / Job submitted (ID: ${currentPromptId}), waiting for execution...`;
                startPolling(currentPromptId); // Start polling for results / 开始轮询结果
            } else {
                statusDiv.textContent = `提交失败 / Submission failed: ${data.error || 'Unknown error'}`;
                console.error("Submission Error:", data);
                runButton.disabled = false; // Re-enable button on failure / 失败时重新启用按钮
            }
        })
        .catch(error => {
            console.error('Error:', error);
            statusDiv.textContent = `提交请求时出错 / Error submitting request: ${error}`;
            runButton.disabled = false; // Re-enable button on error / 出错时重新启用按钮
        });
    });

    // Function to start polling for results / 开始轮询结果的函数
    function startPolling(promptId) {
        stopPolling(); // Ensure only one poll runs at a time / 确保一次只运行一个轮询

        pollingInterval = setInterval(() => {
            fetch(`/get_result/${promptId}`)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (data.status === 'completed') {
                        statusDiv.textContent = '生成完成! / Generation complete!';
                        displayResults(data.images || []);
                        stopPolling();
                        runButton.disabled = false; // Re-enable button on completion / 完成时重新启用按钮
                    } else if (data.status === 'pending') {
                        // Optional: Update status to indicate it's still running
                        // 可选：更新状态以指示仍在运行
                         statusDiv.textContent = `任务 (ID: ${promptId}) 正在处理中... / Job (ID: ${promptId}) is processing...`;
                    } else {
                         // Handle other potential statuses if backend provides them
                         // 如果后端提供其他潜在状态，则进行处理
                         statusDiv.textContent = `任务状态未知 / Unknown job status: ${data.status}`;
                         stopPolling();
                         runButton.disabled = false;
                    }
                } else {
                     statusDiv.textContent = `轮询结果时出错 / Error polling results: ${data.error || 'Unknown error'}`;
                     stopPolling();
                     runButton.disabled = false;
                }
            })
            .catch(error => {
                 console.error('Polling Error:', error);
                 statusDiv.textContent = `轮询请求失败 / Polling request failed: ${error}`;
                 stopPolling();
                 runButton.disabled = false;
            });
        }, 3000); // Poll every 3 seconds (adjust as needed) / 每 3 秒轮询一次 (根据需要调整)
    }

    // Function to stop polling / 停止轮询的函数
    function stopPolling() {
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    }

    // Function to display results / 显示结果的函数
    function displayResults(imageUrls) {
        resultsDiv.innerHTML = '<h2>成果输出:</h2>'; // Clear placeholder / 清除占位符
        if (imageUrls.length > 0) {
            imageUrls.forEach(url => {
                const img = document.createElement('img');
                img.src = url; // Use the URL provided by the backend (pointing to ComfyUI's /view endpoint) / 使用后端提供的 URL (指向 ComfyUI 的 /view 端点)
                img.alt = 'Generated Image / 生成的图像';
                resultsDiv.appendChild(img);
            });
        } else {
            resultsDiv.innerHTML += '<p>未生成任何图像。 / No images were generated.</p>';
        }
    }

});