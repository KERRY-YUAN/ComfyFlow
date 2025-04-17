import os
import json
import uuid
from flask import Flask, render_template, request, jsonify, send_from_directory
import requests
import traceback

app = Flask(__name__)

# --- Configuration ---
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
COMFYUI_URL = os.environ.get('COMFYUI_API_URL', DEFAULT_COMFYUI_URL)
print(f"--- Using ComfyUI URL: {COMFYUI_URL} ---")

# Directory containing workflow JSON files (relative to app.py)
# 包含工作流 JSON 文件的目录（相对于 app.py）
WORKFLOWS_DIR = 'workflows'

# Load workflow configurations (Node IDs etc.) using base filename as key
# 使用基本文件名作为键加载工作流配置（节点 ID 等）
WORKFLOW_CONFIG_FILE = 'workflows_config.json'
WORKFLOW_CONFIGS = {} # Stores config like node IDs, keyed by base filename / 存储节点 ID 等配置，由基本文件名索引
if os.path.exists(WORKFLOW_CONFIG_FILE):
    try:
        with open(WORKFLOW_CONFIG_FILE, 'r', encoding='utf-8') as f:
            WORKFLOW_CONFIGS = json.load(f)
        print(f"--- Loaded workflow NODE ID configurations from {WORKFLOW_CONFIG_FILE} ---")
    except (json.JSONDecodeError, IOError) as e:
        print(f"[ERROR] Failed to load or parse {WORKFLOW_CONFIG_FILE}: {e}")
else:
    print(f"[WARNING] Workflow configuration file {WORKFLOW_CONFIG_FILE} not found. Node IDs might be missing.")

# --- Routes ---

@app.route('/icon.ico')
def favicon():
    template_dir = os.path.join(app.root_path, 'templates')
    icon_path = os.path.join(template_dir, 'icon.ico')
    # print(f"Serving favicon from: {icon_path}") # Debug
    if not os.path.exists(icon_path):
        print("Favicon file not found in templates folder.")
        return "", 404
    try:
        return send_from_directory(template_dir, 'icon.ico', mimetype='image/vnd.microsoft.icon')
    except Exception as e:
        print(f"Error serving favicon: {e}")
        return "", 500

@app.route('/')
def index():
    """Serve the frontend page and dynamically discover workflows."""
    workflow_options = {}
    workflows_path = os.path.join(app.root_path, WORKFLOWS_DIR)
    print(f"Scanning for workflows in: {workflows_path}") # Debug
    if os.path.isdir(workflows_path):
        try:
            for filename in os.listdir(workflows_path):
                if filename.lower().endswith(".json"):
                    # Use filename without extension as the key and display name
                    base_name = os.path.splitext(filename)[0]
                    workflow_options[base_name] = base_name # Key: name_without_ext, Value: name_without_ext
                    print(f"Found workflow: {filename} -> Key: {base_name}") # Debug
        except OSError as e:
            print(f"[ERROR] Cannot access workflows directory {workflows_path}: {e}")
    else:
        print(f"[WARNING] Workflows directory not found: {workflows_path}")

    if not workflow_options:
         print("[WARNING] No workflow JSON files found.")
         # Optionally add a default placeholder if none found
         # workflow_options['none_found'] = "未找到工作流文件"

    print("Passing workflow options to template:", workflow_options)
    return render_template('index.html', workflow_options=workflow_options)

# --- API Routes (upload, render) ---
@app.route('/api/upload', methods=['POST'])
def upload_image():
    if 'image' not in request.files: return jsonify({"success": False, "message": "No image file"}), 400
    file = request.files['image']
    if file.filename == '': return jsonify({"success": False, "message": "No selected file"}), 400
    try:
        files = {'image': (file.filename, file.stream, file.mimetype)}
        payload = {'overwrite': 'true'}; response = requests.post(f"{COMFYUI_URL}/upload/image", files=files, data=payload); response.raise_for_status()
        comfyui_response = response.json(); print(f"Image uploaded: {comfyui_response}")
        return jsonify({"success": True, "data": comfyui_response})
    except requests.exceptions.RequestException as e: print(f"[ERROR] Upload ComfyUI comms error: {e}"); return jsonify({"success": False, "message": f"Error communicating with ComfyUI: {e}"}), 502
    except Exception as e: print(f"[ERROR] Upload server error: {e}"); return jsonify({"success": False, "message": "Internal server error"}), 500

@app.route('/api/render', methods=['POST'])
def render():
    try:
        data = request.json
        print("Received render request data:", data)

        # --- 1. Get Selected Workflow Key (base filename) ---
        # Frontend now sends the key from the dropdown value
        workflow_key = data.get('workflow_key') # Changed from workflow_name
        if not workflow_key:
             return jsonify({"success": False, "message": "Missing 'workflow_key' in request"}), 400

        # --- 2. Find Config (Node IDs) and File Path ---
        selected_config = WORKFLOW_CONFIGS.get(workflow_key)
        if not selected_config:
            # Allow fallback if config entry missing but file exists? Or require config?
            # For now, let's allow fallback but warn about missing Node IDs.
            print(f"[WARNING] Workflow configuration for key '{workflow_key}' not found in {WORKFLOW_CONFIG_FILE}. Node IDs may be incorrect/missing.")
            node_ids = {} # Use empty dict if config missing
            # Construct the expected filename based on the key
            workflow_filename = f"{workflow_key}.json"
            workflow_file_path = os.path.join(app.root_path, WORKFLOWS_DIR, workflow_filename)
        else:
            node_ids = selected_config.get('node_ids', {})
             # Use path from config if available, otherwise construct it
            workflow_file_path = selected_config.get('workflow_file', os.path.join(app.root_path, WORKFLOWS_DIR, f"{workflow_key}.json"))
            # Ensure the configured path is relative to app.py if not absolute
            if not os.path.isabs(workflow_file_path):
                workflow_file_path = os.path.join(app.root_path, workflow_file_path)

        print(f"Using workflow file: {workflow_file_path}")
        print(f"Using Node IDs for '{workflow_key}': {node_ids}")

        # --- 3. Load Base Workflow JSON ---
        if not os.path.exists(workflow_file_path):
             # Construct absolute path for error message if relative was used
            abs_path_for_error = os.path.abspath(workflow_file_path)
            return jsonify({"success": False, "message": f"Workflow file '{abs_path_for_error}' not found."}), 500
        with open(workflow_file_path, 'r', encoding='utf-8') as f:
            workflow_prompt = json.load(f)

        # --- 4. Modify Workflow JSON Dynamically (using node_ids) ---
        # (Input mapping logic - remains the same as before)
        # ... [Line Draft Update] ...
        node_id = node_ids.get("line_draft_loader");
        if node_id and 'lineDraft' in data and data['lineDraft'] and 'filename' in data['lineDraft']:
            if node_id in workflow_prompt: workflow_prompt[node_id]['inputs']['image'] = data['lineDraft']['filename']; print(f"Updated node {node_id} (line_draft)")
            else: print(f"Warning: Node ID {node_id} for line draft not found in workflow '{workflow_key}'.")
        # ... [Reference Update] ...
        node_id = node_ids.get("reference_loader");
        if node_id and 'reference' in data and data['reference'] and 'filename' in data['reference']:
             if node_id in workflow_prompt: workflow_prompt[node_id]['inputs']['image'] = data['reference']['filename']; print(f"Updated node {node_id} (reference)")
             else: print(f"Warning: Node ID {node_id} for reference not found in workflow '{workflow_key}'.")
        # ... [Text Prompt Update] ...
        node_id = node_ids.get("text_prompt");
        if node_id:
            if node_id in workflow_prompt: workflow_prompt[node_id]['inputs']['text'] = data.get('textPrompt', ''); print(f"Updated node {node_id} (text_prompt)")
            else: print(f"Warning: Node ID {node_id} for text prompt not found in workflow '{workflow_key}'.")
        # ... [Control Strength Update] ...
        node_id = node_ids.get("control_strength");
        if node_id and 'controlStrength' in data:
            if node_id in workflow_prompt:
                if 'strength' in workflow_prompt[node_id]['inputs']: workflow_prompt[node_id]['inputs']['strength'] = float(data.get('controlStrength', 0.5)); print(f"Updated node {node_id} (control_strength)")
                else: print(f"Warning: Input key 'strength' not found in node {node_id} for workflow '{workflow_key}'.")
            else: print(f"Warning: Node ID {node_id} for control strength not found in workflow '{workflow_key}'.")
        # ... [Batch Count Update] ...
        node_id = node_ids.get("batch_count");
        if node_id and 'cardCount' in data:
             if node_id in workflow_prompt:
                 if 'batch_size' in workflow_prompt[node_id]['inputs']: workflow_prompt[node_id]['inputs']['batch_size'] = int(data.get('cardCount', 1)); print(f"Updated node {node_id} (batch_count)")
                 else: print(f"Warning: Input key 'batch_size' not found in node {node_id} for workflow '{workflow_key}'.")
             else: print(f"Warning: Node ID {node_id} for batch count not found in workflow '{workflow_key}'.")

        # --- 5. Prepare and Send to ComfyUI ---
        client_id = str(uuid.uuid4())
        prompt_payload = { "prompt": workflow_prompt, "client_id": client_id }
        response = requests.post(f"{COMFYUI_URL}/prompt", json=prompt_payload); response.raise_for_status()
        comfyui_response = response.json(); print("ComfyUI prompt response:", comfyui_response)
        if 'prompt_id' in comfyui_response: return jsonify({ "success": True, "prompt_id": comfyui_response['prompt_id'], "client_id": client_id, "node_errors": comfyui_response.get('node_errors', {}) })
        else: return jsonify({"success": False, "message": "ComfyUI did not return a prompt_id", "details": comfyui_response}), 500

    # --- Exception Handling ---
    except requests.exceptions.RequestException as e: print(f"[ERROR] Render ComfyUI comms error: {e}"); return jsonify({"success": False, "message": f"Error communicating with ComfyUI: {e}"}), 502
    except json.JSONDecodeError as e: print(f"[ERROR] Render JSON decode error: {e}"); return jsonify({"success": False, "message": "Error decoding JSON data."}), 400 if isinstance(e, json.JSONDecodeError) and e.doc == request.data else 500
    except KeyError as e: print(f"[ERROR] Render KeyError: {e}"); return jsonify({"success": False, "message": f"Config/Workflow error: Missing key {e}"}), 500
    except Exception as e: print(f"[ERROR] Render server error: {traceback.format_exc()}"); return jsonify({"success": False, "message": "Internal server error"}), 500

if __name__ == '__main__':
    flask_port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    print(f"--- Flask starting on host 0.0.0.0, port {flask_port} ---")
    app.run(host='0.0.0.0', port=flask_port, debug=False, threaded=True)