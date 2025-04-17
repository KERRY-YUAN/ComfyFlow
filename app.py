# -*- coding: utf-8 -*-
import os
import json
import uuid
from flask import Flask, render_template, request, jsonify, send_file, abort
import requests
import traceback
import logging
# PIL and io are needed for staging potentially, but not directly in trigger_prompt logic anymore for value setting
# from PIL import Image
# import io
import time

# Configure basic logging for app.py itself
# 为 app.py 本身配置基本日志记录
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24) # Good practice / 良好实践

# --- In-memory Data Staging ---
staged_data = {}

# --- Configuration ---
DEFAULT_COMFYUI_API_PORT = "8188"
DEFAULT_FLASK_PORT = "5000"
COMFYUI_API_PORT = os.environ.get('COMFYUI_API_PORT', DEFAULT_COMFYUI_API_PORT)
FLASK_PORT = int(os.environ.get('FLASK_RUN_PORT', DEFAULT_FLASK_PORT))
COMFYUI_URL = f"http://127.0.0.1:{COMFYUI_API_PORT}"
app.logger.info(f"--- Using ComfyUI URL: {COMFYUI_URL} ---")
COMFYUI_WORKFLOW_DIR = os.environ.get('COMFYUI_WORKFLOW_DIR')
if not COMFYUI_WORKFLOW_DIR or not os.path.isdir(COMFYUI_WORKFLOW_DIR):
    app.logger.error(f"!!! ComfyUI Workflow Directory not found or invalid: {COMFYUI_WORKFLOW_DIR} !!!")
    COMFYUI_WORKFLOW_DIR = None
else:
    app.logger.info(f"--- Using ComfyUI Workflow Directory: {COMFYUI_WORKFLOW_DIR} ---")

# --- Routes ---

@app.route('/icon.ico')
def favicon():
    """Serve the favicon. / 提供网站图标。"""
    template_dir = os.path.join(app.root_path, 'templates')
    icon_path = os.path.join(template_dir, 'icon.ico')
    if os.path.exists(icon_path):
        return send_file(icon_path, mimetype='image/vnd.microsoft.icon')
    else:
        abort(404)

@app.route('/')
def index():
    """Serve frontend, scan ComfyUI workflow dir, pass ComfyUI port"""
    """提供前端，扫描 ComfyUI 工作流目录，传递 ComfyUI 端口"""
    workflow_options = {}
    # ... (Code to scan workflow directory - remains the same) ...
    if COMFYUI_WORKFLOW_DIR:
        app.logger.info(f"Scanning for workflows in ComfyUI dir: {COMFYUI_WORKFLOW_DIR}")
        try:
            for filename in os.listdir(COMFYUI_WORKFLOW_DIR):
                if filename.lower().endswith(".json"):
                    if os.path.isfile(os.path.join(COMFYUI_WORKFLOW_DIR, filename)):
                        base_name = os.path.splitext(filename)[0]
                        workflow_options[filename] = base_name # Use filename as key, base_name as display name
                        app.logger.debug(f"Found ComfyUI workflow: {filename}")
        except OSError as e:
            app.logger.error(f"Cannot access ComfyUI workflows directory {COMFYUI_WORKFLOW_DIR}: {e}")
    else:
        app.logger.error("ComfyUI workflow directory not configured or accessible. Cannot list workflows.")

    if not workflow_options:
        app.logger.warning("No ComfyUI workflow JSON files found in the specified directory.")

    return render_template('index.html',
                           workflow_options=workflow_options,
                           comfyui_api_port=COMFYUI_API_PORT)


# --- API: Staging Data (Remains the same) ---
@app.route('/api/stage_data', methods=['POST'])
def stage_data():
    """Receives data from frontend and stores it in memory."""
    """接收来自前端的数据并将其存储在内存中。"""
    try:
        data_key = request.form.get('key') # e.g., "current_line_draft"
        data_type = request.form.get('type') # e.g., "Image", "Text", "Float", "Int"

        if not data_key or not data_type:
            return jsonify({"success": False, "message": "Missing 'key' or 'type' form data. / 缺少 'key' 或 'type' 表单数据。"}), 400

        app.logger.info(f"Received stage request for key: {data_key}, type: {data_type}")
        staged_value = None
        image_filename_for_node = None # Store filename if it's an uploaded image

        if data_type == "Image":
            if 'image_file' not in request.files:
                return jsonify({"success": False, "message": "Missing 'image_file' for Image type. / 图片类型缺少 'image_file'。"}), 400
            file = request.files['image_file']
            if file.filename == '':
                 return jsonify({"success": False, "message": "No selected file for Image type. / 图片类型未选择文件。"}), 400

            # Upload to ComfyUI and store filename in staged_value
            app.logger.info(f"Uploading image '{file.filename}' to ComfyUI input...")
            try:
                file_bytes = file.read()
                files = {'image': (file.filename, io.BytesIO(file_bytes), file.mimetype)}
                payload = {'overwrite': 'true', 'type': 'input'}
                response = requests.post(f"{COMFYUI_URL}/upload/image", files=files, data=payload, timeout=60)
                response.raise_for_status()
                comfy_response = response.json()
                app.logger.info(f"ComfyUI Upload Response: {comfy_response}")
                if comfy_response and 'name' in comfy_response:
                    image_filename_for_node = comfy_response['name']
                    staged_value = image_filename_for_node # Store the filename
                else:
                    app.logger.error(f"ComfyUI upload failed or returned invalid response structure: {comfy_response}")
                    raise Exception("ComfyUI upload failed or returned invalid response.")
            except requests.exceptions.RequestException as e:
                 app.logger.error(f"Error uploading to ComfyUI: {e}")
                 return jsonify({"success": False, "message": f"Failed to upload image to ComfyUI ({COMFYUI_URL}/upload/image): {e}"}), 502
            except Exception as upload_err:
                 app.logger.error(f"Error processing ComfyUI upload: {upload_err}")
                 return jsonify({"success": False, "message": f"Failed during ComfyUI upload process: {upload_err}"}), 500

        elif data_type == "Text":
            staged_value = request.form.get('value', '')
        elif data_type == "Float":
            try: staged_value = float(request.form.get('value', 0.0))
            except (ValueError, TypeError): return jsonify({"success": False, "message": "Invalid Float value. / 无效的浮点数值。"}), 400
        elif data_type == "Int":
            try: staged_value = int(request.form.get('value', 0))
            except (ValueError, TypeError): return jsonify({"success": False, "message": "Invalid Int value. / 无效的整数值。"}), 400
        else:
            return jsonify({"success": False, "message": f"Unsupported data type: {data_type} / 不支持的数据类型: {data_type}"}), 400

        # Store the final value (filename for image, or direct value for others)
        staged_data[data_key] = staged_value
        app.logger.info(f"Staged data for key '{data_key}': {staged_value}")
        response_data = {"success": True, "key": data_key, "value": staged_value}
        if image_filename_for_node:
            response_data["uploaded_filename"] = image_filename_for_node
        return jsonify(response_data)

    except Exception as e:
        app.logger.error(f"[ERROR] Failed to stage data: {traceback.format_exc()}")
        return jsonify({"success": False, "message": f"Internal server error staging data: {e}"}), 500

# --- API: Get Workflow Nodes (Remains the same, useful for frontend checks) ---
@app.route('/api/get_workflow_nodes', methods=['GET'])
def get_workflow_nodes():
    """Gets info about nodes from a specified workflow file."""
    """获取指定工作流文件中节点的信息。"""
    # ... (Code remains the same as previous version) ...
    if not COMFYUI_WORKFLOW_DIR:
        # ... (error handling) ...
        app.logger.error("Attempted to get workflow nodes, but COMFYUI_WORKFLOW_DIR is not set or invalid.")
        return jsonify({"error": "ComfyUI workflow directory not configured on server. / 服务器上未配置 ComfyUI 工作流目录。"}), 500

    workflow_filename = request.args.get('workflow_file')
    if not workflow_filename:
        return jsonify({"error": "Missing 'workflow_file' parameter / 缺少 'workflow_file' 参数"}), 400

    if ".." in workflow_filename or "/" in workflow_filename or "\\" in workflow_filename:
        # ... (error handling) ...
         app.logger.warning(f"Potential path traversal attempt blocked for workflow file: {workflow_filename}")
         return jsonify({"error": "Invalid characters in workflow filename / 工作流文件名中包含无效字符"}), 400

    workflow_filepath = os.path.join(COMFYUI_WORKFLOW_DIR, workflow_filename)

    if not os.path.isfile(workflow_filepath):
        # ... (error handling) ...
        app.logger.warning(f"Workflow file not found at path: {workflow_filepath}")
        return jsonify({"error": f"Workflow file not found: {workflow_filename} / 工作流文件未找到: {workflow_filename}"}), 404

    try:
        app.logger.info(f"Reading workflow nodes from: {workflow_filepath}")
        with open(workflow_filepath, 'r', encoding='utf-8') as f:
            workflow_data = json.load(f)
    except json.JSONDecodeError as json_err:
        # ... (error handling) ...
        app.logger.error(f"Invalid JSON format in file {workflow_filename}: {json_err}")
        return jsonify({"error": f"Invalid JSON format in file: {workflow_filename} / 文件 JSON 格式无效: {workflow_filename}"}), 500
    except Exception as e:
        # ... (error handling) ...
        app.logger.error(f"Error reading workflow file {workflow_filename}: {e}")
        return jsonify({"error": f"Error reading file: {str(e)} / 读取文件时出错: {str(e)}"}), 500

    if not isinstance(workflow_data, dict):
        # ... (error handling) ...
        app.logger.error(f"Workflow file {workflow_filename} does not contain a valid JSON object at the root.")
        return jsonify({"error": f"Workflow data is not a valid JSON object / 工作流数据不是有效的 JSON 对象"}), 500

    input_nodes = []
    output_nodes = []
    target_input_type = "NodeBridge_Input"
    target_output_type = "NodeBridge_Output"

    for node_id, node_data in workflow_data.items():
        if not isinstance(node_data, dict):
            app.logger.warning(f"Skipping invalid node data for ID {node_id} in {workflow_filename}")
            continue

        node_type = node_data.get("class_type")
        node_title = node_data.get("_meta", {}).get("title", "")

        node_info = {
            "id": node_id,
            "type": node_type,
            "title": node_title,
            "widgets_values": node_data.get("widgets_values"), # Include widgets
            "inputs": node_data.get("inputs")
        }

        if node_type == target_input_type:
            input_nodes.append(node_info)
            app.logger.debug(f"Found Input Node: ID={node_id}, Type={node_type}, Title='{node_title}', Widgets={node_info['widgets_values']}")
        elif node_type == target_output_type:
            output_nodes.append(node_info)
            app.logger.debug(f"Found Output Node: ID={node_id}, Type={node_type}, Title='{node_title}'")

    app.logger.info(f"Found {len(input_nodes)} input nodes and {len(output_nodes)} output nodes in {workflow_filename}.")
    return jsonify({
        "workflow_file": workflow_filename,
        "input_nodes": input_nodes,
        "output_nodes": output_nodes
    })

# --- *** REVISED API: Trigger Workflow Execution *** ---
# --- *** 修订后的 API：触发工作流执行 *** ---
@app.route('/api/trigger_prompt', methods=['POST'])
def trigger_prompt():
    """
    Loads workflow, finds NodeBridge_Input nodes, injects staged data into 'value' input
    based on node's 'mode' widget, and queues the prompt.
    """
    """
    加载工作流，查找 NodeBridge_Input 节点，根据节点的 'mode' 小部件将暂存数据注入 'value' 输入，
    并对提示进行排队。
    """
    try:
        data = request.json
        workflow_key_or_filename = data.get('workflow_file') # Expect filename like 'workflow1.json'
        if not workflow_key_or_filename:
            return jsonify({"success": False, "message": "Missing 'workflow_file' in request body. / 请求体中缺少 'workflow_file'。"}), 400
        if not COMFYUI_WORKFLOW_DIR:
             app.logger.error("Cannot trigger prompt, COMFYUI_WORKFLOW_DIR is not configured.")
             return jsonify({"success": False, "message": "ComfyUI workflow directory not configured on server. / 服务器上未配置 ComfyUI 工作流目录。"}), 500

        workflow_filename = workflow_key_or_filename
        # Security check
        if ".." in workflow_filename or "/" in workflow_filename or "\\" in workflow_filename:
             app.logger.warning(f"Potential path traversal attempt blocked for workflow file: {workflow_filename}")
             return jsonify({"success": False, "message": "Invalid characters in workflow filename / 工作流文件名中包含无效字符"}), 400

        workflow_file_path = os.path.join(COMFYUI_WORKFLOW_DIR, workflow_filename)
        if not os.path.exists(workflow_file_path):
            app.logger.error(f"Workflow file not found for triggering: {workflow_file_path}")
            return jsonify({"success": False, "message": f"Workflow file '{workflow_filename}' not found. / 未找到工作流文件 '{workflow_filename}'。"}), 404

        app.logger.info(f"Loading workflow for execution: {workflow_file_path}")
        with open(workflow_file_path, 'r', encoding='utf-8') as f:
            workflow_prompt = json.load(f) # Load as dictionary

        app.logger.info(f"Injecting staged data into workflow '{workflow_filename}' based on NodeBridge_Input mode...")
        output_bridge_node_ids = [] # Collect IDs of all output bridge nodes found

        # --- Define mapping from NodeBridge_Input 'mode' to your staged data key ---
        # --- 定义从 NodeBridge_Input 'mode' 到您的暂存数据键的映射 ---
        # This MUST match the modes defined in NodeBridge.py and the keys used in index.html's stageData calls
        # 这必须与 NodeBridge.py 中定义的模式以及 index.html 的 stageData 调用中使用的键匹配
        mode_to_datakey_map = {
            "Image": "current_line_draft",      # Mode 'Image' expects data staged with key 'current_line_draft'
            "Reference": "current_reference",   # Mode 'Reference' expects 'current_reference'
            "Text": "current_prompt",           # Mode 'Text' expects 'current_prompt'
            "Float": "current_strength",      # Mode 'Float' expects 'current_strength'
            "Int": "current_count"            # Mode 'Int' expects 'current_count'
        }

        # --- Iterate through nodes to find and modify NodeBridge_Input ---
        nodes_modified_count = 0
        for node_id, node_data in workflow_prompt.items():
            if not isinstance(node_data, dict): continue # Skip invalid node data

            class_type = node_data.get("class_type")

            if class_type == "NodeBridge_Input":
                # --- Get the 'mode' value for this specific node instance ---
                node_mode = None
                # 'widgets_values' usually holds the current value of widgets like combos/sliders
                # 'widgets_values' 通常包含组合框/滑块等小部件的当前值
                widgets = node_data.get("widgets_values")

                # Check if widgets_values is a list and non-empty
                if isinstance(widgets, list) and widgets:
                    # *** ASSUMPTION: The 'mode' dropdown is the FIRST widget on the node ***
                    # *** 假设：'mode' 下拉列表是节点上的第一个小部件 ***
                    node_mode = widgets[0]
                    app.logger.debug(f"Node {node_id} (NodeBridge_Input) - Found mode: '{node_mode}' from widgets_values[0].")
                else:
                    # As a fallback, check if 'mode' is set via a connected input (less likely for this design)
                    # 作为后备，检查是否通过连接的输入设置了 'mode'（这种设计的可能性较小）
                    inputs = node_data.get("inputs", {})
                    if isinstance(inputs.get("mode"), str): # Simple string input value
                        node_mode = inputs["mode"]
                        app.logger.debug(f"Node {node_id} (NodeBridge_Input) - Found mode: '{node_mode}' directly from inputs.")
                    # Note: Handling linked inputs (list like [other_node_id, output_index]) is complex here.
                    # We rely on the 'mode' being set directly on the node via its widget.
                    # 注意：此处处理链接输入（类似 [other_node_id, output_index] 的列表）很复杂。
                    # 我们依赖于通过其小部件直接在节点上设置的 'mode'。

                if not node_mode:
                    app.logger.warning(f"Node {node_id} (NodeBridge_Input) - Could not determine 'mode'. Skipping injection for this node.")
                    continue # Skip this node if mode cannot be determined

                # --- Find the corresponding staged data key based on the node's mode ---
                staged_data_key = mode_to_datakey_map.get(node_mode)
                if not staged_data_key:
                    app.logger.warning(f"Node {node_id} - No staged data key mapping found for mode '{node_mode}'. Skipping injection.")
                    continue # Skip if no mapping defined for this mode

                # --- Inject the staged data into the node's 'value' input ---
                if staged_data_key in staged_data:
                    value_to_set = staged_data[staged_data_key]

                    # Ensure the 'inputs' dictionary exists within the node data
                    if 'inputs' not in node_data or not isinstance(node_data['inputs'], dict):
                        node_data['inputs'] = {} # Initialize if missing

                    # Set the 'value' input. NodeBridge_Input expects a string.
                    # 设置 'value' 输入。NodeBridge_Input 需要一个字符串。
                    node_data['inputs']['value'] = str(value_to_set)
                    # Also update the 'trigger' input to ensure re-evaluation
                    node_data['inputs']['trigger'] = time.time()

                    app.logger.info(f"  -> Injected data from key '{staged_data_key}' (Value: '{value_to_set}') into Node {node_id} (Mode: {node_mode}) 'value' input.")
                    nodes_modified_count += 1
                else:
                    # If data for this mode wasn't staged, log a warning but still trigger the node
                    app.logger.warning(f"  -> No staged data found for key '{staged_data_key}' needed by Node {node_id} (Mode: {node_mode}). Setting 'value' to empty string.")
                    if 'inputs' not in node_data or not isinstance(node_data['inputs'], dict):
                         node_data['inputs'] = {}
                    node_data['inputs']['value'] = "" # Set to empty string
                    node_data['inputs']['trigger'] = time.time() # Update trigger anyway

            elif class_type == "NodeBridge_Output":
                # Collect all output node IDs
                output_bridge_node_ids.append(node_id)
                app.logger.info(f"  -> Found NodeBridge_Output with ID: {node_id}")

        app.logger.info(f"Finished processing nodes. Modified {nodes_modified_count} NodeBridge_Input nodes.")

        if not output_bridge_node_ids:
             # This is just a warning, maybe the user doesn't need the output in the web UI
             app.logger.warning(f"No NodeBridge_Output node found in workflow '{workflow_filename}'. Result fetching in UI might not work.")

        # --- Send the potentially modified workflow_prompt to ComfyUI ---
        client_id = str(uuid.uuid4())
        prompt_payload = { "prompt": workflow_prompt, "client_id": client_id }
        app.logger.info(f"Sending prompt for workflow '{workflow_filename}' to ComfyUI (Client ID: {client_id})...")

        try:
            response = requests.post(f"{COMFYUI_URL}/prompt", json=prompt_payload, timeout=60) # Increased timeout slightly
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            comfyui_response = response.json()
            app.logger.info(f"ComfyUI prompt response: {comfyui_response}")
        except requests.exceptions.Timeout:
            app.logger.error(f"Timeout sending prompt to ComfyUI at {COMFYUI_URL}/prompt")
            return jsonify({"success": False, "message": "Timeout connecting to ComfyUI / 连接 ComfyUI 超时"}), 504
        except requests.exceptions.ConnectionError:
             app.logger.error(f"Connection error sending prompt to ComfyUI at {COMFYUI_URL}/prompt")
             return jsonify({"success": False, "message": f"Could not connect to ComfyUI at {COMFYUI_URL}. Is it running? / 无法连接到 ComfyUI ({COMFYUI_URL})。它在运行吗？"}), 503
        except requests.exceptions.RequestException as req_err:
            app.logger.error(f"Error sending prompt to ComfyUI: {req_err}")
            # Try to get more details from the response if possible
            error_details = ""
            try:
                error_details = req_err.response.text
            except Exception:
                 pass # Ignore if no response text
            app.logger.error(f"ComfyUI Error Response Body (if any): {error_details}")
            return jsonify({"success": False, "message": f"Error communicating with ComfyUI: {req_err}", "details": error_details}), 502

        # Check if ComfyUI accepted the prompt and returned an ID
        if 'prompt_id' in comfyui_response:
            # Return the list of output node IDs found back to the frontend
            return jsonify({
                "success": True,
                "prompt_id": comfyui_response['prompt_id'],
                "client_id": client_id,
                "output_node_ids": output_bridge_node_ids, # Pass the list of IDs
                "node_errors": comfyui_response.get('node_errors', {}) # Include potential node errors from ComfyUI
            })
        else:
            # Handle cases where ComfyUI returns 200 OK but no prompt_id (e.g., validation error)
            app.logger.error(f"ComfyUI accepted prompt request but did not return a prompt_id. Response: {comfyui_response}")
            return jsonify({"success": False, "message": "ComfyUI did not return a prompt_id (check ComfyUI logs for validation errors). / ComfyUI 未返回 prompt_id（请检查 ComfyUI 日志中的验证错误）。", "details": comfyui_response}), 500

    except json.JSONDecodeError as json_err:
        # Error decoding the incoming request body from frontend
        app.logger.error(f"[ERROR] Invalid JSON received in /api/trigger_prompt: {json_err}")
        return jsonify({"success": False, "message": "Invalid JSON format in request body. / 请求体中的 JSON 格式无效。"}), 400
    except Exception as e:
        # General catch-all for unexpected errors during processing
        app.logger.error(f"[ERROR] Failed to trigger prompt: {traceback.format_exc()}")
        return jsonify({"success": False, "message": f"Internal server error triggering prompt: {e}"}), 500


# --- Main Execution ---
if __name__ == '__main__':
    # Use the FLASK_PORT variable determined earlier
    app.logger.info(f"--- Flask starting on host 0.0.0.0, port {FLASK_PORT} ---")
    # Use simple app.run for development/testing
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False, threaded=True)
    # Consider using Waitress for a more production-ready server:
    # from waitress import serve
    # serve(app, host='0.0.0.0', port=FLASK_PORT)