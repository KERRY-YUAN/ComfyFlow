import os
import uuid
import json
import urllib.request
import urllib.parse
import websocket # pip install websocket-client
import threading
import time
import logging
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import requests # pip install requests

# --- Configuration ---
# --- 配置 ---
# These might be better read from environment variables or a config file
# 从环境变量或配置文件读取可能更好
COMFYUI_HOST = os.environ.get("COMFYUI_HOST", "127.0.0.1")
COMFYUI_API_PORT = os.environ.get("COMFYUI_API_PORT", "8188") # Get from env var set by launcher
COMFYUI_ADDRESS = f"{COMFYUI_HOST}:{COMFYUI_API_PORT}"
CLIENT_ID = str(uuid.uuid4())
# Workflow config path (needs to be set correctly, maybe via env var from launcher)
# 工作流配置路径（需要正确设置，可能通过启动器设置环境变量）
WORKFLOW_CONFIG_PATH = os.environ.get("WORKFLOW_CONFIG_PATH", "workflows_config.json")
COMFYUI_WORKFLOW_DIR = os.environ.get("COMFYUI_WORKFLOW_DIR", ".") # Directory containing workflow JSON files / 包含工作流 JSON 文件的目录

# --- Constants / 常量 ---
UPLOAD_FOLDER = 'web_uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
NODE_BRIDGE_INPUT_TYPE = "NodeBridge_Input" # Make sure this matches your node's CLASS NAME / 确保这与你的节点的类名匹配
NODE_BRIDGE_OUTPUT_TYPE = "NodeBridge_Output" # Make sure this matches your node's CLASS NAME / 确保这与你的节点的类名匹配

# --- Flask App Setup ---
# --- Flask 应用设置 ---
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # Limit upload size to 16MB / 限制上传大小为 16MB

# --- Logging Setup ---
# --- 日志设置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- In-memory storage for staged data (Simple approach) ---
# --- 用于暂存数据的内存存储 (简单方法) ---
# For production, consider using Flask sessions or a more persistent store
# 对于生产环境，考虑使用 Flask 会话或更持久的存储
staged_data_store = {}

# --- Helper Functions ---
# --- 辅助函数 ---
def allowed_file(filename):
    """Checks if the file extension is allowed."""
    """检查文件扩展名是否允许。"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_workflow_options():
    """Loads workflow display names and keys from the config file."""
    """从配置文件加载工作流显示名称和键。"""
    options = {}
    try:
        if os.path.exists(WORKFLOW_CONFIG_PATH):
            with open(WORKFLOW_CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # Assuming format: {"key1": {"display_name": "Name 1", "file": "wf1.json"}, ...}
                # 假设格式：{"key1": {"display_name": "Name 1", "file": "wf1.json"}, ...}
                for key, data in config.items():
                    if isinstance(data, dict) and "display_name" in data:
                        options[key] = data["display_name"]
        else:
             logging.warning(f"Workflow config file not found: {WORKFLOW_CONFIG_PATH}")
    except (json.JSONDecodeError, IOError, OSError, KeyError) as e:
        logging.error(f"Error loading workflow config '{WORKFLOW_CONFIG_PATH}': {e}")
    return options

def get_workflow_filepath(key):
    """Gets the JSON filepath for a given workflow key."""
    """获取给定工作流键的 JSON 文件路径。"""
    try:
        if os.path.exists(WORKFLOW_CONFIG_PATH):
            with open(WORKFLOW_CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
                if key in config and isinstance(config[key], dict) and "file" in config[key]:
                    # Construct path relative to COMFYUI_WORKFLOW_DIR
                    # 构建相对于 COMFYUI_WORKFLOW_DIR 的路径
                    filepath = os.path.join(COMFYUI_WORKFLOW_DIR, config[key]["file"])
                    if os.path.isfile(filepath):
                        return filepath
                    else:
                        logging.error(f"Workflow file not found for key '{key}': {filepath}")
                else:
                    logging.error(f"Invalid or missing 'file' entry for key '{key}' in {WORKFLOW_CONFIG_PATH}")
        else:
            logging.warning(f"Workflow config file not found: {WORKFLOW_CONFIG_PATH}")
    except Exception as e:
         logging.error(f"Error getting workflow filepath for key '{key}': {e}")
    return None


# --- ComfyUI API Interaction ---
# --- ComfyUI API 交互 ---
def get_comfyui_graph(workflow_filepath):
    """Loads workflow graph from a JSON file."""
    """从 JSON 文件加载工作流图。"""
    try:
        with open(workflow_filepath, 'r', encoding='utf-8') as f:
            # Load the workflow using ComfyUI's /graph endpoint simulation or just load JSON
            # 使用 ComfyUI 的 /graph 端点模拟加载工作流或仅加载 JSON
            # For simplicity, we just load the JSON prompt structure directly.
            # 为简单起见，我们直接加载 JSON 提示结构。
            # A more robust approach might load the full graph if needed.
            # 如果需要，更健壮的方法可能会加载完整的图。
            workflow_data = json.load(f)
            # Assuming the file directly contains the prompt format
            # 假设文件直接包含提示格式
            # If it contains the graph format, you need to extract the prompt part
            # 如果它包含图形格式，则需要提取提示部分
            # e.g., return workflow_data.get('prompt') if 'prompt' in workflow_data else workflow_data
            return workflow_data # Return the whole structure for now / 现在返回整个结构
    except FileNotFoundError:
        logging.error(f"Workflow file not found: {workflow_filepath}")
    except json.JSONDecodeError:
        logging.error(f"Invalid JSON in workflow file: {workflow_filepath}")
    except Exception as e:
        logging.error(f"Error loading workflow file {workflow_filepath}: {e}")
    return None

def find_node_id_by_type(graph_data, node_type_name):
    """Finds the first node ID matching the given custom node type name in the graph structure."""
    """在图结构中查找第一个匹配给定自定义节点类型名称的节点 ID。"""
    # This needs the *graph* structure, not just the prompt structure
    # 这需要*图*结构，而不仅仅是提示结构
    # If graph_data is the prompt structure, we need to adapt or get the full graph first
    # 如果 graph_data 是提示结构，我们需要先进行调整或获取完整的图
    # Let's assume graph_data might be the full graph structure for now
    # 让我们暂时假设 graph_data 可能是完整的图结构
    nodes = None
    if isinstance(graph_data, dict):
        if 'nodes' in graph_data: # Check if it looks like a graph API response
            nodes = graph_data['nodes']
        elif all(isinstance(v, dict) and 'class_type' in v for v in graph_data.values()): # Check if it looks like a prompt API structure
             # Can't reliably get node type from prompt structure easily without full graph
             logging.warning("Cannot reliably find node by type from prompt structure alone. Need full graph.")
             return None # Or try a best guess if absolutely necessary / 或者在绝对必要时尝试最佳猜测

    if not nodes:
         logging.error("Could not find 'nodes' array in the provided graph data.")
         return None

    for node in nodes:
        if node.get('type') == node_type_name:
            return str(node.get('id')) # Node IDs are usually strings / 节点 ID 通常是字符串
    logging.warning(f"Node type '{node_type_name}' not found in the graph.")
    return None


def upload_image_to_comfyui(image_path, image_type="input"):
    """Uploads an image file to ComfyUI's /upload/image endpoint."""
    """将图像文件上传到 ComfyUI 的 /upload/image 端点。"""
    try:
        filename = os.path.basename(image_path)
        url = f"http://{COMFYUI_ADDRESS}/upload/image"
        with open(image_path, 'rb') as f:
            files = {'image': (filename, f)} # Let requests guess mime type / 让 requests 猜测 mime 类型
            data = {'overwrite': 'true', 'type': image_type}
            response = requests.post(url, files=files, data=data, timeout=60) # Add timeout / 添加超时
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx) / 对错误响应（4xx 或 5xx）引发 HTTPError
            result = response.json()
            logging.info(f"Image '{filename}' uploaded successfully: {result}")
            return result
    except requests.exceptions.RequestException as e:
        logging.error(f"Error uploading image {filename} to ComfyUI ({url}): {e}")
    except Exception as e:
        logging.error(f"Unexpected error uploading image {filename} to ComfyUI: {e}")
    return None


def queue_prompt(prompt_workflow, client_id):
    """Sends the prompt workflow to ComfyUI to be queued."""
    """将提示工作流发送到 ComfyUI 进行排队。"""
    url = f"http://{COMFYUI_ADDRESS}/prompt"
    try:
        payload = {"prompt": prompt_workflow, "client_id": client_id}
        response = requests.post(url, json=payload, timeout=30) # Add timeout / 添加超时
        response.raise_for_status()
        result = response.json()
        logging.info(f"Prompt queued successfully: {result.get('prompt_id')}")
        return result
    except requests.exceptions.RequestException as e:
        logging.error(f"Error queuing prompt to {url}: {e}")
        if e.response is not None:
            logging.error(f"Response status: {e.response.status_code}, Body: {e.response.text}")
    except Exception as e:
        logging.error(f"Unexpected error queuing prompt: {e}")
    return None


# --- WebSocket Listener (Placeholder - Frontend handles direct connection now) ---
# --- WebSocket 监听器 (占位符 - 前端现在处理直接连接) ---
# The backend doesn't strictly need its own WS connection if the frontend connects directly
# 如果前端直接连接，后端并不严格需要自己的 WS 连接
# However, it could be useful for backend-initiated actions or monitoring
# 但是，它对于后端启动的操作或监视可能很有用
# Keep the basic structure for potential future use or remove if unused
# 保留基本结构以备将来使用，如果未使用则删除

# prompt_results = {} # Remove if backend WS listener is removed / 如果后端 WS 监听器被移除则删除

# def comfyui_ws_listener(): ...
# def on_ws_message(ws, message): ...
# def on_ws_error(ws, error): ...
# def on_ws_close(ws, close_status_code, close_msg): ...
# def on_ws_open(ws): ...
# ws_thread = threading.Thread(target=comfyui_ws_listener, daemon=True)
# ws_thread.start()


# --- Flask Routes ---
# --- Flask 路由 ---

@app.route('/')
def index():
    """Serves the main HTML page."""
    """提供主 HTML 页面。"""
    # Load workflow options for the dropdown
    # 加载下拉菜单的工作流选项
    workflow_options = load_workflow_options()
    return render_template('index.html',
                           workflow_options=workflow_options,
                           comfyui_api_port=COMFYUI_API_PORT) # Pass port to template / 将端口传递给模板

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    # Serve files uploaded by the browser for preview
    # 提供由浏览器上传的文件以供预览
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- NEW API Route for Staging Data ---
# --- 用于暂存数据的新 API 路由 ---
@app.route('/api/stage_data', methods=['POST'])
def stage_data():
    """Receives and stores individual input data pieces."""
    """接收并存储单个输入数据片段。"""
    try:
        key = request.form.get('key')
        data_type = request.form.get('type')
        value = None

        if not key or not data_type:
            return jsonify({"success": False, "message": "Missing 'key' or 'type'."}), 400

        if data_type == 'Image':
            if 'image_file' not in request.files:
                return jsonify({"success": False, "message": "No 'image_file' part in request."}), 400
            file = request.files['image_file']
            if file.filename == '':
                 # Handle case where input is cleared
                 # 处理输入被清除的情况
                 if key in staged_data_store: del staged_data_store[key]
                 logging.info(f"Staged data cleared for key: {key}")
                 return jsonify({"success": True, "message": "Image data cleared."})
            if file and allowed_file(file.filename):
                # Save the uploaded file temporarily for potential ComfyUI upload later
                # 临时保存上传的文件，以便稍后可能上传到 ComfyUI
                # Use a unique name to avoid collisions
                # 使用唯一名称以避免冲突
                filename = secure_filename(f"{key}_{uuid.uuid4()}_{file.filename}")
                if not os.path.exists(app.config['UPLOAD_FOLDER']):
                     os.makedirs(app.config['UPLOAD_FOLDER'])
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                # Store the *filepath* in the staging area
                # 将 *文件路径* 存储在暂存区
                value = {"type": "image_file", "filepath": filepath, "original_filename": file.filename}
                logging.info(f"Image staged for key '{key}': {filepath}")
            else:
                return jsonify({"success": False, "message": "Invalid file type or no file selected."}), 400
        elif data_type == 'Text':
            value = request.form.get('value', '')
        elif data_type == 'Float':
            try:
                value = float(request.form.get('value', 0.0))
            except ValueError:
                return jsonify({"success": False, "message": "Invalid float value."}), 400
        elif data_type == 'Int':
            try:
                value = int(request.form.get('value', 0))
            except ValueError:
                 return jsonify({"success": False, "message": "Invalid integer value."}), 400
        else:
            return jsonify({"success": False, "message": f"Unsupported data type: {data_type}"}), 400

        # Store the processed value
        # 存储处理后的值
        staged_data_store[key] = value
        # logging.debug(f"Staged data updated: {staged_data_store}") # Log for debugging / 调试日志
        return jsonify({"success": True, "message": f"Data for '{key}' staged."})

    except Exception as e:
        logging.error(f"Error in /api/stage_data: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Internal server error during staging."}), 500


# --- NEW API Route for Triggering Prompt ---
# --- 用于触发提示的新 API 路由 ---
@app.route('/api/trigger_prompt', methods=['POST'])
def trigger_prompt():
    """Loads workflow, injects staged data, finds output node, queues prompt."""
    """加载工作流，注入暂存数据，查找输出节点，排队提示。"""
    output_node_id = None # Initialize / 初始化
    try:
        data = request.get_json()
        workflow_key = data.get('workflow_key')
        if not workflow_key:
            return jsonify({"success": False, "message": "Missing 'workflow_key' in request."}), 400

        # 1. Get Workflow Filepath / 获取工作流文件路径
        workflow_filepath = get_workflow_filepath(workflow_key)
        if not workflow_filepath:
            return jsonify({"success": False, "message": f"Workflow not found or configured for key: {workflow_key}"}), 404

        # 2. Load Workflow Structure (assuming it contains the prompt format)
        #    加载工作流结构（假设它包含提示格式）
        #    For finding node IDs by type, we might ideally need the full graph API response,
        #    but we'll try with the loaded JSON first.
        #    为了按类型查找节点 ID，我们理想情况下可能需要完整的图 API 响应，
        #    但我们将首先尝试使用加载的 JSON。
        loaded_workflow_data = get_comfyui_graph(workflow_filepath)
        if not loaded_workflow_data:
             return jsonify({"success": False, "message": "Failed to load workflow file."}), 500

        # Assume the loaded data *is* the prompt structure for modification
        # 假设加载的数据 *是* 用于修改的提示结构
        prompt_workflow = loaded_workflow_data # Adapt if your JSON is the graph format / 如果你的 JSON 是图格式，则进行调整

        # We need the graph structure to find nodes by type
        # 我们需要图结构来按类型查找节点
        # Let's fetch the current graph from ComfyUI to reliably get node IDs
        # 让我们从 ComfyUI 获取当前图以可靠地获取节点 ID
        # Note: This assumes the *currently loaded* graph in ComfyUI matches the structure
        # of the selected workflow file, which might not always be true if the user
        # changed workflows in ComfyUI without restarting the backend.
        # 注意：这假设 ComfyUI 中*当前加载*的图与所选工作流文件的结构匹配，
        # 如果用户在 ComfyUI 中更改了工作流而没有重新启动后端，这可能并不总是正确的。
        # A better approach loads the workflow file *into* ComfyUI first if needed.
        # 如果需要，更好的方法是首先将工作流文件*加载到*ComfyUI 中。
        # For simplicity, let's *assume* the loaded JSON structure *is* the prompt:
        # 为简单起见，让我们*假设*加载的 JSON 结构*是*提示：

        # --- Find Node IDs ---
        # This part is tricky without the full graph context associated *with this specific workflow file*.
        # 如果没有与*此特定工作流文件*关联的完整图上下文，这部分会很棘手。
        # We will *guess* the node IDs based on the common practice that node IDs in the
        # prompt structure often match the graph structure. This is NOT guaranteed.
        # 我们将根据常见实践*猜测*节点 ID，即提示结构中的节点 ID 通常与图结构匹配。这*不能*保证。
        # A more robust solution involves loading the workflow via API or parsing the graph structure.
        # 更强大的解决方案涉及通过 API 加载工作流或解析图结构。

        input_node_id = None
        output_node_id = None

        # Iterate through the prompt structure to find likely IDs
        # 遍历提示结构以查找可能的 ID
        potential_input_nodes = []
        potential_output_nodes = []
        if isinstance(prompt_workflow, dict):
             for node_id, node_data in prompt_workflow.items():
                  if isinstance(node_data, dict) and node_data.get("class_type") == NODE_BRIDGE_INPUT_TYPE:
                      potential_input_nodes.append(node_id)
                  if isinstance(node_data, dict) and node_data.get("class_type") == NODE_BRIDGE_OUTPUT_TYPE:
                       potential_output_nodes.append(node_id)

        if not potential_input_nodes:
             return jsonify({"success": False, "message": f"Node type '{NODE_BRIDGE_INPUT_TYPE}' not found in workflow '{workflow_key}'."}), 404
        if not potential_output_nodes:
            return jsonify({"success": False, "message": f"Node type '{NODE_BRIDGE_OUTPUT_TYPE}' not found in workflow '{workflow_key}'."}), 404

        input_node_id = potential_input_nodes[0] # Use the first one found / 使用找到的第一个
        output_node_id = potential_output_nodes[0] # Use the first one found / 使用找到的第一个
        logging.info(f"Found Input Node ID: {input_node_id}, Output Node ID: {output_node_id} (by type guessing)")


        # 3. Inject Staged Data into the Prompt Workflow / 将暂存数据注入提示工作流
        if input_node_id not in prompt_workflow:
             return jsonify({"success": False, "message": f"Input node ID '{input_node_id}' not found in prompt structure."}), 500

        inputs_to_update = prompt_workflow[input_node_id]['inputs']

        # Map staged keys to node input names / 将暂存键映射到节点输入名称
        key_to_input_map = {
            'current_line_draft': 'Image',
            'current_reference': 'Reference',
            'current_prompt': 'Text',
            'current_strength': 'CN',
            'current_count': 'Count',
        }

        for stage_key, node_input_name in key_to_input_map.items():
            if stage_key in staged_data_store:
                staged_value = staged_data_store[stage_key]

                if isinstance(staged_value, dict) and staged_value.get("type") == "image_file":
                    # Upload the staged image file to ComfyUI
                    # 将暂存的图像文件上传到 ComfyUI
                    filepath = staged_value.get("filepath")
                    if filepath and os.path.exists(filepath):
                        logging.info(f"Uploading staged image '{filepath}' for input '{node_input_name}'...")
                        upload_info = upload_image_to_comfyui(filepath)
                        if upload_info and 'name' in upload_info:
                            inputs_to_update[node_input_name] = upload_info['name'] # Use the filename returned by ComfyUI / 使用 ComfyUI 返回的文件名
                            logging.info(f"Injecting image '{upload_info['name']}' into input '{node_input_name}'.")
                            # Optionally delete the temp file after upload / 上传后可选择删除临时文件
                            # try: os.remove(filepath)
                            # except OSError as e: logging.warning(f"Could not remove temp upload {filepath}: {e}")
                        else:
                            logging.warning(f"Failed to upload staged image for key '{stage_key}'. Skipping input '{node_input_name}'.")
                            # Decide how to handle upload failure - skip, use default, raise error?
                            # 决定如何处理上传失败 - 跳过、使用默认值、引发错误？
                            # Setting to None might cause issues if the node requires an image
                            # 如果节点需要图像，设置为空可能会导致问题
                            if node_input_name in inputs_to_update: del inputs_to_update[node_input_name]

                    else:
                        logging.warning(f"Staged image file path not found or invalid for key '{stage_key}'. Skipping input '{node_input_name}'.")
                        if node_input_name in inputs_to_update: del inputs_to_update[node_input_name]
                else:
                    # Inject non-image values directly
                    # 直接注入非图像值
                    inputs_to_update[node_input_name] = staged_value
                    logging.info(f"Injecting value '{staged_value}' into input '{node_input_name}'.")
            else:
                 # Handle missing staged data - maybe set to default or remove from inputs?
                 # 处理丢失的暂存数据 - 可能设置为默认值或从输入中移除？
                 logging.warning(f"No staged data found for key '{stage_key}'. Input '{node_input_name}' might be missing.")
                 # If the input is mandatory in ComfyUI, this might cause an error later
                 # 如果输入在 ComfyUI 中是必需的，这稍后可能会导致错误
                 if node_input_name in inputs_to_update: del inputs_to_update[node_input_name] # Remove if not staged / 如果未暂存则移除

        logging.debug(f"Modified Prompt Inputs for node {input_node_id}: {json.dumps(inputs_to_update, indent=2)}")

        # 4. Queue the Prompt / 排队提示
        result = queue_prompt(prompt_workflow, CLIENT_ID)

        if result and 'prompt_id' in result:
            prompt_id = result['prompt_id']
            # Return success and the *output node ID* the frontend should watch
            # 返回成功和前端应监视的 *输出节点 ID*
            return jsonify({
                "success": True,
                "prompt_id": prompt_id,
                "message": "Workflow triggered successfully.",
                "output_node_id": output_node_id # Crucial for the frontend / 对前端至关重要
            })
        else:
            error_details = result.get('error', 'Unknown error') if result else 'Queue request failed'
            node_errors = result.get('node_errors', {}) if result else {}
            return jsonify({
                "success": False,
                "message": "Failed to queue prompt in ComfyUI.",
                "details": error_details,
                "node_errors": node_errors
            }), 500

    except Exception as e:
        logging.error(f"Error in /api/trigger_prompt: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Internal server error during trigger."}), 500


# --- Main Execution ---
# --- 主要执行 ---
if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
        logging.info(f"Created upload folder: {UPLOAD_FOLDER}")

    # Ensure ComfyUI workflow dir is set and exists
    # 确保 ComfyUI 工作流目录已设置且存在
    if not COMFYUI_WORKFLOW_DIR or not os.path.isdir(COMFYUI_WORKFLOW_DIR):
         logging.warning(f"COMFYUI_WORKFLOW_DIR ('{COMFYUI_WORKFLOW_DIR}') not set or not a valid directory. Workflow loading may fail.")

    logging.info(f"Flask app running. Access at http://127.0.0.1:5000")
    logging.info(f"Expecting ComfyUI at http://{COMFYUI_ADDRESS}")
    logging.info(f"Using workflow config: {WORKFLOW_CONFIG_PATH}")
    logging.info(f"Expecting workflow JSONs in: {COMFYUI_WORKFLOW_DIR}")

    # Use host='0.0.0.0' to be accessible from other devices on the network
    # 使用 host='0.0.0.0' 以便网络上的其他设备可以访问
    # Set debug=True for development (enables auto-reload and debugger)
    # 设置 debug=True 用于开发（启用自动重新加载和调试器）
    # Use use_reloader=False if you want to disable the auto-reloader specifically
    # 如果你想特别禁用自动重新加载器，请使用 use_reloader=False
    app.run(host='0.0.0.0', port=5000, debug=True)