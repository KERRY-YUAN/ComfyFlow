import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, font as tkfont, filedialog
import subprocess
import os
import threading
import queue
import time
import json
import webbrowser
# import re # No longer needed

# --- Configuration File ---
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launcher_config.json")

# --- Default Values ---
DEFAULT_COMFYUI_INSTALL_DIR = "D:\\Program\\ComfyUI_Program\\ComfyUI"
DEFAULT_COMFYUI_PORTABLE_PYTHON = "D:\\Program\\ComfyUI_Program\\python_embeded\\python.exe"
DEFAULT_FLASK_PORT = "5000"
DEFAULT_COMFYUI_API_PORT = "8188"

# --- Constants for Styling ---
UPDATE_INTERVAL_MS = 100
BG_COLOR = "#2d2d2d"
CONTROL_FRAME_BG = "#353535"
TEXT_AREA_BG = "#1e1e1e"
FG_COLOR = "#e0e0e0"
FG_MUTED = "#9e9e9e"
ACCENT_COLOR = "#007aff"
ACCENT_ACTIVE = "#005ecb"
STOP_COLOR = "#5a5a5a"
STOP_ACTIVE = "#ff453a"
STOP_RUNNING_BG = "#b71c1c" # Dark Red
STOP_RUNNING_ACTIVE_BG = "#d32f2f" # Slightly lighter red when hovered/pressed
STOP_RUNNING_FG = "#ffffff" # White text for contrast
BORDER_COLOR = "#484848"
FG_STDOUT = "#e0e0e0"
FG_STDERR = "#ff6b6b"
FG_INFO = "#64d1b8"
FONT_FAMILY_UI = "Segoe UI"
FONT_FAMILY_MONO = "Consolas"
FONT_SIZE_NORMAL = 10
FONT_SIZE_MONO = 9
FONT_WEIGHT_BOLD = "bold"
VERSION_INFO = "Kerry, Ver. 1.0.0"

# Special marker for queue
_COMFYUI_READY_MARKER_ = "_COMFYUI_IS_READY_FOR_BROWSER_\n"

class ConfigurableServiceRunnerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("服务运行与配置 / Service Runner & Config")
        self.root.geometry("950x650")
        self.root.configure(bg=BG_COLOR)
        self.root.minsize(750, 500)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self.comfyui_process = None
        self.flask_process = None
        self.comfyui_output_queue = queue.Queue()
        self.flask_output_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.comfyui_dir_var = tk.StringVar()
        self.python_exe_var = tk.StringVar()
        self.flask_port_var = tk.StringVar()
        self.comfyui_api_port_var = tk.StringVar()
        self.config = {}
        self.backend_browser_triggered_for_session = False
        self.comfyui_ready_marker_sent = False

        self.load_config()
        self.update_derived_paths()
        self.setup_styles()
        self.setup_ui()
        self.root.after(UPDATE_INTERVAL_MS, self.process_output_queues)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # --- Configuration Handling ---
    def load_config(self):
        loaded_config = {}
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                print(f"Configuration loaded from {CONFIG_FILE}")
            else:
                print("Config file not found, using defaults...")
        except Exception as e:
            print(f"Error loading config: {e}. Using defaults.")
            loaded_config = {} # Ensure empty on error

        self.config = {
            "comfyui_dir": loaded_config.get("comfyui_dir", DEFAULT_COMFYUI_INSTALL_DIR),
            "python_exe": loaded_config.get("python_exe", DEFAULT_COMFYUI_PORTABLE_PYTHON),
            "flask_port": loaded_config.get("flask_port", DEFAULT_FLASK_PORT),
            "comfyui_api_port": loaded_config.get("comfyui_api_port", DEFAULT_COMFYUI_API_PORT)
        }
        self.comfyui_dir_var.set(self.config.get("comfyui_dir", ""))
        self.python_exe_var.set(self.config.get("python_exe", ""))
        self.flask_port_var.set(self.config.get("flask_port", DEFAULT_FLASK_PORT))
        self.comfyui_api_port_var.set(self.config.get("comfyui_api_port", DEFAULT_COMFYUI_API_PORT))

        if not os.path.exists(CONFIG_FILE) or not loaded_config:
            print("Attempting to save default configuration...")
            try:
                self.save_config_to_file(show_success=False)
            except Exception as e:
                print(f"Initial config save failed: {e}")

    def save_config_to_file(self, show_success=True):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            print(f"Configuration saved to {CONFIG_FILE}")
            if show_success and self.root:
                 messagebox.showinfo("Settings Saved", "Configuration saved successfully.", parent=self.root)
        except Exception as e:
             print(f"Error saving config file: {e}")
             if self.root:
                 messagebox.showerror("Config Save Error", f"Cannot save config to file:\n{e}", parent=self.root)

    def update_derived_paths(self):
        self.base_project_dir = os.path.dirname(os.path.abspath(__file__))
        self.comfyui_install_dir = self.config.get("comfyui_dir", "")
        self.comfyui_portable_python = self.config.get("python_exe", "")
        self.venv_python_exe = os.path.join(self.base_project_dir, "venv", "Scripts", "python.exe")
        self.app_script = os.path.join(self.base_project_dir, "app.py")
        self.comfyui_main_script = os.path.join(self.comfyui_install_dir, "main.py") if self.comfyui_install_dir else ""
        self.flask_working_dir = self.base_project_dir
        self.flask_port = self.config.get("flask_port", DEFAULT_FLASK_PORT)
        self.comfyui_api_port = self.config.get("comfyui_api_port", DEFAULT_COMFYUI_API_PORT)
        self.comfyui_args = [
            "--listen",
            f"--port={self.comfyui_api_port}",
            f"--enable-cors-header=http://127.0.0.1:{self.flask_port}",
            f"--enable-cors-header=http://localhost:{self.flask_port}"
        ]
        print(f"--- Paths Updated ---")
        print(f" ComfyUI Port: {self.comfyui_api_port}")
        print(f" Flask Port: {self.flask_port}")
        print(f" ComfyUI Args: {self.comfyui_args}")

    def save_settings(self):
        print("--- Saving Settings ---")
        self.config["comfyui_dir"] = self.comfyui_dir_var.get()
        self.config["python_exe"] = self.python_exe_var.get()
        self.config["comfyui_api_port"] = self.comfyui_api_port_var.get()
        self.config["flask_port"] = self.flask_port_var.get()
        self.save_config_to_file(show_success=True)
        self.update_derived_paths()
        print("Settings saved and paths updated.")

    def browse_directory(self, var_to_set):
        directory = filedialog.askdirectory(title="Select Directory", parent=self.root)
        if directory:
            var_to_set.set(os.path.normpath(directory))

    def browse_file(self, var_to_set, filetypes):
        filepath = filedialog.askopenfilename(title="Select File", filetypes=filetypes, parent=self.root)
        if filepath:
            var_to_set.set(os.path.normpath(filepath))

    # --- Styling Setup ---
    def setup_styles(self):
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use('clam')
        except tk.TclError:
            pass # If clam theme not available, use default

        self.style.configure('.', background=BG_COLOR, foreground=FG_COLOR, font=(FONT_FAMILY_UI, FONT_SIZE_NORMAL), bordercolor=BORDER_COLOR)
        self.style.map('.', background=[('active', '#4f4f4f'), ('disabled', '#404040')])
        self.style.map('.', foreground=[('disabled', FG_MUTED)])

        self.style.configure('TFrame', background=BG_COLOR)
        self.style.configure('Control.TFrame', background=CONTROL_FRAME_BG)
        self.style.configure('Settings.TFrame', background=BG_COLOR)

        self.style.configure('TLabel', background=BG_COLOR, foreground=FG_COLOR)
        self.style.configure('Status.TLabel', background=CONTROL_FRAME_BG, foreground=FG_MUTED, padding=(5, 3))
        self.style.configure('Version.TLabel', background=BG_COLOR, foreground=FG_MUTED, font=(FONT_FAMILY_UI, FONT_SIZE_NORMAL - 1))

        self.style.configure('TButton', padding=(10, 6), anchor=tk.CENTER, font=(FONT_FAMILY_UI, FONT_SIZE_NORMAL), borderwidth=0, relief=tk.FLAT)
        self.style.map('TButton', background=[('active', '#555555')])

        self.style.configure("Accent.TButton", background=ACCENT_COLOR, foreground="white", font=(FONT_FAMILY_UI, FONT_SIZE_NORMAL, FONT_WEIGHT_BOLD))
        self.style.map("Accent.TButton", background=[('pressed', ACCENT_ACTIVE), ('active', '#006ae0'), ('disabled', '#4a5a6a')], foreground=[('disabled', FG_MUTED)])

        self.style.configure("Stop.TButton", background=STOP_COLOR, foreground=FG_COLOR)
        self.style.map("Stop.TButton", background=[('pressed', STOP_ACTIVE), ('active', '#6e6e6e'), ('disabled', '#505050')])

        self.style.configure("StopRunning.TButton", background=STOP_RUNNING_BG, foreground=STOP_RUNNING_FG)
        self.style.map("StopRunning.TButton", background=[('pressed', STOP_RUNNING_ACTIVE_BG), ('active', STOP_RUNNING_ACTIVE_BG), ('disabled', '#505050')], foreground=[('disabled', FG_MUTED)])

        self.style.configure('TNotebook', background=BG_COLOR, borderwidth=0, tabmargins=[5, 5, 5, 0])
        self.style.configure('TNotebook.Tab', padding=[15, 8], background=BG_COLOR, foreground=FG_MUTED, font=(FONT_FAMILY_UI, FONT_SIZE_NORMAL), borderwidth=0)
        self.style.map('TNotebook.Tab', background=[('selected', '#4a4a4a'), ('active', '#3a3a3a')], foreground=[('selected', 'white'), ('active', FG_COLOR)], focuscolor=self.style.lookup('TNotebook.Tab', 'background'))

        self.style.configure('Horizontal.TProgressbar', thickness=6, background=ACCENT_COLOR, troughcolor=CONTROL_FRAME_BG, borderwidth=0)

        self.style.configure('TEntry', fieldbackground=TEXT_AREA_BG, foreground=FG_COLOR, insertcolor='white', bordercolor=BORDER_COLOR, borderwidth=1)
        self.style.map('TEntry', fieldbackground=[('focus', TEXT_AREA_BG)], bordercolor=[('focus', ACCENT_COLOR)], lightcolor=[('focus', ACCENT_COLOR)])

    # --- UI Setup ---
    def setup_ui(self):
        # Top Control Frame
        control_frame = ttk.Frame(self.root, padding=(10, 10, 10, 5), style='Control.TFrame')
        control_frame.grid(row=0, column=0, sticky="ew")
        control_frame.columnconfigure(1, weight=1) # Spacer expands

        self.status_label = ttk.Label(control_frame, text="状态: 空闲 / Status: Idle", style='Status.TLabel', anchor=tk.W)
        self.status_label.grid(row=0, column=0, sticky="w", padx=(0, 10))

        self.progress_bar = ttk.Progressbar(control_frame, mode='indeterminate', length=300, style='Horizontal.TProgressbar')
        self.progress_bar.grid(row=0, column=2, padx=10)

        self.stop_button = ttk.Button(control_frame, text="停止服务 / Stop", command=self.stop_all_services, style="Stop.TButton")
        self.stop_button.grid(row=0, column=3, padx=(0, 5))
        self.stop_button.config(state=tk.DISABLED)

        self.run_button = ttk.Button(control_frame, text="运行服务 / Run", command=self.start_services_thread, style="Accent.TButton")
        self.run_button.grid(row=0, column=4, padx=(0, 0))

        # Main Notebook
        self.notebook = ttk.Notebook(self.root, style='TNotebook')
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=5, pady=(0, 5))
        self.notebook.enable_traversal()

        # Settings Tab
        self.settings_frame = ttk.Frame(self.notebook, padding="25", style='Settings.TFrame')
        self.settings_frame.columnconfigure(1, weight=1)
        self.settings_frame.rowconfigure(5, weight=1) # Adjust index if needed
        self.notebook.add(self.settings_frame, text=' 设置 / Settings ')
        row_idx = 0
        pady_val = (6, 6)
        padx_val = 5
        # -- Settings Widgets --
        ttk.Label(self.settings_frame, text="ComfyUI 目录 / Directory:").grid(row=row_idx, column=0, sticky=tk.W, pady=pady_val)
        dir_entry = ttk.Entry(self.settings_frame, textvariable=self.comfyui_dir_var, width=60)
        dir_entry.grid(row=row_idx, column=1, sticky="ew", pady=pady_val, padx=padx_val)
        dir_btn = ttk.Button(self.settings_frame, text="浏览 / Browse...", width=12, command=lambda: self.browse_directory(self.comfyui_dir_var))
        dir_btn.grid(row=row_idx, column=2, sticky=tk.E, pady=pady_val, padx=(padx_val, 0))
        row_idx += 1

        ttk.Label(self.settings_frame, text="后端 Python 路径 / Backend Python Path:").grid(row=row_idx, column=0, sticky=tk.W, pady=pady_val)
        py_entry = ttk.Entry(self.settings_frame, textvariable=self.python_exe_var, width=60)
        py_entry.grid(row=row_idx, column=1, sticky="ew", pady=pady_val, padx=padx_val)
        py_btn = ttk.Button(self.settings_frame, text="浏览 / Browse...", width=12, command=lambda: self.browse_file(self.python_exe_var, [("Python Executable", "python.exe"), ("All Files", "*.*")]))
        py_btn.grid(row=row_idx, column=2, sticky=tk.E, pady=pady_val, padx=(padx_val, 0))
        row_idx += 1

        ttk.Label(self.settings_frame, text="后端 API 端口 / Backend API Port:").grid(row=row_idx, column=0, sticky=tk.W, pady=pady_val)
        comfyui_port_entry = ttk.Entry(self.settings_frame, textvariable=self.comfyui_api_port_var, width=10)
        comfyui_port_entry.grid(row=row_idx, column=1, sticky=tk.W, pady=pady_val, padx=padx_val)
        row_idx += 1

        ttk.Label(self.settings_frame, text="前端网页端口 / Frontend Web Port:").grid(row=row_idx, column=0, sticky=tk.W, pady=pady_val)
        flask_port_entry = ttk.Entry(self.settings_frame, textvariable=self.flask_port_var, width=10)
        flask_port_entry.grid(row=row_idx, column=1, sticky=tk.W, pady=pady_val, padx=padx_val)
        row_idx += 1

        # Spacer row
        self.settings_frame.rowconfigure(row_idx, minsize=20)
        row_idx += 1

        # Bottom row for Save/Version
        bottom_row_idx = row_idx
        self.settings_frame.rowconfigure(bottom_row_idx, weight=1)
        save_btn = ttk.Button(self.settings_frame, text="保存设置 / Save Settings", style="TButton", command=self.save_settings)
        save_btn.grid(row=bottom_row_idx, column=0, sticky="sw", padx=(0, padx_val), pady=(10, 0))
        version_label = ttk.Label(self.settings_frame, text=VERSION_INFO, style="Version.TLabel")
        version_label.grid(row=bottom_row_idx, column=2, sticky="se", padx=(padx_val, 0), pady=(10, 0))

        # Output Tabs
        self.app_frame = ttk.Frame(self.notebook, style='TFrame', padding=0)
        self.notebook.add(self.app_frame, text=' 前端_网页 / Frontend ')
        self.app_output_text = scrolledtext.ScrolledText(self.app_frame, wrap=tk.WORD, state=tk.DISABLED, font=(FONT_FAMILY_MONO, FONT_SIZE_MONO), bg=TEXT_AREA_BG, fg=FG_STDOUT, relief=tk.FLAT, borderwidth=1, bd=1, highlightthickness=1, highlightbackground=BORDER_COLOR, insertbackground="white")
        self.app_output_text.pack(expand=True, fill=tk.BOTH, padx=1, pady=1)
        self.setup_text_tags(self.app_output_text)

        self.main_frame = ttk.Frame(self.notebook, style='TFrame', padding=0)
        self.notebook.add(self.main_frame, text=' 后端_ComfyUI / Backend ')
        self.main_output_text = scrolledtext.ScrolledText(self.main_frame, wrap=tk.WORD, state=tk.DISABLED, font=(FONT_FAMILY_MONO, FONT_SIZE_MONO), bg=TEXT_AREA_BG, fg=FG_STDOUT, relief=tk.FLAT, borderwidth=1, bd=1, highlightthickness=1, highlightbackground=BORDER_COLOR, insertbackground="white")
        self.main_output_text.pack(expand=True, fill=tk.BOTH, padx=1, pady=1)
        self.setup_text_tags(self.main_output_text)

        self.notebook.select(self.settings_frame) # Default tab

    # --- Text/Output Methods ---
    def setup_text_tags(self, text_widget):
        text_widget.tag_config("stdout", foreground=FG_STDOUT)
        text_widget.tag_config("stderr", foreground=FG_STDERR)
        text_widget.tag_config("info", foreground=FG_INFO, font=(FONT_FAMILY_MONO, FONT_SIZE_MONO, 'italic'))

    def insert_output(self, text_widget, line, source_tag="stdout"):
        if not text_widget or not text_widget.winfo_exists():
            return
        text_widget.config(state=tk.NORMAL)
        tag = "stdout"
        if "[Launcher]" in source_tag:
            tag = "info"
        elif "ERR" in source_tag.upper() or "ERROR" in line.upper() or "Traceback" in line:
            tag = "stderr"
        elif "WARN" in source_tag.upper() or "WARNING" in line.upper():
            tag = "stderr"
        text_widget.insert(tk.END, line, (tag,))
        text_widget.see(tk.END)
        text_widget.config(state=tk.DISABLED)

    def log_to_gui(self, target, message):
        source_tag = "[Launcher]"
        if target == "ComfyUI":
            self.comfyui_output_queue.put((source_tag, message))
        elif target == "Flask":
            self.flask_output_queue.put((source_tag, message))

    def process_output_queues(self):
        comfy_processed = 0
        while not self.comfyui_output_queue.empty() and comfy_processed < 50:
            try:
                source, line = self.comfyui_output_queue.get_nowait()
                if line.strip() == _COMFYUI_READY_MARKER_.strip():
                    print("DEBUG QUEUE: Marker detected! Triggering backend browser.")
                    self._trigger_backend_browser_opening()
                else:
                    self.insert_output(self.main_output_text, line, source)
                comfy_processed += 1
            except queue.Empty:
                break
            except Exception as e:
                print(f"Error processing ComfyUI queue: {e}")
        flask_processed = 0
        while not self.flask_output_queue.empty() and flask_processed < 50:
            try:
                source, line = self.flask_output_queue.get_nowait()
                self.insert_output(self.app_output_text, line, source)
                flask_processed += 1
            except queue.Empty:
                break
            except Exception as e:
                print(f"Error processing Flask queue: {e}")
        self.root.after(UPDATE_INTERVAL_MS, self.process_output_queues)

    def stream_output(self, process_stream, output_queue, stream_name):
        marker_already_sent_in_this_stream = False
        target_string = "Starting server"
        try:
            for line in iter(process_stream.readline, ''):
                if self.stop_event.is_set():
                    break
                if line:
                    output_queue.put((stream_name, line))
                    if stream_name == "[ComfyUI]" and not marker_already_sent_in_this_stream:
                        if target_string in line:
                            print(f"DEBUG STREAM: Found '{target_string}'. Queuing marker.")
                            output_queue.put((stream_name, _COMFYUI_READY_MARKER_))
                            marker_already_sent_in_this_stream = True
        except ValueError:
            print(f"{stream_name} stream closed (ValueError).")
        except Exception as e:
            print(f"Error reading {stream_name}: {e}")
            try:
                output_queue.put((f"[{stream_name} ERR]", f"Error reading stream: {e}\n"))
            except Exception:
                pass # Avoid error loops
        finally:
            try:
                process_stream.close()
            except Exception:
                pass # Ignore close errors

    # --- Service Management ---
    def _validate_paths_for_execution(self):
        paths_ok = True
        missing = []
        if not self.comfyui_portable_python or not os.path.isfile(self.comfyui_portable_python):
            missing.append(f"Backend Python Path: {self.comfyui_portable_python or 'Not set'}")
            paths_ok = False
        if not self.comfyui_main_script or not os.path.isfile(self.comfyui_main_script):
            missing.append(f"ComfyUI Main Script: {self.comfyui_main_script or 'Cannot determine'}")
            paths_ok = False
        if not self.comfyui_install_dir or not os.path.isdir(self.comfyui_install_dir):
            missing.append(f"ComfyUI Directory: {self.comfyui_install_dir or 'Not set'}")
            paths_ok = False
        if not os.path.isfile(self.venv_python_exe):
            missing.append(f"Frontend Venv Python: {self.venv_python_exe} (Did you create venv?)")
            paths_ok = False
        if not os.path.isfile(self.app_script):
            missing.append(f"Frontend App Script: {self.app_script}")
            paths_ok = False
        if not paths_ok:
            messagebox.showerror("Execution Path Error", "Cannot run services...\n\n" + "\n".join(missing) + "\n\nPlease check settings.", parent=self.root)
            return False
        return True

    def start_services_thread(self):
        if not self._validate_paths_for_execution():
            return
        if (self.comfyui_process and self.comfyui_process.poll() is None) or \
           (self.flask_process and self.flask_process.poll() is None):
            messagebox.showwarning("Already Running", "Services seem to be running...", parent=self.root)
            return
        self.backend_browser_triggered_for_session = False
        self.comfyui_ready_marker_sent = False
        self.clear_output_widgets()
        self.stop_event.clear()
        self.run_button.config(state=tk.DISABLED, text="运行中... / Running...")
        self.stop_button.config(state=tk.NORMAL, style="Stop.TButton")
        self.status_label.config(text="状态: 正在启动... / Status: Starting...")
        self.progress_bar.start(10)
        self.notebook.select(self.main_frame)
        thread = threading.Thread(target=self._run_services, daemon=True)
        thread.start()

    def _run_services(self):
        comfyui_started = False
        flask_started = False
        try: # Start ComfyUI
            self.log_to_gui("ComfyUI", f"Starting Backend_ComfyUI in {self.comfyui_install_dir}...\n")
            comfyui_cmd_list = [self.comfyui_portable_python, self.comfyui_main_script] + self.comfyui_args
            self.log_to_gui("ComfyUI", f"Command: {' '.join(comfyui_cmd_list)}\n")
            creationflags = 0
            startupinfo = None
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NO_WINDOW
            self.comfyui_process = subprocess.Popen(comfyui_cmd_list, cwd=self.comfyui_install_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore', bufsize=1, creationflags=creationflags, startupinfo=startupinfo)
            self.log_to_gui("ComfyUI", f"Backend_ComfyUI PID: {self.comfyui_process.pid}\n")
            comfyui_started = True
            self.comfyui_reader_thread_stdout = threading.Thread(target=self.stream_output, args=(self.comfyui_process.stdout, self.comfyui_output_queue, "[ComfyUI]"), daemon=True)
            self.comfyui_reader_thread_stdout.start()
            self.comfyui_reader_thread_stderr = threading.Thread(target=self.stream_output, args=(self.comfyui_process.stderr, self.comfyui_output_queue, "[ComfyUI ERR]"), daemon=True)
            self.comfyui_reader_thread_stderr.start()
            time.sleep(3) # Check if died early
            if self.comfyui_process.poll() is not None:
                raise Exception(f"ComfyUI process terminated unexpectedly code {self.comfyui_process.poll()}. Check Log.")
        except Exception as e:
            error_msg = f"Failed to start Backend_ComfyUI: {e}\n"
            print(error_msg)
            self.log_to_gui("ComfyUI", error_msg)
            self.root.after(0, lambda: messagebox.showerror("Backend_ComfyUI Error", error_msg, parent=self.root))
            self.root.after(0, self.reset_ui_on_error)
            self.root.after(0, self.progress_bar.stop)
            return
        time.sleep(1)
        try: # Start Flask
            self.log_to_gui("Flask", f"Starting Frontend_Web (Flask) in {self.flask_working_dir}...\n")
            flask_cmd_list = [self.venv_python_exe, self.app_script]
            self.log_to_gui("Flask", f"Command: {' '.join(flask_cmd_list)}\n")
            creationflags = 0
            startupinfo = None
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NO_WINDOW
            flask_env = os.environ.copy()
            flask_env['COMFYUI_API_URL'] = f"http://127.0.0.1:{self.comfyui_api_port}"
            flask_env['FLASK_RUN_PORT'] = self.flask_port
            self.flask_process = subprocess.Popen(flask_cmd_list, cwd=self.flask_working_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore', bufsize=1, creationflags=creationflags, startupinfo=startupinfo, env=flask_env)
            self.log_to_gui("Flask", f"Frontend_Web (Flask) PID: {self.flask_process.pid}\n")
            flask_started = True
            self.flask_reader_thread_stdout = threading.Thread(target=self.stream_output, args=(self.flask_process.stdout, self.flask_output_queue, "[Flask]"), daemon=True)
            self.flask_reader_thread_stdout.start()
            self.flask_reader_thread_stderr = threading.Thread(target=self.stream_output, args=(self.flask_process.stderr, self.flask_output_queue, "[Flask ERR]"), daemon=True)
            self.flask_reader_thread_stderr.start()
            time.sleep(3) # Check if died early
            if self.flask_process.poll() is not None:
                raise Exception(f"Flask process terminated unexpectedly code {self.flask_process.poll()}. Check Log.")
            print("DEBUG: Scheduling frontend browser opening...")
            self.root.after(500, self._open_frontend_browser) # Open frontend browser
        except Exception as e:
             error_msg = f"Failed to start Frontend_Web (Flask): {e}\n"
             print(error_msg)
             self.log_to_gui("Flask", error_msg)
             self.root.after(0, lambda: messagebox.showerror("Frontend_Web Error", error_msg, parent=self.root))
             if comfyui_started and self.comfyui_process:
                 self.log_to_gui("ComfyUI", "Stopping backend due to frontend error...\n")
                 self.comfyui_process.terminate()
                 try:
                     self.comfyui_process.wait(timeout=1)
                 except subprocess.TimeoutExpired:
                     self.comfyui_process.kill()
                 self.comfyui_process = None
             self.root.after(0, self.reset_ui_on_error)
             self.root.after(0, self.progress_bar.stop)
             return
        if comfyui_started and flask_started:
            def update_ui_on_success():
                self.status_label.config(text="状态: 服务运行中 / Status: Services Running")
                self.progress_bar.stop()
                if self.stop_button and self.stop_button.winfo_exists():
                    self.stop_button.config(style="StopRunning.TButton")
            self.root.after(0, update_ui_on_success)

    def _open_frontend_browser(self):
        flask_url = f"http://127.0.0.1:{self.flask_port}"
        print(f"DEBUG: Attempting to open Frontend URL: {flask_url}")
        try:
            webbrowser.open_new_tab(flask_url)
            print("DEBUG: Frontend webbrowser call finished.")
        except Exception as wb_error:
            print(f"Error opening frontend browser tab: {wb_error}")
            self.log_to_gui("Flask", f"[Launcher ERR] Failed to open frontend tab: {wb_error}\n")
            messagebox.showwarning("Browser Error", f"Could not open frontend:\n{wb_error}", parent=self.root)

    def _trigger_backend_browser_opening(self):
        print("DEBUG TRIGGER: _trigger_backend_browser_opening called.")
        print(f"DEBUG TRIGGER: backend_browser_triggered_for_session = {self.backend_browser_triggered_for_session}")
        if not self.backend_browser_triggered_for_session:
            self.backend_browser_triggered_for_session = True
            comfyui_url = f"http://127.0.0.1:{self.comfyui_api_port}"
            print("ComfyUI ready signal processed, opening backend browser tab...")
            try:
                print(f"DEBUG TRIGGER: Attempting to open Backend URL: {comfyui_url}")
                webbrowser.open_new_tab(comfyui_url)
                print("DEBUG TRIGGER: Backend webbrowser call finished.")
            except Exception as wb_error:
                print(f"Error opening backend tab: {wb_error}")
                self.log_to_gui("ComfyUI", f"[Launcher ERR] Failed to open backend tab: {wb_error}\n")
                messagebox.showwarning("Browser Error", f"Could not open backend:\n{wb_error}", parent=self.root)
        else:
            print("DEBUG TRIGGER: Backend browser already triggered, skipping.")

    def stop_all_services(self):
        if not self.comfyui_process and not self.flask_process:
             print("Stop called but no processes seem active.")
             self.run_button.config(state=tk.NORMAL, text="运行服务 / Run")
             self.stop_button.config(state=tk.DISABLED, style="Stop.TButton")
             self.status_label.config(text="状态: 服务已停止 / Status: Services Stopped")
             self.progress_bar.stop()
             return
        self.status_label.config(text="状态: 正在停止... / Status: Stopping...")
        self.progress_bar.start(10)
        self.stop_event.set()
        if self.stop_button and self.stop_button.winfo_exists():
             self.stop_button.config(style="Stop.TButton")
        stopped_any = False
        if self.flask_process and self.flask_process.poll() is None:
            self.log_to_gui("Flask", "Stopping Frontend_Web...\n")
            try:
                self.flask_process.terminate()
                self.flask_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                print("Flask killing.")
                self.flask_process.kill()
            except Exception as e:
                print(f"Error terminating Flask: {e}")
            self.flask_process = None
            stopped_any = True
            self.log_to_gui("Flask", "Frontend_Web Stopped.\n")
        else:
            self.flask_process = None
        if self.comfyui_process and self.comfyui_process.poll() is None:
            self.log_to_gui("ComfyUI", "Stopping Backend_ComfyUI...\n")
            try:
                self.comfyui_process.terminate()
                self.comfyui_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                print("ComfyUI killing.")
                self.comfyui_process.kill()
            except Exception as e:
                print(f"Error terminating ComfyUI: {e}")
            self.comfyui_process = None
            stopped_any = True
            self.log_to_gui("ComfyUI", "Backend_ComfyUI Stopped.\n")
        else:
            self.comfyui_process = None
        time.sleep(0.2)
        self.run_button.config(state=tk.NORMAL, text="运行服务 / Run")
        self.stop_button.config(state=tk.DISABLED, style="Stop.TButton")
        self.status_label.config(text="状态: 服务已停止 / Status: Services Stopped")
        self.progress_bar.stop()
        self.backend_browser_triggered_for_session = False
        self.comfyui_ready_marker_sent = False

    def reset_ui_on_error(self):
        self.run_button.config(state=tk.NORMAL, text="运行服务 / Run")
        self.stop_button.config(state=tk.DISABLED, style="Stop.TButton")
        self.progress_bar.stop()
        self.status_label.config(text="状态: 启动失败 / Status: Startup Failed")
        if self.comfyui_process and self.comfyui_process.poll() is not None:
            self.comfyui_process = None
        if self.flask_process and self.flask_process.poll() is not None:
            self.flask_process = None
        self.backend_browser_triggered_for_session = False
        self.comfyui_ready_marker_sent = False

    def clear_output_widgets(self):
        for widget in [self.main_output_text, self.app_output_text]:
            if widget and widget.winfo_exists():
                widget.config(state=tk.NORMAL)
                widget.delete('1.0', tk.END)
                widget.config(state=tk.DISABLED)

    def on_closing(self):
        print("Closing application...")
        self.stop_all_services()
        self.root.after(100, self.root.destroy)

# --- Main Execution ---
if __name__ == "__main__":
    base_project_dir_check = os.path.dirname(os.path.abspath(__file__))
    venv_python_check = os.path.join(base_project_dir_check, "venv", "Scripts", "python.exe")
    app_script_check = os.path.join(base_project_dir_check, "app.py")
    expected_workflow_config_file = 'workflows_config.json'
    config_check = os.path.join(base_project_dir_check, expected_workflow_config_file)
    critical_error = False
    error_msg = ""
    if not os.path.isfile(venv_python_check):
        error_msg += f"Frontend Venv Python not found:\n{venv_python_check}\n(Create venv & install dependencies)\n\n"
        critical_error = True
    if not os.path.isfile(app_script_check):
        error_msg += f"Frontend App Script not found:\n{app_script_check}\n\n"
        critical_error = True
    if not os.path.isfile(config_check):
        error_msg += f"Workflow config file not found:\n{config_check}\n(Create {expected_workflow_config_file} and configure workflows.)\n\n"
        critical_error = True
    if critical_error:
        root_err = tk.Tk()
        root_err.withdraw()
        messagebox.showerror("Startup Error", error_msg + "Application will exit.")
        root_err.destroy()
        exit()
    root = tk.Tk()
    app = ConfigurableServiceRunnerApp(root)
    root.mainloop()