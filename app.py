import os
import uuid
import json
import urllib.request
import urllib.parse
import threading
import time
import logging
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import requests # pip install requests

# --- Configuration ---
COMFYUI_HOST = os.environ.get("COMFYUI_HOST", "127.0.0.1")
COMFYUI_API_PORT = os.environ.get("COMFYUI_API_PORT", "8188") # Get from env var set by launcher
COMFYUI_ADDRESS = f"{COMFYUI_HOST}:{COMFYUI_API_PORT}"
CLIENT_ID = str(uuid.uuid4())

# --- Constants ---
UPLOAD_FOLDER = 'web_uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
NODE_BRIDGE_INPUT_TYPE = "NodeBridge_Input" # Class name of your input node / 输入节点的类名
NODE_BRIDGE_OUTPUT_TYPE = "NodeBridge_Output" # Class name of your output node / 输出节点的类名

# --- Flask App Setup ---
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # Limit upload size to 16MB

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app.logger.setLevel(logging.INFO) # Ensure Flask logger uses the same level

# --- In-memory storage for staged data ---
staged_data_store = {}

# --- Helper Functions ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- ComfyUI API Interaction ---

def get_current_comfyui_graph_and_prompt():
    """Fetches the current graph structure and prompt structure from ComfyUI."""
    """从 ComfyUI 获取当前的图结构和提示结构。"""
    url = f"http://{COMFYUI_ADDRESS}/graph"
    app.logger.info(f"Attempting to fetch graph from {url}")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        graph_data = response.json()
        app.logger.info("Successfully fetched graph data.")
        # Extract prompt structure (often nested, check the actual response structure)
        # 提取提示结构（通常是嵌套的，检查实际的响应结构）
        # Common structure: graph_data contains 'graph' which contains 'nodes', and 'prompt' structure is separate
        # 常见结构：graph_data 包含 'graph'，其中包含 'nodes'，而 'prompt' 结构是分开的
        # Let's assume graph_data *is* the graph API response structure
        # 假设 graph_data *是* 图 API 响应结构
        if 'prompt' in graph_data and 'graph' in graph_data and 'nodes' in graph_data['graph']:
             prompt_data = graph_data['prompt']
             graph_nodes = graph_data['graph']['nodes']
             app.logger.info("Found 'prompt' and 'graph.nodes' in response.")
             return graph_nodes, prompt_data # Return nodes array and prompt dict / 返回节点数组和提示字典
        else:
            # Fallback: Check if the root IS the prompt structure (less likely for /graph)
            # 回退：检查根是否是提示结构（对于 /graph 不太可能）
            if isinstance(graph_data, dict) and all(isinstance(v, dict) and 'class_type' in v for k,v in graph_data.items() if not k.startswith('_')):
                 app.logger.warning("/graph endpoint seems to have returned prompt structure directly? Cannot get graph nodes.")
                 # We cannot reliably find nodes by type from only the prompt structure
                 # 我们无法仅从提示结构可靠地按类型查找节点
                 return None, graph_data # Return None for nodes, but the assumed prompt / 为节点返回 None，但返回假定的提示
            else:
                 app.logger.error("Could not find expected 'prompt' or 'graph.nodes' structure in /graph response.")
                 raise ValueError("Invalid graph response structure.")

    except requests.exceptions.Timeout:
        app.logger.error(f"Timeout when connecting to ComfyUI ({url}).")
    except requests.exceptions.ConnectionError:
        app.logger.error(f"Connection refused by ComfyUI ({url}). Is it running?")
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Failed to get graph from ComfyUI ({url}): {e}")
    except (ValueError, KeyError, json.JSONDecodeError) as e:
         app.logger.error(f"Failed to parse graph response from ComfyUI: {e}")
    except Exception as e:
         app.logger.error(f"Unexpected error getting graph from ComfyUI: {e}", exc_info=True)
    return None, None # Indicate failure / 表示失败

def find_node_id_by_type(graph_nodes, node_type_name):
    """Finds the first node ID matching the given custom node type name in the graph nodes list."""
    """在图节点列表中查找第一个匹配给定自定义节点类型名称的节点 ID。"""
    if not graph_nodes:
        app.logger.warning(f"Cannot find node ID for '{node_type_name}': graph_nodes list is empty or None.")
        return None
    for node in graph_nodes:
        # Node structure from /graph is usually: {'id': N, 'type': 'NodeType', ...}
        # 来自 /graph 的节点结构通常是：{'id': N, 'type': 'NodeType', ...}
        if node.get('type') == node_type_name:
            node_id_str = str(node.get('id'))
            app.logger.info(f"Found node ID {node_id_str} for type '{node_type_name}'.")
            return node_id_str
    app.logger.warning(f"Node type '{node_type_name}' not found in the provided graph nodes.")
    return None


def upload_image_to_comfyui(image_path, image_type="input"):
    """Uploads an image file to ComfyUI's /upload/image endpoint."""
    """将图像文件上传到 ComfyUI 的 /upload/image 端点。"""
    filename = os.path.basename(image_path)
    url = f"http://{COMFYUI_ADDRESS}/upload/image"
    app.logger.info(f"Uploading '{filename}' to {url}...")
    try:
        with open(image_path, 'rb') as f:
            files = {'image': (filename, f)}
            data = {'overwrite': 'true', 'type': image_type}
            response = requests.post(url, files=files, data=data, timeout=60)
            response.raise_for_status()
            result = response.json()
            app.logger.info(f"Image '{filename}' uploaded successfully: {result}")
            return result
    except requests.exceptions.Timeout:
        app.logger.error(f"Timeout uploading image {filename} to ComfyUI ({url}).")
    except requests.exceptions.ConnectionError:
        app.logger.error(f"Connection refused by ComfyUI ({url}) during image upload.")
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error uploading image {filename} to ComfyUI ({url}): {e}")
        if e.response is not None:
            app.logger.error(f"Response status: {e.response.status_code}, Body: {e.response.text}")
    except Exception as e:
        app.logger.error(f"Unexpected error uploading image {filename} to ComfyUI: {e}", exc_info=True)
    return None


def queue_prompt(prompt_workflow, client_id):
    """Sends the prompt workflow to ComfyUI to be queued."""
    """将提示工作流发送到 ComfyUI 进行排队。"""
    url = f"http://{COMFYUI_ADDRESS}/prompt"
    app.logger.info(f"Queueing prompt to {url}...")
    try:
        payload = {"prompt": prompt_workflow, "client_id": client_id}
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        app.logger.info(f"Prompt queued successfully: ID {result.get('prompt_id')}")
        # app.logger.debug(f"Queued prompt payload: {json.dumps(prompt_workflow, indent=2)}") # DEBUG
        return result
    except requests.exceptions.Timeout:
        app.logger.error(f"Timeout queuing prompt to ComfyUI ({url}).")
    except requests.exceptions.ConnectionError:
        app.logger.error(f"Connection refused by ComfyUI ({url}) during prompt queue.")
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error queuing prompt to {url}: {e}")
        if e.response is not None:
            app.logger.error(f"Response status: {e.response.status_code}, Body: {e.response.text}")
    except Exception as e:
        app.logger.error(f"Unexpected error queuing prompt: {e}", exc_info=True)
    return None


# --- Flask Routes ---

@app.route('/')
def index():
    """Serves the main HTML page."""
    """提供主 HTML 页面。"""
    app.logger.info("Serving index.html")
    # Removed workflow_options loading / 移除 workflow_options 加载
    return render_template('index.html',
                           comfyui_api_port=COMFYUI_API_PORT) # Pass port for WS connection / 传递端口用于 WS 连接

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    # Serve files uploaded by the browser for preview / 提供由浏览器上传的文件以供预览
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- API Route for Connection Status Check (Req 1) ---
@app.route('/api/ping_comfyui')
def ping_comfyui():
    """Checks if the ComfyUI API is reachable."""
    """检查 ComfyUI API 是否可达。"""
    url = f"http://{COMFYUI_ADDRESS}/queue" # Use a lightweight endpoint / 使用轻量级端点
    try:
        # Short timeout as this should be fast if running / 超时时间短，因为如果正在运行应该很快
        response = requests.get(url, timeout=3)
        response.raise_for_status()
        # Could optionally check response content here if needed / 如果需要，可以在此处选择性地检查响应内容
        # is_connected = response.status_code == 200 # Basic check / 基本检查
        is_connected = True # Assume success if no exception / 假设没有异常即成功
        message = "ComfyUI is reachable."
    except requests.exceptions.Timeout:
        is_connected = False
        message = "ComfyUI connection timed out."
        app.logger.warning(f"Ping ComfyUI failed: Timeout ({url})")
    except requests.exceptions.ConnectionError:
        is_connected = False
        message = "ComfyUI connection refused."
        app.logger.warning(f"Ping ComfyUI failed: Connection refused ({url})")
    except requests.exceptions.RequestException as e:
        is_connected = False
        message = f"ComfyUI API request failed: {e}"
        app.logger.warning(f"Ping ComfyUI failed: {e}")
    except Exception as e:
        is_connected = False
        message = f"Internal error pinging ComfyUI: {e}"
        app.logger.error(f"Unexpected error pinging ComfyUI: {e}", exc_info=True)

    status_code = 200 if is_connected else 503 # 503 Service Unavailable / 503 服务不可用
    return jsonify({"success": is_connected, "message": message}), status_code


# --- API Route for Staging Data ---
@app.route('/api/stage_data', methods=['POST'])
def stage_data():
    """Receives and stores individual input data pieces."""
    """接收并存储单个输入数据片段。"""
    try:
        key = request.form.get('key')
        data_type = request.form.get('type')
        value = None

        if not key or not data_type:
            app.logger.warning("Stage request missing 'key' or 'type'.")
            return jsonify({"success": False, "message": "Missing 'key' or 'type'."}), 400

        app.logger.debug(f"Received stage request: key='{key}', type='{data_type}'")

        if data_type == 'Image':
            if 'image_file' not in request.files:
                 # This can happen if the file input is cleared
                 # 如果文件输入被清除，可能会发生这种情况
                 if key in staged_data_store:
                     # Clean up old file if it exists
                     # 如果存在旧文件，则清理
                     old_data = staged_data_store.get(key)
                     if isinstance(old_data, dict) and old_data.get("type") == "image_file":
                          filepath = old_data.get("filepath")
                          if filepath and os.path.exists(filepath):
                              try:
                                  os.remove(filepath)
                                  app.logger.info(f"Removed previous staged file: {filepath}")
                              except OSError as e:
                                   app.logger.warning(f"Could not remove previous staged file {filepath}: {e}")
                     del staged_data_store[key]
                     app.logger.info(f"Staged data cleared for key: {key}")
                 return jsonify({"success": True, "message": "Image data cleared."})

            file = request.files['image_file']
            if file and allowed_file(file.filename):
                # Save the uploaded file temporarily
                # 临时保存上传的文件
                filename = secure_filename(f"{key}_{uuid.uuid4()}_{file.filename}")
                if not os.path.exists(app.config['UPLOAD_FOLDER']):
                     os.makedirs(app.config['UPLOAD_FOLDER'])
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                # Store the filepath
                # 存储文件路径
                value = {"type": "image_file", "filepath": filepath, "original_filename": file.filename}
                app.logger.info(f"Image staged for key '{key}': {filepath}")
                # Clean up previous file for this key if it exists
                # 如果此键存在先前的文件，则清理
                if key in staged_data_store:
                     old_data = staged_data_store.get(key)
                     if isinstance(old_data, dict) and old_data.get("type") == "image_file":
                          old_filepath = old_data.get("filepath")
                          if old_filepath and os.path.exists(old_filepath) and old_filepath != filepath:
                              try:
                                  os.remove(old_filepath)
                                  app.logger.info(f"Removed previous staged file: {old_filepath}")
                              except OSError as e:
                                   app.logger.warning(f"Could not remove previous staged file {old_filepath}: {e}")
            else:
                app.logger.warning(f"Invalid file type or no file selected for key '{key}'.")
                return jsonify({"success": False, "message": "Invalid file type or no file selected."}), 400
        elif data_type == 'Text':
            value = request.form.get('value', '')
        elif data_type == 'Float':
            try: value = float(request.form.get('value', 0.0))
            except ValueError: return jsonify({"success": False, "message": "Invalid float value."}), 400
        elif data_type == 'Int':
            try: value = int(request.form.get('value', 0))
            except ValueError: return jsonify({"success": False, "message": "Invalid integer value."}), 400
        else:
            return jsonify({"success": False, "message": f"Unsupported data type: {data_type}"}), 400

        staged_data_store[key] = value
        app.logger.debug(f"Staged data store updated: {staged_data_store}")
        return jsonify({"success": True, "message": f"Data for '{key}' staged."})

    except Exception as e:
        app.logger.error(f"Error in /api/stage_data: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Internal server error during staging."}), 500

# --- API Route for Triggering Prompt (Modified for Live Workflow) ---
@app.route('/api/trigger_prompt', methods=['POST'])
def trigger_prompt():
    """Gets live workflow, injects staged data, finds output node, queues prompt."""
    """获取实时工作流，注入暂存数据，查找输出节点，排队提示。"""
    input_node_id = None
    output_node_id = None

    try:
        # 1. Get Current ComfyUI Graph and Prompt Structure
        #    获取当前的 ComfyUI 图和提示结构
        graph_nodes, prompt_workflow = get_current_comfyui_graph_and_prompt()
        if graph_nodes is None or prompt_workflow is None:
            app.logger.error("Failed to get graph/prompt from ComfyUI.")
            return jsonify({"success": False, "message": "Failed to get current workflow from ComfyUI. Is it running and reachable?"}), 503

        # 2. Find NodeBridge Input and Output Node IDs from the Graph Nodes
        #    从图节点中查找 NodeBridge 输入和输出节点 ID
        input_node_id = find_node_id_by_type(graph_nodes, NODE_BRIDGE_INPUT_TYPE)
        output_node_id = find_node_id_by_type(graph_nodes, NODE_BRIDGE_OUTPUT_TYPE)

        if not input_node_id:
            app.logger.error(f"Could not find '{NODE_BRIDGE_INPUT_TYPE}' node in the current ComfyUI workflow graph.")
            return jsonify({"success": False, "message": f"Required node '{NODE_BRIDGE_INPUT_TYPE}' not found in the active ComfyUI workflow."}), 404
        if not output_node_id:
            # Output node might be optional depending on workflow design
            # 输出节点可能根据工作流设计是可选的
            app.logger.warning(f"Node type '{NODE_BRIDGE_OUTPUT_TYPE}' not found in the current ComfyUI workflow graph. Result fetching might rely on last node.")
            # Proceed without output_node_id, frontend needs fallback logic
            # 在没有 output_node_id 的情况下继续，前端需要回退逻辑

        # 3. Inject Staged Data into the *Prompt* Workflow Structure
        #    将暂存数据注入 *提示* 工作流结构
        if input_node_id not in prompt_workflow:
            # This can happen if the graph structure ID doesn't match the prompt structure ID
            # 如果图结构 ID 与提示结构 ID 不匹配，可能会发生这种情况
            app.logger.error(f"Input node ID '{input_node_id}' (found in graph) does not exist as a key in the prompt structure.")
            return jsonify({"success": False, "message": f"Mismatch between graph node ID and prompt structure key for input node."}), 500

        inputs_to_update = prompt_workflow[input_node_id]['inputs']
        app.logger.info(f"Preparing to inject data into prompt node ID: {input_node_id}")

        # Map staged keys to node input names (as defined in NodeBridge_Input.INPUT_TYPES)
        # 将暂存键映射到节点输入名称（在 NodeBridge_Input.INPUT_TYPES 中定义）
        key_to_input_map = {
            'current_line_draft': 'Image',
            'current_reference': 'Reference',
            'current_prompt': 'Text',
            'current_strength': 'CN',
            'current_count': 'Count',
        }

        active_inputs = {} # Store only the inputs we actually inject / 只存储我们实际注入的输入
        for stage_key, node_input_name in key_to_input_map.items():
            if stage_key in staged_data_store:
                staged_value = staged_data_store[stage_key]
                app.logger.debug(f"Processing staged key: {stage_key} for node input: {node_input_name}")

                if isinstance(staged_value, dict) and staged_value.get("type") == "image_file":
                    filepath = staged_value.get("filepath")
                    if filepath and os.path.exists(filepath):
                        app.logger.info(f"Uploading staged image '{filepath}' for input '{node_input_name}'...")
                        upload_info = upload_image_to_comfyui(filepath)
                        if upload_info and 'name' in upload_info:
                            active_inputs[node_input_name] = upload_info['name']
                            app.logger.info(f"Injecting image '{upload_info['name']}' into input '{node_input_name}'.")
                            # Optionally remove local staged file after successful upload
                            # 在成功上传后可选择删除本地暂存文件
                            # try: os.remove(filepath) except OSError: pass
                        else:
                            app.logger.warning(f"Failed to upload staged image for key '{stage_key}'. Skipping input '{node_input_name}'.")
                    else:
                        app.logger.warning(f"Staged image file path not found or invalid for key '{stage_key}'. Skipping input '{node_input_name}'.")
                else:
                    active_inputs[node_input_name] = staged_value
                    app.logger.info(f"Injecting value '{staged_value}' into input '{node_input_name}'.")
            else:
                 app.logger.warning(f"No staged data found for key '{stage_key}'. Input '{node_input_name}' will not be included.")

        # Update the prompt node's inputs with only the active ones
        # 仅使用活动的输入更新提示节点的输入
        prompt_workflow[input_node_id]['inputs'] = active_inputs
        app.logger.info(f"Final inputs for node {input_node_id}: {json.dumps(active_inputs)}")


        # 4. Queue the Modified Prompt / 排队修改后的提示
        result = queue_prompt(prompt_workflow, CLIENT_ID)

        if result and 'prompt_id' in result:
            prompt_id = result['prompt_id']
            app.logger.info(f"Workflow triggered successfully. Prompt ID: {prompt_id}, Output Node ID: {output_node_id}")
            return jsonify({
                "success": True,
                "prompt_id": prompt_id,
                "message": "Workflow triggered successfully.",
                "output_node_id": output_node_id # Pass potentially null output node ID / 传递可能为 null 的输出节点 ID
            })
        else:
            app.logger.error(f"Failed to queue prompt in ComfyUI. Result: {result}")
            error_details = result.get('error', 'Unknown error') if result else 'Queue request failed'
            node_errors = result.get('node_errors', {}) if result else {}
            return jsonify({
                "success": False,
                "message": "Failed to queue prompt in ComfyUI.",
                "details": error_details,
                "node_errors": node_errors
            }), 500

    except Exception as e:
        app.logger.error(f"Error in /api/trigger_prompt: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Internal server error during trigger."}), 500

# --- Main Execution ---
if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
        app.logger.info(f"Created upload folder: {UPLOAD_FOLDER}")

    app.logger.info(f"Flask app running. Access at http://127.0.0.1:5000 or http://0.0.0.0:5000")
    app.logger.info(f"Expecting ComfyUI at http://{COMFYUI_ADDRESS}")
    app.run(host='0.0.0.0', port=5000, debug=True)