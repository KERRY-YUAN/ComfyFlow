# File: app.py
# Version 2.0.1 (No functional changes, verified paths and rendering)

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
from flask_cors import CORS  # Import CORS / 导入 CORS
import os
import json
import uuid
import websocket # Use websocket-client library / 使用 websocket-client 库
import requests # For uploading images / 用于上传图片
import threading
import time
import base64
from io import BytesIO
from PIL import Image
import sys # Import sys for path manipulation / 导入 sys 用于路径操作

# --- Configuration / 配置 ---
# Determine the base directory of the script / 确定脚本的基础目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Add the base directory to the Python path / 将基础目录添加到 Python 路径
sys.path.insert(0, BASE_DIR)

# Static and template folder configuration / 静态和模板文件夹配置
# Assumes 'static' and 'templates' are in the same directory as app.py / 假设 'static' 和 'templates' 与 app.py 在同一目录中
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
TEMPLATE_FOLDER = os.path.join(BASE_DIR, 'templates')

# ComfyUI Configuration / ComfyUI 配置
# IMPORTANT: Update this path to your actual ComfyUI workflows directory / 重要提示：将此路径更新为你的实际 ComfyUI 工作流目录
COMFYUI_WORKFLOWS_PATH = r"D:\Program\ComfyUI_Program\ComfyUI\user\default\workflows"
# IMPORTANT: Update this path to your actual ComfyUI input directory / 重要提示：将此路径更新为你的实际 ComfyUI 输入目录
COMFYUI_INPUT_PATH = r"D:\Program\ComfyUI_Program\ComfyUI\input"
# IMPORTANT: Update this path to your actual ComfyUI output directory / 重要提示：将此路径更新为你的实际 ComfyUI 输出目录
COMFYUI_OUTPUT_PATH = r"D:\Program\ComfyUI_Program\ComfyUI\output"
COMFYUI_API_ADDRESS = "127.0.0.1:8188" # Default ComfyUI API address / 默认 ComfyUI API 地址

# --- Flask App Setup / Flask 应用设置 ---
# Verify template and static folders exist / 验证模板和静态文件夹存在
print(f"[*] Template folder: {TEMPLATE_FOLDER} (Exists: {os.path.isdir(TEMPLATE_FOLDER)})")
print(f"[*] Static folder: {STATIC_FOLDER} (Exists: {os.path.isdir(STATIC_FOLDER)})")

app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
app.config['SECRET_KEY'] = 'your_very_secret_key' # Change this! / 修改这个！
CORS(app) # Enable CORS for all routes / 为所有路由启用 CORS
# Use gevent-websocket for SocketIO / 为 SocketIO 使用 gevent-websocket
# Use eventlet or gevent for production / 在生产环境中使用 eventlet 或 gevent
# Example using eventlet: pip install eventlet
# socketio = SocketIO(app, async_mode='eventlet')
# Example using gevent: pip install gevent gevent-websocket
socketio = SocketIO(app, async_mode='gevent') # Keep gevent for now / 现在保留 gevent

# Dictionary to store client-specific data / 用于存储客户端特定数据的字典
client_data = {}

# --- Helper Functions / 辅助函数 ---

def save_base64_image(base64_string, filename_prefix):
    """Saves a base64 encoded image to the ComfyUI input directory."""
    """将 base64 编码的图像保存到 ComfyUI 输入目录。"""
    if not base64_string:
        return None
    try:
        # Extract mime type and base64 data / 提取 mime 类型和 base64 数据
        header, encoded = base64_string.split(',', 1)
        # Determine file extension / 确定文件扩展名
        if "image/png" in header:
            ext = ".png"
        elif "image/jpeg" in header or "image/jpg" in header:
            ext = ".jpg"
        else:
            ext = ".png" # Default to png / 默认为 png

        image_data = base64.b64decode(encoded)
        image = Image.open(BytesIO(image_data))

        # Generate a unique filename / 生成唯一文件名
        unique_filename = f"{filename_prefix}_{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(COMFYUI_INPUT_PATH, unique_filename)

        # Ensure the input directory exists / 确保输入目录存在
        os.makedirs(COMFYUI_INPUT_PATH, exist_ok=True)

        image.save(save_path)
        print(f"[*] Image saved to: {save_path}") # Log save path / 记录保存路径
        # Return the filename relative to the input directory / 返回相对于输入目录的文件名
        return unique_filename
    except Exception as e:
        print(f"[Error] Saving base64 image: {e}") # Log error / 记录错误
        return None

def find_node_by_type(workflow_data, node_type):
    """Finds the first node ID matching the given type in the workflow."""
    """在工作流中查找与给定类型匹配的第一个节点 ID。"""
    for node_id, node_info in workflow_data.items():
        if node_info.get("class_type") == node_type:
            return node_id
    return None

def find_nodes_by_type(workflow_data, node_type):
    """Finds all node IDs matching the given type in the workflow."""
    """在工作流中查找与给定类型匹配的所有节点 ID。"""
    ids = []
    for node_id, node_info in workflow_data.items():
        if node_info.get("class_type") == node_type:
            ids.append(node_id)
    return ids

def find_node_by_title(workflow_data, node_title):
    """Finds the first node ID matching the given title in the workflow."""
    """在工作流中查找与给定标题匹配的第一个节点 ID。"""
    for node_id, node_info in workflow_data.items():
        # ComfyUI stores title in _meta_ / ComfyUI 将标题存储在 _meta_ 中
        if node_info.get("_meta", {}).get("title") == node_title:
            return node_id
    return None

def queue_comfyui_prompt(prompt_data, client_id):
    """Sends the workflow prompt to the ComfyUI API and starts listening."""
    """将工作流提示发送到 ComfyUI API 并开始监听。"""
    ws = None # Initialize ws to None / 将 ws 初始化为 None
    try:
        ws_url = f"ws://{COMFYUI_API_ADDRESS}/ws?clientId={client_id}"
        ws = websocket.create_connection(ws_url)
        print(f"[*] WebSocket connected to ComfyUI: {ws_url}") # Log connection / 记录连接

        # Send the prompt / 发送提示
        # Wrap the prompt data correctly / 正确包装提示数据
        prompt_to_send = {"prompt": prompt_data, "client_id": client_id}
        ws.send(json.dumps(prompt_to_send))
        print(f"[*] Prompt sent for client: {client_id}") # Log prompt sending / 记录提示发送

        # Listen for messages / 监听消息
        while True:
            message_str = ws.recv()
            if not message_str:
                print("[Warning] WebSocket received empty message, breaking loop.") # Log empty message / 记录空消息
                break # Break if connection closes / 如果连接关闭则中断

            message = json.loads(message_str)
            # print(f"[*] Received WS message: {message}") # Debug: Print all messages / 调试：打印所有消息

            if message['type'] == 'status':
                status_data = message['data']['status']
                execinfo = status_data.get('execinfo', {})
                queue_remaining = execinfo.get('queue_remaining', 'N/A')
                print(f"[*] Queue status: {queue_remaining} remaining") # Log queue status / 记录队列状态
                # Optionally send progress to frontend / 可选地将进度发送到前端
                socketio.emit('status_update', {'status': 'running', 'queue_remaining': queue_remaining}, room=client_id)

            elif message['type'] == 'executing':
                node_id = message['data']['node']
                # Use the original prompt_data to find the title / 使用原始 prompt_data 查找标题
                node_info = prompt_data.get(str(node_id), {}) # Node IDs in prompt are strings / prompt 中的 Node ID 是字符串
                node_title = node_info.get('_meta', {}).get('title', f'Node {node_id}')
                if node_id is not None:
                    print(f"[*] Executing node: {node_title} ({node_id})") # Log executing node / 记录正在执行的节点
                    socketio.emit('status_update', {'status': 'executing', 'node_id': node_id, 'node_title': node_title}, room=client_id)
                # If it's the final node / 如果是最终节点
                if message['data']['prompt_id'] == client_data.get(client_id, {}).get('prompt_id') and node_id is None:
                    print("[*] Execution finished according to 'executing' message with node=None.") # Log execution finish / 记录执行完成
                    break # End of execution for this prompt / 此提示的执行结束

            elif message['type'] == 'executed':
                node_id = message['data']['node']
                output_data = message['data']['outputs']
                prompt_id_from_msg = message['data']['prompt_id']

                # Check if this execution belongs to the current client's request / 检查此执行是否属于当前客户端的请求
                if client_id in client_data and prompt_id_from_msg == client_data[client_id].get('prompt_id'):
                    print(f"[*] Node {node_id} executed for prompt {prompt_id_from_msg}.") # Log node execution / 记录节点执行

                    # --- Check if this is the NodeBridge_Output node ---
                    # Node IDs in prompt keys are strings / prompt 键中的节点 ID 是字符串
                    node_info = prompt_data.get(str(node_id), {})
                    node_type = node_info.get("class_type")
                    node_title = node_info.get("_meta", {}).get("title", f"Node {node_id}")

                    # Also check the node title in case class_type isn't unique enough / 同时检查节点标题以防 class_type 不够唯一
                    # Example: Check if node_title == "NodeBridge Output"
                    # 示例：检查 node_title 是否 == "NodeBridge Output"
                    # Or better, check the class type directly from the loaded node data
                    # 或者更好的是，直接从加载的节点数据检查类类型

                    # Use class_type for reliability / 使用 class_type 以确保可靠性
                    if node_type == "NodeBridge_Output":
                        print(f"[*] Detected NodeBridge_Output execution: Node {node_title} ({node_id})") # Log output node detection / 记录输出节点检测
                        if 'images' in output_data:
                            print(f"[*] Output images found: {len(output_data['images'])}") # Log image count / 记录图像数量
                            final_images_base64 = []
                            for img_info in output_data['images']:
                                filename = img_info['filename']
                                # Construct full path to the output image / 构建输出图像的完整路径
                                # Handle potential subfolder / 处理潜在的子文件夹
                                subfolder = img_info.get('subfolder', '') # Get subfolder, default to empty string / 获取子文件夹，默认为空字符串
                                img_path = os.path.join(COMFYUI_OUTPUT_PATH, subfolder, filename)

                                try:
                                    if os.path.exists(img_path):
                                        with Image.open(img_path) as img:
                                            buffered = BytesIO()
                                            img_format = img.format if img.format else 'PNG' # Handle case where format is None / 处理格式为 None 的情况
                                            if img_format.upper() == 'JPEG':
                                                mime_type = 'image/jpeg'
                                            else:
                                                 mime_type = 'image/png' # Default to PNG / 默认为 PNG

                                            # Convert RGBA to RGB if saving as JPEG / 如果保存为 JPEG，将 RGBA 转换为 RGB
                                            save_format = 'JPEG' if mime_type == 'image/jpeg' else 'PNG'
                                            if save_format == 'JPEG' and img.mode == 'RGBA':
                                                img = img.convert('RGB')

                                            img.save(buffered, format=save_format)
                                            img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
                                            final_images_base64.append(f"data:{mime_type};base64,{img_base64}")
                                        print(f"[*] Processed output image: {filename}") # Log processed image / 记录已处理的图像
                                    else:
                                        print(f"[Error] Output image file not found at {img_path}") # Log file not found / 记录文件未找到
                                except Exception as e:
                                    print(f"[Error] Processing output image {filename}: {e}") # Log image processing error / 记录图像处理错误

                            if final_images_base64:
                                # Send results back to the specific client via Flask-SocketIO / 通过 Flask-SocketIO 将结果发送回特定客户端
                                socketio.emit('render_result', {'images': final_images_base64}, room=client_id)
                                print(f"[*] Sent {len(final_images_base64)} images to client {client_id}") # Log result sending / 记录结果发送
                            else:
                                print(f"[Warning] No images processed for NodeBridge_Output {node_id}") # Log no images processed / 记录未处理图像
                                socketio.emit('render_error', {'message': 'No images generated or processed'}, room=client_id)
                        else:
                             print(f"[Warning] NodeBridge_Output {node_id} executed but no 'images' key in output data.") # Log missing images key / 记录缺少 images 键
                             socketio.emit('render_error', {'message': 'NodeBridge_Output did not produce image data'}, room=client_id)
                        # Optional: break here if you only care about the first output node / 可选：如果只关心第一个输出节点，则在此处中断
                        # break
                else:
                    # Message from a different prompt or client, ignore / 来自不同提示或客户端的消息，忽略
                    pass


            elif message['type'] == 'progress':
                # Handle progress updates if needed / 如果需要，处理进度更新
                progress = message['data']['value']
                total = message['data']['max']
                # Progress might be associated with a node / 进度可能与节点相关
                node_id = message.get('data', {}).get('node')
                node_title = "Overall Progress" # Default title / 默认标题
                if node_id:
                     # Node IDs in prompt keys are strings / prompt 键中的节点 ID 是字符串
                     node_info = prompt_data.get(str(node_id), {})
                     node_title = node_info.get('_meta', {}).get('title', f'Node {node_id}')

                # print(f"[*] Progress: {progress}/{total} for {node_title}") # Log progress / 记录进度
                socketio.emit('progress_update', {'progress': progress, 'total': total, 'node_title': node_title}, room=client_id)

            # Check for execution end signal (often 'executing' with node=None) / 检查执行结束信号（通常是带有 node=None 的 'executing'）
            if message['type'] == 'executing' and message['data']['node'] is None:
                 # Check if it matches the prompt_id we are tracking / 检查它是否与我们正在跟踪的 prompt_id 匹配
                 if client_id in client_data and message['data']['prompt_id'] == client_data[client_id].get('prompt_id'):
                     print(f"[*] Execution finished signal received for prompt {client_data[client_id]['prompt_id']}.") # Log finish signal / 记录完成信号
                     socketio.emit('status_update', {'status': 'finished'}, room=client_id) # Send finished status / 发送完成状态
                     break # Exit the loop as the tracked prompt is done / 退出循环，因为跟踪的提示已完成


    except websocket.WebSocketException as e:
        print(f"[Error] ComfyUI WebSocket Error: {e}") # Log WebSocket error / 记录 WebSocket 错误
        socketio.emit('render_error', {'message': f'ComfyUI Connection Error: {e}'}, room=client_id)
    except ConnectionRefusedError:
        print("[Error] Connection to ComfyUI WebSocket refused. Is ComfyUI running?") # Log connection refused / 记录连接被拒绝
        socketio.emit('render_error', {'message': 'Connection to ComfyUI refused. Is ComfyUI running?'}, room=client_id)
    except Exception as e:
        print(f"[Error] An unexpected error occurred in ComfyUI communication thread: {e}") # Log unexpected error / 记录意外错误
        import traceback
        traceback.print_exc() # Print detailed traceback / 打印详细的回溯信息
        socketio.emit('render_error', {'message': f'An unexpected error occurred: {e}'}, room=client_id)
    finally:
        if ws and ws.connected:
            try:
                ws.close()
                print("[*] ComfyUI WebSocket connection closed.") # Log connection closed / 记录连接关闭
            except Exception as e:
                print(f"[Error] Closing ComfyUI WebSocket: {e}") # Log closing error / 记录关闭错误
        # Clean up client data for this request / 清理此请求的客户端数据
        # Keep client data for potential multiple results? Clear on disconnect instead.
        # 为潜在的多个结果保留客户端数据？在断开连接时清除。
        # if client_id in client_data:
        #      print(f"[*] Cleaning up data for client {client_id}") # Log cleanup / 记录清理
        #      del client_data[client_id]

# --- SocketIO Events / SocketIO 事件 ---
@socketio.on('connect')
def handle_connect():
    """Handles new client connections."""
    """处理新的客户端连接。"""
    client_id = request.sid # Use SocketIO session ID as client ID / 使用 SocketIO 会话 ID 作为客户端 ID
    print(f"[*] Client connected: {client_id}") # Log connection / 记录连接
    # Initialize client data structure / 初始化客户端数据结构
    client_data[client_id] = {'status': 'connected'}

@socketio.on('disconnect')
def handle_disconnect():
    """Handles client disconnections."""
    """处理客户端断开连接。"""
    client_id = request.sid
    print(f"[*] Client disconnected: {client_id}") # Log disconnection / 记录断开连接
    # Clean up data associated with this client / 清理与此客户端关联的数据
    if client_id in client_data:
        del client_data[client_id]
        print(f"[*] Cleaned up data for disconnected client {client_id}") # Log cleanup / 记录清理

# --- Flask Routes / Flask 路由 ---
@app.route('/')
def index():
    """Serves the main HTML page."""
    """提供主 HTML 页面。"""
    print("[*] Request received for / route, attempting to render index.html") # Log request / 记录请求
    try:
        # Ensure the template exists before trying to render / 在尝试渲染之前确保模板存在
        template_path = os.path.join(app.template_folder, 'index.html')
        if not os.path.exists(template_path):
             print(f"[Error] Template not found at: {template_path}") # Log template not found / 记录模板未找到
             return f"Error: Template 'index.html' not found in {app.template_folder}", 404
        return render_template('index.html')
    except Exception as e:
         print(f"[Error] Failed to render template: {e}") # Log rendering error / 记录渲染错误
         import traceback
         traceback.print_exc() # Print full traceback / 打印完整的回溯
         return f"An error occurred while rendering the page: {e}", 500


@app.route('/api/workflows', methods=['GET'])
def get_workflows():
    """API endpoint to list available ComfyUI workflow files."""
    """用于列出可用 ComfyUI 工作流文件的 API 端点。"""
    # @@Requirement 1 & 6: List workflows from the specified directory / 要求 1 和 6：列出指定目录中的工作流
    if not os.path.isdir(COMFYUI_WORKFLOWS_PATH):
        print(f"[Error] Workflows directory not found: {COMFYUI_WORKFLOWS_PATH}") # Log directory not found / 记录目录未找到
        return jsonify({"error": f"Workflow directory not found: {COMFYUI_WORKFLOWS_PATH}"}), 500

    try:
        workflows = [f for f in os.listdir(COMFYUI_WORKFLOWS_PATH) if f.endswith('.json')]
        print(f"[*] Found workflows: {workflows}") # Log found workflows / 记录找到的工作流
        return jsonify({"workflows": workflows})
    except Exception as e:
        print(f"[Error] Listing workflows: {e}") # Log listing error / 记录列出错误
        return jsonify({"error": f"Error listing workflows: {e}"}), 500

@app.route('/api/render', methods=['POST'])
def render_workflow():
    """API endpoint to trigger a ComfyUI workflow render."""
    """用于触发 ComfyUI 工作流渲染的 API 端点。"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON payload"}), 400

    # Get client ID from payload (more reliable) / 从有效负载获取客户端 ID（更可靠）
    client_id = data.get('clientId')
    if not client_id or client_id not in client_data:
         print(f"[Error] Invalid or missing clientId in render request: {client_id}") # Log invalid client ID / 记录无效客户端 ID
         # Look up SID if possible (might not work reliably across requests) / 如果可能，查找 SID（可能无法跨请求可靠地工作）
         # sid = request.sid # This might be None or different / 这可能是 None 或不同
         # print(f"[*] Request SID: {sid}")
         return jsonify({"error": "Missing or invalid clientId. Please reconnect."}), 400 # Ask client to reconnect / 要求客户端重新连接

    workflow_name = data.get('workflow')
    lineart_b64 = data.get('lineart') # Base64 encoded image / Base64 编码的图像
    reference_b64 = data.get('reference') # Base64 encoded image / Base64 编码的图像
    text_prompt = data.get('textPrompt', '')
    control_strength = float(data.get('controlStrength', 1.0))
    batch_count = int(data.get('batchCount', 1))

    if not workflow_name:
        return jsonify({"error": "Workflow name is required"}), 400

    workflow_path = os.path.join(COMFYUI_WORKFLOWS_PATH, workflow_name)
    if not os.path.isfile(workflow_path):
        return jsonify({"error": f"Workflow file not found: {workflow_name}"}), 404

    try:
        # 1. Load the base workflow / 1. 加载基础工作流
        with open(workflow_path, 'r', encoding='utf-8') as f:
            # Load the API format workflow / 加载 API 格式工作流
            # Usually, the .json file is the API format directly / 通常，.json 文件直接是 API 格式
            workflow_api_format = json.load(f)
        print(f"[*] Loaded workflow: {workflow_name}") # Log workflow loading / 记录工作流加载

        # Check if it's wrapped in 'prompt' key (sometimes happens with exports)
        # 检查它是否被包装在 'prompt' 键中（有时导出时会发生）
        if "prompt" in workflow_api_format and isinstance(workflow_api_format["prompt"], dict):
            workflow_data = workflow_api_format["prompt"]
            print("[*] Workflow seems wrapped, using content of 'prompt' key.") # Log wrapped workflow / 记录包装的工作流
        else:
            workflow_data = workflow_api_format # Assume it's the direct prompt dictionary / 假设它是直接的提示字典


        # 2. Handle Image Uploads (Save to ComfyUI input and get filenames) / 2. 处理图像上传（保存到 ComfyUI 输入并获取文件名）
        lineart_filename = save_base64_image(lineart_b64, "lineart_input")
        reference_filename = save_base64_image(reference_b64, "reference_input")

        # 3. Modify the workflow JSON / 3. 修改工作流 JSON
        prompt_id = str(uuid.uuid4()) # Generate unique ID for this execution / 为此执行生成唯一 ID
        client_data[client_id]['prompt_id'] = prompt_id # Store prompt ID / 存储提示 ID
        client_data[client_id]['status'] = 'processing'
        print(f"[*] Assigned prompt ID {prompt_id} to client {client_id}") # Log prompt ID assignment / 记录提示 ID 分配


        # --- Inject data into the workflow ---
        # @@Requirement 4 & 5 Implementation (Simplified - Injecting into nodes) / 要求 4 和 5 实现（简化 - 注入节点）

        # a) Update LoadImage nodes (assuming they exist and are titled appropriately) / a) 更新 LoadImage 节点（假设它们存在且标题适当）
        lineart_loader_id = find_node_by_title(workflow_data, "Load Lineart")
        reference_loader_id = find_node_by_title(workflow_data, "Load Reference")

        if lineart_loader_id and lineart_filename:
             # Node IDs in workflow_data keys are strings / workflow_data 键中的节点 ID 是字符串
             if lineart_loader_id in workflow_data:
                 workflow_data[lineart_loader_id]["inputs"]["image"] = lineart_filename
                 print(f"[*] Updated Load Lineart node ({lineart_loader_id}) with image: {lineart_filename}") # Log update / 记录更新
             else:
                  print(f"[Warning] Found Load Lineart ID {lineart_loader_id} by title, but key not in workflow data.") # Log warning / 记录警告
        elif lineart_filename:
            print("[Warning] Lineart image provided, but no 'Load Lineart' node found or ID mismatch in workflow.") # Log warning / 记录警告

        if reference_loader_id and reference_filename:
             if reference_loader_id in workflow_data:
                 workflow_data[reference_loader_id]["inputs"]["image"] = reference_filename
                 print(f"[*] Updated Load Reference node ({reference_loader_id}) with image: {reference_filename}") # Log update / 记录更新
             else:
                 print(f"[Warning] Found Load Reference ID {reference_loader_id} by title, but key not in workflow data.") # Log warning / 记录警告
        elif reference_filename:
            print("[Warning] Reference image provided, but no 'Load Reference' node found or ID mismatch in workflow.") # Log warning / 记录警告

        # b) Update NodeBridge_Input nodes / b) 更新 NodeBridge_Input 节点
        node_bridge_input_ids = find_nodes_by_type(workflow_data, "NodeBridge_Input")
        if not node_bridge_input_ids:
             print("[Warning] No 'NodeBridge_Input' nodes found in the workflow.") # Log warning / 记录警告

        for node_id in node_bridge_input_ids:
             if node_id in workflow_data: # Ensure the found ID exists as a key / 确保找到的 ID 作为键存在
                print(f"[*] Injecting data into NodeBridge_Input ({node_id})") # Log injection / 记录注入
                # Inject values / 注入值
                workflow_data[node_id]["inputs"]["Text"] = text_prompt
                workflow_data[node_id]["inputs"]["CN"] = control_strength
                workflow_data[node_id]["inputs"]["Count"] = batch_count
                # Image/Reference are handled by upstream LoadImage nodes / 图像/参考由上游 LoadImage 节点处理
             else:
                 print(f"[Warning] Found NodeBridge_Input ID {node_id} by type, but key not in workflow data.") # Log warning / 记录警告


        # Example: Update a specific node like KSampler's seed / 示例：更新特定节点，如 KSampler 的种子
        ksampler_ids = find_nodes_by_type(workflow_data, "KSampler") # Find all KSamplers / 查找所有 KSampler
        for ksampler_id in ksampler_ids:
             if ksampler_id in workflow_data:
                # Use a consistent seed generation for potential debugging / 使用一致的种子生成以进行潜在调试
                # Or use random seed: random.randint(0, 0xffffffffffffffff)
                # 或者使用随机种子: random.randint(0, 0xffffffffffffffff)
                seed = int(time.time() * 1000) % 0xffffffffffffffff # Example seed / 示例种子
                workflow_data[ksampler_id]["inputs"]["seed"] = seed
                print(f"[*] Updated KSampler node ({ksampler_id}) seed to {seed}.") # Log update / 记录更新
             else:
                  print(f"[Warning] Found KSampler ID {ksampler_id} by type, but key not in workflow data.") # Log warning / 记录警告


        # 4. Start ComfyUI execution in a separate thread / 4. 在单独的线程中启动 ComfyUI 执行
        # @@Requirement 3: Trigger ComfyUI run / 要求 3：触发 ComfyUI 运行
        print(f"[*] Queuing prompt for client {client_id} with prompt ID {prompt_id}") # Log queuing / 记录排队
        # Pass the modified workflow_data (the prompt dictionary) / 传递修改后的 workflow_data（提示字典）
        thread = threading.Thread(target=queue_comfyui_prompt, args=(workflow_data, client_id))
        thread.start()

        return jsonify({"message": "Workflow rendering started", "prompt_id": prompt_id, "client_id": client_id})

    except FileNotFoundError:
        return jsonify({"error": f"Workflow file not found: {workflow_path}"}), 404
    except json.JSONDecodeError as e:
         print(f"[Error] Invalid JSON in workflow file: {workflow_name} - {e}") # Log JSON error / 记录 JSON 错误
         return jsonify({"error": f"Invalid JSON in workflow file: {workflow_name}"}), 500
    except Exception as e:
        print(f"[Error] Processing render request: {e}") # Log error / 记录错误
        import traceback
        traceback.print_exc() # Print detailed traceback / 打印详细的回溯信息
        # Clean up client data in case of failure before thread start / 在线程启动前失败时清理客户端数据
        if client_id in client_data:
            # Reset status or remove prompt_id / 重置状态或删除 prompt_id
             client_data[client_id]['status'] = 'error'
             if 'prompt_id' in client_data[client_id]:
                 del client_data[client_id]['prompt_id']

        return jsonify({"error": f"An unexpected error occurred: {e}"}), 500


if __name__ == '__main__':
    print("[*] Starting Flask server with SocketIO...") # Log server start / 记录服务器启动
    # Use socketio.run to handle WebSockets correctly / 使用 socketio.run 正确处理 WebSocket
    # host='0.0.0.0' makes it accessible on your network / host='0.0.0.0' 使其在您的网络上可访问
    # Use allow_unsafe_werkzeug=True only if needed for reloader with gevent/eventlet / 仅当 gevent/eventlet 的重载器需要时才使用 allow_unsafe_werkzeug=True
    print(f"[*] Server running on http://0.0.0.0:5000")
    socketio.run(app, debug=True, host='0.0.0.0', port=5000) # Add allow_unsafe_werkzeug=True if debug reloader fails / 如果调试重载器失败，则添加 allow_unsafe_werkzeug=True