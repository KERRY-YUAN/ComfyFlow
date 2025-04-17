# File: app.py
# Version 3.0.0 (Real-time Bridge Support)

from flask import Flask, render_template, request, jsonify, send_from_directory
# Use gevent for SocketIO and monkey-patching for websocket-client within nodes
# 为 SocketIO 使用 gevent，并在节点内为 websocket-client 进行猴子补丁
# This might require running ComfyUI with gevent too, or careful environment setup.
# 这可能也需要使用 gevent 运行 ComfyUI，或者仔细设置环境。
# pip install gevent gevent-websocket
# from gevent import monkey
# monkey.patch_all() # Patch standard libraries for gevent compatibility / 修补标准库以实现 gevent 兼容性

from flask_socketio import SocketIO, emit, join_room, leave_room, Namespace # Import Namespace / 导入命名空间
from flask_cors import CORS
import os
import json
import uuid
import websocket # For main ComfyUI connection / 用于主 ComfyUI 连接
import requests # For potential external calls if needed / 如果需要，用于潜在的外部调用
import threading
import time
import base64
from io import BytesIO
from PIL import Image
import sys

# --- Configuration / 配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
STATIC_FOLDER = os.path.join(BASE_DIR, 'static')
TEMPLATE_FOLDER = os.path.join(BASE_DIR, 'templates')

# ComfyUI Configuration (Ensure these are correct) / ComfyUI 配置（确保这些是正确的）
COMFYUI_WORKFLOWS_PATH = r"D:\Program\ComfyUI_Program\ComfyUI\user\default\workflows"
COMFYUI_INPUT_PATH = r"D:\Program\ComfyUI_Program\ComfyUI\input" # Still needed if saving intermediary files / 如果保存中间文件，仍然需要
COMFYUI_OUTPUT_PATH = r"D:\Program\ComfyUI_Program\ComfyUI\output" # Needed for retrieving final output / 需要检索最终输出
COMFYUI_API_ADDRESS = "127.0.0.1:8188"

# --- Flask App Setup ---
app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)
app.config['SECRET_KEY'] = 'your_very_secret_key_v2' # Change this!
CORS(app)
# Explicitly use gevent for async mode / 显式使用 gevent 作为异步模式
socketio = SocketIO(app, async_mode='gevent', cors_allowed_origins="*") # Allow all origins for simplicity / 为简单起见允许所有来源

# --- Data Structures ---
# Map client_id (frontend user SID) to their current prompt info
# 将 client_id（前端用户 SID）映射到其当前提示信息
client_prompt_map = {} # { client_id: {'prompt_id': prompt_id, 'workflow_data': workflow_data} }
# Map prompt_id to the client_id that owns it
# 将 prompt_id 映射到拥有它的 client_id
prompt_client_map = {} # { prompt_id: client_id }
# Store pending requests from nodes waiting for frontend data
# 存储来自等待前端数据的节点的待处理请求
# Key: (prompt_id, node_id), Value: {'request_id': request_id, 'client_id': client_id, 'mode': mode, 'node_sid': node_sid}
pending_node_requests = {}

# --- Helper Functions ---
def tensor_to_base64(tensor):
    """Converts an image tensor to a list of Base64 strings."""
    if tensor is None: return []
    pil_images = tensor_to_pil(tensor) # Use helper from NodeBridge if available, or define here
    base64_list = []
    for img in pil_images:
        buffered = BytesIO()
        img.save(buffered, format="PNG") # Save as PNG
        img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
        base64_list.append(f"data:image/png;base64,{img_base64}")
    return base64_list

# Helper function copied from NodeBridge.py for consistency
# 为保持一致性，从 NodeBridge.py 复制的辅助函数
def tensor_to_pil(tensor):
    if tensor is None: return []
    images = tensor.cpu().numpy()
    images = (images * 255).clip(0, 255).astype(np.uint8)
    return [Image.fromarray(img) for img in images]


# --- ComfyUI Main WebSocket Listener ---
# (Similar to before, but NO data injection, just monitoring)
# （与之前类似，但没有数据注入，只是监控）
def queue_comfyui_prompt(prompt_data, client_id, prompt_id):
    """Sends the original workflow prompt and monitors execution."""
    """发送原始工作流提示并监控执行。"""
    ws = None
    comfyui_ws_url = f"ws://{COMFYUI_API_ADDRESS}/ws?clientId={client_id}" # Use client_id for ComfyUI WS too

    try:
        ws = websocket.create_connection(comfyui_ws_url)
        print(f"ComfyUI Main WS connected: {comfyui_ws_url}")

        # Send the unmodified prompt / 发送未修改的提示
        # IMPORTANT: We MUST inject the prompt_id and node_id into the node's inputs
        # so the node knows its context when it executes.
        # 重要提示：我们必须将 prompt_id 和 node_id 注入节点的输入中
        # 以便节点在执行时了解其上下文。
        modified_prompt = prompt_data.copy()
        for node_id, node_info in modified_prompt.items():
            if node_info.get("class_type") in ["NodeBridge_Input", "NodeBridge_Output"]:
                if "inputs" not in node_info: node_info["inputs"] = {}
                node_info["inputs"]["_prompt_id"] = prompt_id
                node_info["inputs"]["_node_id"] = node_id # Node ID is the key in the prompt dict
                print(f"Injecting context: prompt={prompt_id}, node={node_id} into {node_info.get('class_type')}")


        # Queue the prompt with the injected context / 将带有注入上下文的提示排队
        print(f"Queuing prompt {prompt_id} for client {client_id}")
        ws.send(json.dumps({'prompt': modified_prompt, 'client_id': client_id}))

        # --- Listener Loop ---
        while True:
            message_str = ws.recv()
            if not message_str:
                print("ComfyUI Main WS received empty message, breaking.")
                break

            message = json.loads(message_str)
            msg_type = message.get('type')
            msg_data = message.get('data', {})

            # --- Handle different message types ---
            if msg_type == 'status':
                status_info = msg_data.get('status', {})
                exec_info = status_info.get('execinfo', {})
                queue_remaining = exec_info.get('queue_remaining')
                current_prompt_id_executing = exec_info.get('prompt_id')

                status_text = f"队列 Queue: {queue_remaining}"
                if current_prompt_id_executing:
                     status_text += f", 执行中 Executing: {current_prompt_id_executing[:8]}..."

                 # Emit status to the specific client / 向特定客户端发出状态
                if prompt_id in prompt_client_map:
                     target_client = prompt_client_map[prompt_id]
                     socketio.emit('status_update', {'status': status_text}, room=target_client)

            elif msg_type == 'executing':
                exec_node_id = msg_data.get('node')
                exec_prompt_id = msg_data.get('prompt_id')

                # Notify frontend about node execution (if it's the relevant prompt)
                # 通知前端有关节点执行的信息（如果是相关的提示）
                if exec_prompt_id == prompt_id and exec_node_id is not None:
                    node_title = modified_prompt.get(exec_node_id, {}).get('_meta', {}).get('title', f'Node {exec_node_id}')
                    print(f"Executing node: {node_title} ({exec_node_id}) for prompt {prompt_id}")
                    socketio.emit('status_update', {'status': f"执行节点 Executing Node: {node_title}"}, room=client_id)

                # Detect end of execution for the tracked prompt
                # 检测跟踪提示的执行结束
                if exec_prompt_id == prompt_id and exec_node_id is None:
                    print(f"Execution finished signal received for prompt {prompt_id}.")
                    socketio.emit('status_update', {'status': "执行完成 Finishing execution..."}, room=client_id)
                    # Don't break immediately, wait for potential 'executed' messages, especially NodeBridge_Output
                    # 不要立即中断，等待潜在的 'executed' 消息，特别是 NodeBridge_Output
                    # break # Exit loop maybe? Let timeout handle it? Or explicit completion message?

            elif msg_type == 'executed':
                executed_node_id = msg_data.get('node')
                executed_prompt_id = msg_data.get('prompt_id')

                # Check if it's our prompt and the NodeBridge_Output node
                # 检查它是否是我们的提示以及 NodeBridge_Output 节点
                if executed_prompt_id == prompt_id:
                    node_info = modified_prompt.get(executed_node_id, {})
                    node_type = node_info.get("class_type")

                    if node_type == "NodeBridge_Output":
                        print(f"Detected NodeBridge_Output execution ({executed_node_id}) for prompt {prompt_id}.")
                        outputs = msg_data.get('outputs', {})
                        if 'images' in outputs:
                            print(f"Output images found: {len(outputs['images'])}")
                            final_images_base64 = []
                            for img_info in outputs['images']:
                                filename = img_info.get('filename')
                                subfolder = img_info.get('subfolder', '')
                                img_type = img_info.get('type', 'output') # Usually 'output' or 'temp'

                                if not filename: continue

                                # Construct full path
                                img_path = os.path.join(COMFYUI_OUTPUT_PATH if img_type == 'output' else COMFYUI_INPUT_PATH, subfolder, filename)

                                try:
                                    if os.path.exists(img_path):
                                        with Image.open(img_path) as img:
                                            buffered = BytesIO()
                                            img_format = img.format if img.format else 'PNG'
                                            mime_type = f'image/{img_format.lower()}'
                                            if img_format == 'JPEG' and img.mode == 'RGBA': img = img.convert('RGB')
                                            img.save(buffered, format=img_format)
                                            img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
                                            final_images_base64.append(f"data:{mime_type};base64,{img_base64}")
                                        print(f"Processed output image: {filename}")
                                    else:
                                        print(f"Error: Output image file not found at {img_path}")
                                except Exception as e:
                                    print(f"Error processing output image {filename}: {e}")

                            if final_images_base64:
                                socketio.emit('render_result', {'images': final_images_base64}, room=client_id)
                                print(f"Sent {len(final_images_base64)} images to client {client_id}")
                                # Now we can likely break the loop as we got the final output
                                # 现在我们可以中断循环了，因为我们得到了最终的输出
                                break
                            else:
                                print(f"NodeBridge_Output executed but no images processed.")
                                socketio.emit('render_error', {'message': 'No images generated or processed by NodeBridge_Output'}, room=client_id)
                                break # Break even if no images, output node finished
                        else:
                            print(f"NodeBridge_Output executed but no 'images' key in output data.")
                            socketio.emit('render_error', {'message': 'NodeBridge_Output did not produce image data'}, room=client_id)
                            break # Break, output node finished

            elif msg_type == 'progress':
                progress = msg_data.get('value', 0)
                total = msg_data.get('max', 0)
                # Emit progress to the specific client / 向特定客户端发出进度
                if prompt_id in prompt_client_map:
                     target_client = prompt_client_map[prompt_id]
                     percent = int((progress / total) * 100) if total > 0 else 0
                     socketio.emit('progress_update', {'progress': progress, 'total': total, 'percent': percent}, room=target_client)


    except websocket.WebSocketException as e:
        print(f"ComfyUI Main WS Error: {e}")
        if prompt_id in prompt_client_map:
             target_client = prompt_client_map[prompt_id]
             socketio.emit('render_error', {'message': f'ComfyUI Connection Error: {e}'}, room=target_client)
    except ConnectionRefusedError:
        print("Error: Connection to ComfyUI Main WS refused.")
        if prompt_id in prompt_client_map:
             target_client = prompt_client_map[prompt_id]
             socketio.emit('render_error', {'message': 'Connection to ComfyUI refused. Is ComfyUI running?'}, room=target_client)
    except Exception as e:
        print(f"An unexpected error occurred in ComfyUI listener thread: {e}")
        import traceback
        traceback.print_exc()
        if prompt_id in prompt_client_map:
             target_client = prompt_client_map[prompt_id]
             socketio.emit('render_error', {'message': f'An unexpected error occurred: {e}'}, room=target_client)
    finally:
        if ws and ws.connected:
            try:
                ws.close()
                print("ComfyUI Main WS connection closed.")
            except Exception as e:
                print(f"Error closing ComfyUI Main WS: {e}")
        # Clean up prompt mapping when listener exits / 监听器退出时清理提示映射
        if prompt_id in prompt_client_map:
            owner_client = prompt_client_map[prompt_id]
            del prompt_client_map[prompt_id]
            if owner_client in client_prompt_map and client_prompt_map[owner_client]['prompt_id'] == prompt_id:
                del client_prompt_map[owner_client]
                print(f"Cleaned up mappings for prompt {prompt_id}")


# --- Bridge Namespace for Node Communication ---
# --- 用于节点通信的桥接命名空间 ---
class BridgeNamespace(Namespace):
    def on_connect(self):
        print(f"[Bridge] Node connected: {request.sid}")

    def on_disconnect(self):
        print(f"[Bridge] Node disconnected: {request.sid}")
        # Clean up any pending requests associated with this node's sid
        # 清理与此节点 sid 关联的任何待处理请求
        requests_to_remove = []
        for key, req_info in pending_node_requests.items():
            if req_info.get('node_sid') == request.sid:
                requests_to_remove.append(key)
        for key in requests_to_remove:
             print(f"[Bridge] Cleaning up pending request {key} due to node disconnect.")
             del pending_node_requests[key]


    def on_request_data_from_node(self, data):
        """Received request from NodeBridge_Input via its WebSocket connection."""
        """通过其 WebSocket 连接从 NodeBridge_Input 收到请求。"""
        node_sid = request.sid # SID of the node's connection / 节点的连接 SID
        prompt_id = data.get('prompt_id')
        node_id = data.get('node_id')
        mode = data.get('mode')
        request_id = data.get('request_id') # Get the request_id sent by the node

        print(f"[Bridge] Received data request: prompt={prompt_id}, node={node_id}, mode={mode}, req_id={request_id}")

        if not all([prompt_id, node_id, mode, request_id]):
            print("[Bridge] Error: Incomplete data request received from node.")
            # Optionally send error back to node? / 可选地将错误发送回节点？
            return

        # Find the frontend client associated with this prompt_id
        # 查找与此 prompt_id 关联的前端客户端
        client_id = prompt_client_map.get(prompt_id)

        if not client_id:
            print(f"[Bridge] Error: Could not find frontend client for prompt_id {prompt_id}.")
            # Send error back to node / 将错误发送回节点
            emit('data_response_for_node', {
                 'request_id': request_id,
                 'error': 'Frontend client not found for this prompt.'
                 }, room=node_sid)
            return

        # Store the pending request details / 存储待处理请求详细信息
        pending_key = (prompt_id, node_id, request_id) # Use request_id in key for uniqueness
        pending_node_requests[pending_key] = {
            'request_id': request_id,
            'client_id': client_id,
            'mode': mode,
            'node_sid': node_sid,
            'timestamp': time.time()
        }
        print(f"[Bridge] Stored pending request {pending_key}")

        # Relay the request to the specific frontend client (using main namespace)
        # 将请求中继到特定的前端客户端（使用主命名空间）
        print(f"[Bridge] Relaying request to frontend client {client_id}")
        socketio.emit('request_data_for_frontend', {
            'prompt_id': prompt_id,
            'node_id': node_id,
            'mode': mode,
            'request_id': request_id # Include request_id so frontend can send it back
        }, room=client_id)

        # Notify frontend user / 通知前端用户
        socketio.emit('status_update', {'status': f"等待前端提供数据 Waiting for frontend data: {mode}"}, room=client_id)


# Register the namespace / 注册命名空间
socketio.on_namespace(BridgeNamespace('/bridge'))


# --- Main SocketIO Events (Frontend Communication) ---
# --- 主 SocketIO 事件（前端通信） ---
@socketio.on('connect')
def handle_connect():
    client_id = request.sid
    print(f"Frontend client connected: {client_id}")

@socketio.on('disconnect')
def handle_disconnect():
    client_id = request.sid
    print(f"Frontend client disconnected: {client_id}")
    # Clean up mappings if the client disconnects
    # 如果客户端断开连接，则清理映射
    prompt_info = client_prompt_map.pop(client_id, None)
    if prompt_info:
        prompt_id = prompt_info.get('prompt_id')
        if prompt_id and prompt_id in prompt_client_map:
            del prompt_client_map[prompt_id]
            print(f"Cleaned up mappings for disconnected client {client_id}, prompt {prompt_id}")
        # Also clean up any pending requests FOR this client
        # 同时清理此客户端的任何待处理请求
        reqs_to_remove = [key for key, req in pending_node_requests.items() if req['client_id'] == client_id]
        for key in reqs_to_remove:
            print(f"[Main] Cleaning up pending request {key} due to frontend client disconnect.")
            # TODO: Should we notify the waiting node that the client disconnected?
            # 我们是否应该通知等待中的节点客户端已断开连接？
            node_sid = pending_node_requests[key]['node_sid']
            request_id = pending_node_requests[key]['request_id']
            socketio.emit('data_response_for_node', {
                 'request_id': request_id,
                 'error': 'Frontend client disconnected before providing data.'
                 }, room=node_sid, namespace='/bridge') # Send error to node
            del pending_node_requests[key]


@socketio.on('provide_data_from_frontend')
def handle_provide_data(data):
    """Received data response from the frontend client."""
    """收到来自前端客户端的数据响应。"""
    client_id = request.sid
    prompt_id = data.get('prompt_id')
    node_id = data.get('node_id')
    mode = data.get('mode')
    request_id = data.get('request_id') # Get the request_id
    provided_data = data.get('data')

    print(f"[Main] Received data from frontend {client_id}: prompt={prompt_id}, node={node_id}, mode={mode}, req_id={request_id}")

    # Find the corresponding pending request using request_id
    # 使用 request_id 查找相应的待处理请求
    pending_key = None
    req_info = None
    for key, info in pending_node_requests.items():
        if info.get('request_id') == request_id:
            # Basic check: ensure the client sending data is the one we asked
            # 基本检查：确保存储的客户端 ID 与发送数据的客户端匹配
            if info.get('client_id') == client_id:
                 pending_key = key
                 req_info = info
                 break
            else:
                 print(f"[Main] Warning: Data received for request {request_id} from wrong client {client_id} (expected {info.get('client_id')}). Ignoring.")
                 return # Ignore data from wrong client

    if req_info and pending_key:
        node_sid = req_info.get('node_sid')
        if node_sid:
            print(f"[Main] Found pending request {pending_key}. Relaying data to node SID {node_sid}.")
            # Send the data back to the specific node via the bridge namespace
            # 通过桥接命名空间将数据发送回特定节点
            socketio.emit('data_response_for_node', {
                'request_id': request_id, # Include request_id for node confirmation
                'data': provided_data
            }, room=node_sid, namespace='/bridge')

            # Remove the pending request entry / 删除待处理请求条目
            del pending_node_requests[pending_key]
            print(f"[Main] Removed pending request {pending_key}")
        else:
            print(f"[Main] Error: Found pending request {pending_key} but missing node SID.")
            # Clean up the stale request / 清理过时的请求
            del pending_node_requests[pending_key]
    else:
        print(f"[Main] Warning: Received data for unknown or already fulfilled request (req_id: {request_id}).")


# --- Flask Routes ---
@app.route('/')
def index():
    # Pass comfyui port to template if needed by JS, though JS now uses fixed port
    # 如果 JS 需要，将 comfyui 端口传递给模板，尽管 JS 现在使用固定端口
    comfyui_port = COMFYUI_API_ADDRESS.split(':')[-1] if ':' in COMFYUI_API_ADDRESS else 8188
    return render_template('index.html', comfyui_api_port=comfyui_port)

@app.route('/api/workflows', methods=['GET'])
def get_workflows():
    if not os.path.isdir(COMFYUI_WORKFLOWS_PATH):
        return jsonify({"error": f"Workflow directory not found: {COMFYUI_WORKFLOWS_PATH}"}), 500
    try:
        # Include subdirectories (using os.walk) / 包括子目录（使用 os.walk）
        workflow_files = []
        for root, dirs, files in os.walk(COMFYUI_WORKFLOWS_PATH):
            for file in files:
                if file.endswith('.json'):
                    # Get path relative to COMFYUI_WORKFLOWS_PATH / 获取相对于 COMFYUI_WORKFLOWS_PATH 的路径
                    relative_path = os.path.relpath(os.path.join(root, file), COMFYUI_WORKFLOWS_PATH)
                    workflow_files.append(relative_path.replace("\\", "/")) # Use forward slashes
        print(f"Found workflows: {workflow_files}")
        return jsonify({"workflows": workflow_files})
    except Exception as e:
        print(f"Error listing workflows: {e}")
        return jsonify({"error": f"Error listing workflows: {e}"}), 500

# API endpoint to trigger workflow (replaces /api/render)
# 用于触发工作流的 API 端点（替换 /api/render）
@app.route('/api/trigger_prompt', methods=['POST'])
def trigger_prompt():
    client_id = request.sid # Get client SID from the initiating request
    if not client_id:
         # This might happen if called via simple HTTP POST, not JS fetch from socket context
         # 如果通过简单的 HTTP POST 调用，而不是从套接字上下文进行 JS fetch，则可能会发生这种情况
         # We NEED the client_id to route messages back.
         # 我们需要 client_id 来将消息路由回去。
         # The frontend JS should include its socket.id in the payload.
         # 前端 JS 应在其有效负载中包含其 socket.id。
         data = request.get_json()
         client_id = data.get('clientId') # Get client ID from payload
         if not client_id:
             print("Error: /api/trigger_prompt called without client ID.")
             return jsonify({"success": False, "message": "Missing client ID"}), 400
         print(f"/api/trigger_prompt using client ID from payload: {client_id}")
    else:
         print(f"/api/trigger_prompt using client ID from session: {client_id}")
         data = request.get_json()


    # Ensure this client isn't already running a prompt
    # 确保此客户端尚未运行提示
    if client_id in client_prompt_map:
         active_prompt = client_prompt_map[client_id]['prompt_id']
         print(f"Client {client_id} tried to start a new prompt while {active_prompt} is active.")
         return jsonify({"success": False, "message": "Please wait for the previous render to complete."}), 409 # Conflict


    workflow_key = data.get('workflow_key') # Expecting workflow key (relative path) now
    if not workflow_key:
        return jsonify({"success": False, "message": "Workflow key is required"}), 400

    # Construct full path carefully / 仔细构建完整路径
    workflow_path = os.path.abspath(os.path.join(COMFYUI_WORKFLOWS_PATH, workflow_key))

    # Security check: Ensure the path is still within the allowed directory
    # 安全检查：确保存储路径仍在允许的目录内
    if not workflow_path.startswith(os.path.abspath(COMFYUI_WORKFLOWS_PATH)):
         print(f"Error: Attempted access outside workflow directory: {workflow_key}")
         return jsonify({"success": False, "message": "Invalid workflow path"}), 400


    if not os.path.isfile(workflow_path):
        return jsonify({"success": False, "message": f"Workflow file not found: {workflow_key}"}), 404

    try:
        # 1. Load the base workflow / 1. 加载基础工作流
        with open(workflow_path, 'r', encoding='utf-8') as f:
            workflow_data = json.load(f)
        print(f"Loaded workflow: {workflow_key}")

        # 2. Generate Prompt ID and store mappings / 2. 生成提示 ID 并存储映射
        prompt_id = str(uuid.uuid4())
        client_prompt_map[client_id] = {'prompt_id': prompt_id, 'workflow_data': workflow_data}
        prompt_client_map[prompt_id] = client_id
        print(f"Assigned prompt ID {prompt_id} to client {client_id}")

        # 3. Start ComfyUI execution in a separate thread (no data injection here)
        # 3. 在单独的线程中启动 ComfyUI 执行（此处无数据注入）
        print(f"Starting ComfyUI listener thread for prompt {prompt_id}")
        thread = threading.Thread(target=queue_comfyui_prompt, args=(workflow_data, client_id, prompt_id))
        thread.daemon = True # Ensure thread exits when main app exits / 确保主应用程序退出时线程退出
        thread.start()

        # 4. Respond to frontend immediately / 4. 立即响应前端
        # Find the ID of the NodeBridge_Output node to potentially help the listener
        # 查找 NodeBridge_Output 节点的 ID 以可能帮助监听器
        output_node_id = None
        for n_id, n_info in workflow_data.items():
             if n_info.get("class_type") == "NodeBridge_Output":
                 output_node_id = n_id
                 break

        return jsonify({
            "success": True,
            "message": "Workflow triggered successfully.",
            "prompt_id": prompt_id,
            "client_id": client_id,
            "output_node_id": output_node_id # Send the expected output node ID
            })

    except FileNotFoundError:
        return jsonify({"success": False, "message": f"Workflow file not found: {workflow_path}"}), 404
    except json.JSONDecodeError:
         return jsonify({"success": False, "message": f"Invalid JSON in workflow file: {workflow_key}"}), 500
    except Exception as e:
        print(f"Error processing trigger request: {e}")
        import traceback
        traceback.print_exc()
        # Clean up mappings on error / 出错时清理映射
        if client_id in client_prompt_map: del client_prompt_map[client_id]
        if 'prompt_id' in locals() and prompt_id in prompt_client_map: del prompt_client_map[prompt_id]
        return jsonify({"success": False, "message": f"An unexpected error occurred: {e}"}), 500


if __name__ == '__main__':
    print("Starting Flask server with SocketIO (Real-time Bridge Mode)...")
    # Ensure gevent is used if patching was enabled / 如果启用了修补，请确保使用 gevent
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)