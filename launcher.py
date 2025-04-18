# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, font as tkfont, filedialog
import subprocess
import os
import threading
import queue
import time
import json
import webbrowser
import requests # Added for port check / 添加用于端口检查
import socket # Fallback or additional checks / 后备或其他检查

# --- Configuration File ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "launcher_config.json")

# --- Default Values ---
DEFAULT_COMFYUI_INSTALL_DIR = ""
DEFAULT_COMFYUI_PORTABLE_PYTHON = ""
DEFAULT_COMFYUI_API_PORT = "8188"
DEFAULT_FP16_VAE = False
DEFAULT_FP8_UNET = False
DEFAULT_FP8_TEXTENC = False
DEFAULT_DISABLE_CUDA_MALLOC = False
DEFAULT_VRAM_MODE = "default"

# --- Constants for Styling ---
UPDATE_INTERVAL_MS = 100
BG_COLOR = "#2d2d2d"
CONTROL_FRAME_BG = "#353535"
TAB_CONTROL_FRAME_BG = "#3c3c3c"
TEXT_AREA_BG = "#1e1e1e"
FG_COLOR = "#e0e0e0"
FG_MUTED = "#9e9e9e"
ACCENT_COLOR = "#007aff"
ACCENT_ACTIVE = "#005ecb"
STOP_COLOR = "#5a5a5a"
STOP_ACTIVE = "#ff453a"
STOP_RUNNING_BG = "#b71c1c"
STOP_RUNNING_ACTIVE_BG = "#d32f2f"
STOP_RUNNING_FG = "#ffffff"
BORDER_COLOR = "#484848"
FG_STDOUT = "#e0e0e0"
FG_STDERR = "#ff6b6b"
FG_INFO = "#64d1b8"
FONT_FAMILY_UI = "Segoe UI"
FONT_FAMILY_MONO = "Consolas"
FONT_SIZE_NORMAL = 10
FONT_SIZE_MONO = 9
FONT_WEIGHT_BOLD = "bold"
VERSION_INFO = "Kerry, Ver. 1.6.1" # Incremented version / 增加版本号

# Special marker for queue
_COMFYUI_READY_MARKER_ = "_COMFYUI_IS_READY_FOR_BROWSER_\n"

class ConfigurableServiceRunnerApp:
    """Main class for the Tkinter application."""
    def __init__(self, root):
        """Initializes the application."""
        self.root = root
        self.root.title("服务运行与配置 / Service Runner & Config")
        self.root.geometry("950x700")
        self.root.configure(bg=BG_COLOR)
        self.root.minsize(750, 550)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        # Process and state variables
        self.comfyui_process = None
        self.flask_process = None
        self.comfyui_output_queue = queue.Queue()
        self.flask_output_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.backend_browser_triggered_for_session = False
        self.comfyui_ready_marker_sent = False
        # --- NEW state variable for external detection ---
        # --- 用于外部检测的新状态变量 ---
        self.comfyui_externally_detected = False

        # Configuration variables
        self.comfyui_dir_var = tk.StringVar()
        self.python_exe_var = tk.StringVar()
        self.comfyui_api_port_var = tk.StringVar()
        self.fp16_vae_var = tk.BooleanVar()
        self.fp8_unet_var = tk.BooleanVar()
        self.fp8_textenc_var = tk.BooleanVar()
        self.disable_cuda_malloc_var = tk.BooleanVar()
        self.vram_mode_var = tk.StringVar()

        self.config = {}

        # Initialize
        self.load_config()
        self.update_derived_paths()
        self.setup_styles()
        self.setup_ui()

        # Start background tasks
        self.root.after(UPDATE_INTERVAL_MS, self.process_output_queues)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Set initial UI state
        self._update_ui_state()

    # --- Configuration Handling ---
    def load_config(self):
        """Loads configuration from JSON file or uses defaults."""
        loaded_config = {}
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                print(f"Configuration loaded from {CONFIG_FILE}")
            else:
                print("Config file not found, using defaults...")
        except (json.JSONDecodeError, IOError, OSError) as e:
            print(f"Error loading config file '{CONFIG_FILE}': {e}. Using defaults.")
            loaded_config = {}

        self.config = {
            "comfyui_dir": loaded_config.get("comfyui_dir", DEFAULT_COMFYUI_INSTALL_DIR),
            "python_exe": loaded_config.get("python_exe", DEFAULT_COMFYUI_PORTABLE_PYTHON),
            "comfyui_api_port": loaded_config.get("comfyui_api_port", DEFAULT_COMFYUI_API_PORT),
            "fp16_vae": loaded_config.get("fp16_vae", DEFAULT_FP16_VAE),
            "fp8_unet": loaded_config.get("fp8_unet", DEFAULT_FP8_UNET),
            "fp8_textenc": loaded_config.get("fp8_textenc", DEFAULT_FP8_TEXTENC),
            "disable_cuda_malloc": loaded_config.get("disable_cuda_malloc", DEFAULT_DISABLE_CUDA_MALLOC),
            "vram_mode": loaded_config.get("vram_mode", DEFAULT_VRAM_MODE)
        }
        self.comfyui_dir_var.set(self.config.get("comfyui_dir"))
        self.python_exe_var.set(self.config.get("python_exe"))
        self.comfyui_api_port_var.set(self.config.get("comfyui_api_port"))
        self.fp16_vae_var.set(self.config.get("fp16_vae"))
        self.fp8_unet_var.set(self.config.get("fp8_unet"))
        self.fp8_textenc_var.set(self.config.get("fp8_textenc"))
        self.disable_cuda_malloc_var.set(self.config.get("disable_cuda_malloc"))
        vram_mode = self.config.get("vram_mode")
        valid_vram_modes = ["default", "high", "low"]
        if vram_mode not in valid_vram_modes:
            print(f"Warning: Invalid vram_mode '{vram_mode}' found in config. Resetting to 'default'.")
            vram_mode = "default"
            self.config["vram_mode"] = vram_mode
        self.vram_mode_var.set(vram_mode)
        if not os.path.exists(CONFIG_FILE) or not loaded_config:
            print("Attempting to save default configuration...")
            try: self.save_config_to_file(show_success=False)
            except Exception as e: print(f"Initial default config save failed: {e}")

    def save_settings(self):
        """Saves current settings from UI variables to the config dictionary and file."""
        print("--- Saving Settings ---")
        if self._is_comfyui_running() or self._is_flask_running():
             if not messagebox.askyesno("服务运行中 / Services Running", "部分服务当前正在运行。\n更改的设置需要重启服务才能生效。\n是否仍要保存？", parent=self.root):
                 return
        self.config["comfyui_dir"] = self.comfyui_dir_var.get()
        self.config["python_exe"] = self.python_exe_var.get()
        self.config["comfyui_api_port"] = self.comfyui_api_port_var.get()
        self.config["fp16_vae"] = self.fp16_vae_var.get()
        self.config["fp8_unet"] = self.fp8_unet_var.get()
        self.config["fp8_textenc"] = self.fp8_textenc_var.get()
        self.config["disable_cuda_malloc"] = self.disable_cuda_malloc_var.get()
        self.config["vram_mode"] = self.vram_mode_var.get()
        port_valid = True
        try:
            port_num = int(self.config["comfyui_api_port"])
            if not (1 <= port_num <= 65535): raise ValueError("Port out of range")
        except ValueError:
            port_valid = False; messagebox.showerror("端口错误 / Invalid Port", "后端 API 端口号必须是 1-65535 之间的数字。", parent=self.root)
        if port_valid:
             valid_vram_modes = ["default", "high", "low"]
             mode = self.config["vram_mode"]
             if mode not in valid_vram_modes:
                 messagebox.showwarning("设置警告 / Settings Warning", f"无效的 VRAM 优化模式 '{mode}'。将重置为 'default'。", parent=self.root)
                 self.config["vram_mode"] = "default"; self.vram_mode_var.set("default")
             self.save_config_to_file(show_success=True)
             self.update_derived_paths(); print("Settings saved and paths updated."); self._update_ui_state()

    def save_config_to_file(self, show_success=True):
        """Writes the self.config dictionary to the JSON file."""
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(self.config, f, indent=4, ensure_ascii=False)
            print(f"Configuration saved to {CONFIG_FILE}")
            if show_success and self.root and self.root.winfo_exists(): messagebox.showinfo("设置已保存 / Settings Saved", "配置已成功保存。", parent=self.root)
        except Exception as e:
            print(f"Error saving config file: {e}")
            if self.root and self.root.winfo_exists(): messagebox.showerror("配置保存错误 / Config Save Error", f"无法将配置保存到文件：\n{e}", parent=self.root)

    def update_derived_paths(self):
        """Updates internal path variables and base arguments based on current config."""
        self.base_project_dir = os.path.dirname(os.path.abspath(__file__))
        self.comfyui_install_dir = self.config.get("comfyui_dir", "")
        self.comfyui_portable_python = self.config.get("python_exe", "")
        self.venv_python_exe = os.path.join(self.base_project_dir, "venv", "Scripts", "python.exe")
        self.app_script = os.path.join(self.base_project_dir, "app.py")
        self.comfyui_main_script = os.path.join(self.comfyui_install_dir, "main.py") if self.comfyui_install_dir and os.path.isdir(self.comfyui_install_dir) else ""
        self.flask_working_dir = self.base_project_dir
        self.comfyui_api_port = self.config.get("comfyui_api_port", DEFAULT_COMFYUI_API_PORT)
        fixed_flask_port_for_cors = "5000"
        self.comfyui_base_args = [
            "--listen", "127.0.0.1", f"--port={self.comfyui_api_port}",
            f"--enable-cors-header=http://127.0.0.1:{fixed_flask_port_for_cors}",
            f"--enable-cors-header=http://localhost:{fixed_flask_port_for_cors}"
        ]
        print(f"--- Paths Updated ---")
        print(f" ComfyUI Port: {self.comfyui_api_port}")
        print(f" ComfyUI Base Args: {self.comfyui_base_args}")

    def browse_directory(self, var_to_set):
        """Opens a directory selection dialog."""
        directory = filedialog.askdirectory(title="选择目录 / Select Directory", parent=self.root)
        if directory: var_to_set.set(os.path.normpath(directory))

    def browse_file(self, var_to_set, filetypes):
        """Opens a file selection dialog."""
        filepath = filedialog.askopenfilename(title="选择文件 / Select File", filetypes=filetypes, parent=self.root)
        if filepath: var_to_set.set(os.path.normpath(filepath))

    # --- Styling Setup ---
    def setup_styles(self):
        """Configures the ttk styles for the application."""
        self.style = ttk.Style(self.root)
        try: self.style.theme_use('clam')
        except tk.TclError: print("Warning: 'clam' theme not available, using default theme.")
        neutral_button_bg="#555555"; neutral_button_fg=FG_COLOR; n_active_bg="#6e6e6e"; n_pressed_bg="#7f7f7f"; n_disabled_bg="#4a5a6a"; n_disabled_fg=FG_MUTED
        self.style.configure('.', background=BG_COLOR, foreground=FG_COLOR, font=(FONT_FAMILY_UI, FONT_SIZE_NORMAL), bordercolor=BORDER_COLOR); self.style.map('.', background=[('active', '#4f4f4f'), ('disabled', '#404040')], foreground=[('disabled', FG_MUTED)])
        self.style.configure('TFrame', background=BG_COLOR); self.style.configure('Control.TFrame', background=CONTROL_FRAME_BG); self.style.configure('TabControl.TFrame', background=TAB_CONTROL_FRAME_BG); self.style.configure('Settings.TFrame', background=BG_COLOR); self.style.configure('TLabelframe', background=BG_COLOR, foreground=FG_COLOR, bordercolor=BORDER_COLOR, relief=tk.GROOVE); self.style.configure('TLabelframe.Label', background=BG_COLOR, foreground=FG_COLOR, font=(FONT_FAMILY_UI, FONT_SIZE_NORMAL, 'italic'))
        self.style.configure('TLabel', background=BG_COLOR, foreground=FG_COLOR); self.style.configure('Status.TLabel', background=CONTROL_FRAME_BG, foreground=FG_MUTED, padding=(5, 3)); self.style.configure('Version.TLabel', background=BG_COLOR, foreground=FG_MUTED, font=(FONT_FAMILY_UI, FONT_SIZE_NORMAL - 1)); self.style.configure('Hint.TLabel', background=BG_COLOR, foreground=FG_MUTED, font=(FONT_FAMILY_UI, FONT_SIZE_NORMAL - 1))
        main_pady=(10, 6); main_fnt=(FONT_FAMILY_UI, FONT_SIZE_NORMAL); main_fnt_bld=(FONT_FAMILY_UI, FONT_SIZE_NORMAL, FONT_WEIGHT_BOLD)
        self.style.configure('TButton', padding=main_pady, anchor=tk.CENTER, font=main_fnt, borderwidth=0, relief=tk.FLAT, background=neutral_button_bg, foreground=neutral_button_fg); self.style.map('TButton', background=[('active', n_active_bg), ('pressed', n_pressed_bg), ('disabled', n_disabled_bg)], foreground=[('disabled', n_disabled_fg)])
        self.style.configure("Accent.TButton", padding=main_pady, font=main_fnt_bld, background=ACCENT_COLOR, foreground="white"); self.style.map("Accent.TButton", background=[('pressed', ACCENT_ACTIVE), ('active', '#006ae0'), ('disabled', n_disabled_bg)], foreground=[('disabled', n_disabled_fg)])
        self.style.configure("Stop.TButton", padding=main_pady, font=main_fnt, background=STOP_COLOR, foreground=FG_COLOR); self.style.map("Stop.TButton", background=[('pressed', STOP_ACTIVE), ('active', '#6e6e6e'), ('disabled', n_disabled_bg)], foreground=[('disabled', n_disabled_fg)])
        self.style.configure("StopRunning.TButton", padding=main_pady, font=main_fnt, background=STOP_RUNNING_BG, foreground=STOP_RUNNING_FG); self.style.map("StopRunning.TButton", background=[('pressed', STOP_RUNNING_ACTIVE_BG), ('active', STOP_RUNNING_ACTIVE_BG), ('disabled', n_disabled_bg)], foreground=[('disabled', n_disabled_fg)])
        tab_pady=(6, 4); tab_fnt=(FONT_FAMILY_UI, FONT_SIZE_NORMAL - 1); tab_neutral_bg=neutral_button_bg; tab_n_active_bg=n_active_bg; tab_n_pressed_bg=n_pressed_bg
        self.style.configure("TabAccent.TButton", padding=tab_pady, font=tab_fnt, background=tab_neutral_bg, foreground=neutral_button_fg); self.style.map("TabAccent.TButton", background=[('pressed', tab_n_pressed_bg), ('active', tab_n_active_bg), ('disabled', n_disabled_bg)], foreground=[('disabled', n_disabled_fg)])
        self.style.configure("TabStop.TButton", padding=tab_pady, font=tab_fnt, background=tab_neutral_bg, foreground=neutral_button_fg); self.style.map("TabStop.TButton", background=[('pressed', tab_n_pressed_bg), ('active', tab_n_active_bg), ('disabled', n_disabled_bg)], foreground=[('disabled', n_disabled_fg)])
        self.style.configure("TabStopRunning.TButton", padding=tab_pady, font=tab_fnt, background=tab_neutral_bg, foreground=neutral_button_fg); self.style.map("TabStopRunning.TButton", background=[('pressed', tab_n_pressed_bg), ('active', tab_n_active_bg), ('disabled', n_disabled_bg)], foreground=[('disabled', n_disabled_fg)])
        self.style.configure('TCheckbutton', background=BG_COLOR, foreground=FG_COLOR, font=main_fnt); self.style.map('TCheckbutton', background=[('active', BG_COLOR)], indicatorcolor=[('selected', ACCENT_COLOR), ('pressed', ACCENT_ACTIVE), ('!selected', FG_MUTED)], foreground=[('disabled', FG_MUTED)])
        self.style.configure('TCombobox', fieldbackground=TEXT_AREA_BG, background=TEXT_AREA_BG, foreground=FG_COLOR, arrowcolor=FG_COLOR, bordercolor=BORDER_COLOR, insertcolor=FG_COLOR, padding=(5, 4), font=main_fnt); self.style.map('TCombobox', fieldbackground=[('readonly', TEXT_AREA_BG), ('disabled', CONTROL_FRAME_BG)], foreground=[('disabled', FG_MUTED), ('readonly', FG_COLOR)], arrowcolor=[('disabled', FG_MUTED)], selectbackground=[('!focus', ACCENT_COLOR), ('focus', ACCENT_ACTIVE)], selectforeground=[('!focus', 'white'), ('focus', 'white')])
        try:
            self.root.option_add('*TCombobox*Listbox.background', TEXT_AREA_BG); self.root.option_add('*TCombobox*Listbox.foreground', FG_COLOR); self.root.option_add('*TCombobox*Listbox.selectBackground', ACCENT_ACTIVE); self.root.option_add('*TCombobox*Listbox.selectForeground', 'white'); self.root.option_add('*TCombobox*Listbox.font', (FONT_FAMILY_UI, FONT_SIZE_NORMAL)); self.root.option_add('*TCombobox*Listbox.borderWidth', 1); self.root.option_add('*TCombobox*Listbox.relief', 'solid')
        except tk.TclError as e: print(f"Warning: Could not set Combobox Listbox styles: {e}")
        self.style.configure('TNotebook', background=BG_COLOR, borderwidth=0, tabmargins=[5, 5, 5, 0]); self.style.configure('TNotebook.Tab', padding=[15, 8], background=BG_COLOR, foreground=FG_MUTED, font=(FONT_FAMILY_UI, FONT_SIZE_NORMAL), borderwidth=0); self.style.map('TNotebook.Tab', background=[('selected', '#4a4a4a'), ('active', '#3a3a3a')], foreground=[('selected', 'white'), ('active', FG_COLOR)], focuscolor=self.style.lookup('TNotebook.Tab', 'background'))
        self.style.configure('Horizontal.TProgressbar', thickness=6, background=ACCENT_COLOR, troughcolor=CONTROL_FRAME_BG, borderwidth=0)
        self.style.configure('TEntry', fieldbackground=TEXT_AREA_BG, foreground=FG_COLOR, insertcolor='white', bordercolor=BORDER_COLOR, borderwidth=1, padding=(5,4)); self.style.map('TEntry', fieldbackground=[('focus', TEXT_AREA_BG)], bordercolor=[('focus', ACCENT_COLOR)], lightcolor=[('focus', ACCENT_COLOR)])

    # --- UI Setup ---
    def setup_ui(self):
        """Builds the main UI structure."""
        # Top Control Frame
        control_frame = ttk.Frame(self.root, padding=(10, 10, 10, 5), style='Control.TFrame'); control_frame.grid(row=0, column=0, sticky="ew"); control_frame.columnconfigure(1, weight=1)
        self.status_label = ttk.Label(control_frame, text="状态: 未知", style='Status.TLabel', anchor=tk.W); self.status_label.grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Label(control_frame, text="", style='Status.TLabel').grid(row=0, column=1, sticky="ew") # Spacer
        self.progress_bar = ttk.Progressbar(control_frame, mode='indeterminate', length=350, style='Horizontal.TProgressbar'); self.progress_bar.grid(row=0, column=2, padx=10); self.progress_bar.stop()
        self.stop_all_button = ttk.Button(control_frame, text="停止", command=self.stop_all_services, style="Stop.TButton", width=12); self.stop_all_button.grid(row=0, column=3, padx=(0, 5))
        self.run_all_button = ttk.Button(control_frame, text="运行", command=self.start_all_services_thread, style="Accent.TButton", width=12); self.run_all_button.grid(row=0, column=4, padx=(0, 0))

        # Main Notebook
        self.notebook = ttk.Notebook(self.root, style='TNotebook'); self.notebook.grid(row=1, column=0, sticky="nsew", padx=5, pady=(0, 5)); self.notebook.enable_traversal()

        # --- Settings Tab ---
        self.settings_frame = ttk.Frame(self.notebook, padding="15", style='Settings.TFrame'); self.settings_frame.columnconfigure(0, weight=1); self.notebook.add(self.settings_frame, text=' 设置 / Settings ')
        current_row = 0; frame_padx = 5; frame_pady = (0, 10); widget_pady = (3, 3); widget_padx = 5; label_min_width = 25 # Adjusted label width
        # Basic Settings Group
        basic_group = ttk.LabelFrame(self.settings_frame, text=" 基本路径与端口 ", padding=(10, 5)); basic_group.grid(row=current_row, column=0, sticky="ew", padx=frame_padx, pady=frame_pady); basic_group.columnconfigure(1, weight=1); basic_row = 0
        ttk.Label(basic_group, text="ComfyUI 安装目录:", width=label_min_width, anchor=tk.W).grid(row=basic_row, column=0, sticky=tk.W, pady=widget_pady, padx=widget_padx); dir_entry = ttk.Entry(basic_group, textvariable=self.comfyui_dir_var); dir_entry.grid(row=basic_row, column=1, sticky="ew", pady=widget_pady, padx=widget_padx); dir_btn = ttk.Button(basic_group, text="浏览", width=8, command=lambda: self.browse_directory(self.comfyui_dir_var), style='TButton'); dir_btn.grid(row=basic_row, column=2, sticky=tk.E, pady=widget_pady, padx=(0, widget_padx)); basic_row += 1
        ttk.Label(basic_group, text="ComfyUI Python 路径:", width=label_min_width, anchor=tk.W).grid(row=basic_row, column=0, sticky=tk.W, pady=widget_pady, padx=widget_padx); py_entry = ttk.Entry(basic_group, textvariable=self.python_exe_var); py_entry.grid(row=basic_row, column=1, sticky="ew", pady=widget_pady, padx=widget_padx); py_btn = ttk.Button(basic_group, text="浏览", width=8, command=lambda: self.browse_file(self.python_exe_var, [("Python Executable", "python.exe"), ("All Files", "*.*")]), style='TButton'); py_btn.grid(row=basic_row, column=2, sticky=tk.E, pady=widget_pady, padx=(0, widget_padx)); basic_row += 1
        ttk.Label(basic_group, text="ComfyUI API 端口:", width=label_min_width, anchor=tk.W).grid(row=basic_row, column=0, sticky=tk.W, pady=widget_pady, padx=widget_padx); comfyui_port_entry = ttk.Entry(basic_group, textvariable=self.comfyui_api_port_var, width=10); comfyui_port_entry.grid(row=basic_row, column=1, sticky=tk.W, pady=widget_pady, padx=widget_padx); current_row += 1
        # Performance Group
        perf_group = ttk.LabelFrame(self.settings_frame, text=" 性能与显存优化 ", padding=(10, 5)); perf_group.grid(row=current_row, column=0, sticky="ew", padx=frame_padx, pady=frame_pady); perf_row = 0
        ttk.Label(perf_group, text="显存优化模式:", width=label_min_width, anchor=tk.W).grid(row=perf_row, column=0, sticky=tk.W, pady=widget_pady, padx=widget_padx); vram_mode_combo = ttk.Combobox(perf_group, textvariable=self.vram_mode_var, values=["default", "high", "low"], state="readonly", width=15); vram_mode_combo.grid(row=perf_row, column=1, sticky=tk.W, pady=widget_pady, padx=widget_padx); perf_row += 1
        fp16_vae_check = ttk.Checkbutton(perf_group, text="启用 VAE 半精度 (--fp16-vae)", variable=self.fp16_vae_var); fp16_vae_check.grid(row=perf_row, column=0, columnspan=3, sticky=tk.W, pady=widget_pady, padx=widget_padx); perf_row += 1
        fp8_unet_check = ttk.Checkbutton(perf_group, text="启用 UNet FP8 (实验性, 需新GPU)", variable=self.fp8_unet_var); fp8_unet_check.grid(row=perf_row, column=0, columnspan=3, sticky=tk.W, pady=widget_pady, padx=widget_padx); perf_row += 1
        fp8_textenc_check = ttk.Checkbutton(perf_group, text="启用 Text Encoder FP8 (实验性, 需新GPU)", variable=self.fp8_textenc_var); fp8_textenc_check.grid(row=perf_row, column=0, columnspan=3, sticky=tk.W, pady=widget_pady, padx=widget_padx); perf_row += 1
        disable_cuda_check = ttk.Checkbutton(perf_group, text="禁用 CUDA 内存分配器 (调试)", variable=self.disable_cuda_malloc_var); disable_cuda_check.grid(row=perf_row, column=0, columnspan=3, sticky=tk.W, pady=widget_pady, padx=widget_padx); current_row += 1
        # Spacer and Bottom Row
        self.settings_frame.rowconfigure(current_row, weight=1); current_row += 1
        bottom_frame = ttk.Frame(self.settings_frame, style='Settings.TFrame'); bottom_frame.grid(row=current_row, column=0, sticky="sew", pady=(15, 0)); bottom_frame.columnconfigure(1, weight=1)
        save_btn = ttk.Button(bottom_frame, text="保存设置", style="TButton", command=self.save_settings); save_btn.grid(row=0, column=0, sticky="sw", padx=(frame_padx, 0))
        version_label = ttk.Label(bottom_frame, text=VERSION_INFO, style="Version.TLabel"); version_label.grid(row=0, column=2, sticky="se", padx=(0, frame_padx))
        # Output Tabs
        self.app_frame = ttk.Frame(self.notebook, style='TFrame', padding=0); self.notebook.add(self.app_frame, text=' 前端_网页 / Frontend '); self.app_frame.columnconfigure(0, weight=1); self.app_frame.rowconfigure(1, weight=1)
        flask_control_frame = ttk.Frame(self.app_frame, style='TabControl.TFrame', padding=(5, 5)); flask_control_frame.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        self.flask_run_button = ttk.Button(flask_control_frame, text="运行前端", style="TabAccent.TButton", command=self.start_flask_service_thread); self.flask_run_button.pack(side=tk.LEFT, padx=5)
        self.flask_stop_button = ttk.Button(flask_control_frame, text="停止前端", style="TabStop.TButton", command=self._stop_flask_service); self.flask_stop_button.pack(side=tk.LEFT, padx=5)
        self.app_output_text = scrolledtext.ScrolledText(self.app_frame, wrap=tk.WORD, state=tk.DISABLED, font=(FONT_FAMILY_MONO, FONT_SIZE_MONO), bg=TEXT_AREA_BG, fg=FG_STDOUT, relief=tk.FLAT, borderwidth=1, bd=1, highlightthickness=1, highlightbackground=BORDER_COLOR, insertbackground="white"); self.app_output_text.grid(row=1, column=0, sticky="nsew", padx=1, pady=1); self.setup_text_tags(self.app_output_text)
        self.main_frame = ttk.Frame(self.notebook, style='TFrame', padding=0); self.notebook.add(self.main_frame, text=' 后端_ComfyUI / Backend '); self.main_frame.columnconfigure(0, weight=1); self.main_frame.rowconfigure(1, weight=1)
        comfy_control_frame = ttk.Frame(self.main_frame, style='TabControl.TFrame', padding=(5, 5)); comfy_control_frame.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        self.comfy_run_button = ttk.Button(comfy_control_frame, text="运行后端", style="TabAccent.TButton", command=self.start_comfyui_service_thread); self.comfy_run_button.pack(side=tk.LEFT, padx=5)
        self.comfy_stop_button = ttk.Button(comfy_control_frame, text="停止后端", style="TabStop.TButton", command=self._stop_comfyui_service); self.comfy_stop_button.pack(side=tk.LEFT, padx=5)
        self.main_output_text = scrolledtext.ScrolledText(self.main_frame, wrap=tk.WORD, state=tk.DISABLED, font=(FONT_FAMILY_MONO, FONT_SIZE_MONO), bg=TEXT_AREA_BG, fg=FG_STDOUT, relief=tk.FLAT, borderwidth=1, bd=1, highlightthickness=1, highlightbackground=BORDER_COLOR, insertbackground="white"); self.main_output_text.grid(row=1, column=0, sticky="nsew", padx=1, pady=1); self.setup_text_tags(self.main_output_text)
        self.notebook.select(self.settings_frame)

    # --- Text/Output Methods ---
    def setup_text_tags(self, text_widget): text_widget.tag_config("stdout", foreground=FG_STDOUT); text_widget.tag_config("stderr", foreground=FG_STDERR); text_widget.tag_config("info", foreground=FG_INFO, font=(FONT_FAMILY_MONO, FONT_SIZE_MONO, 'italic')); text_widget.tag_config("warn", foreground="#ffd700")
    def insert_output(self, text_widget, line, source_tag="stdout"):
        if not text_widget or not text_widget.winfo_exists(): return
        text_widget.config(state=tk.NORMAL); tag = "stdout"
        if "[Launcher]" in source_tag: tag = "info"
        elif "ERR" in source_tag.upper() or "ERROR" in line.upper() or "Traceback" in line or "Failed" in line: tag = "stderr"
        elif "WARN" in source_tag.upper() or "WARNING" in line.upper(): tag = "warn"
        text_widget.insert(tk.END, line, (tag,));
        if text_widget.yview()[1] > 0.95: text_widget.see(tk.END)
        text_widget.config(state=tk.DISABLED)
    def log_to_gui(self, target, message, tag="info"): queue = self.comfyui_output_queue if target == "ComfyUI" else self.flask_output_queue; queue.put((f"[Launcher {tag.upper()}]", message))
    def process_output_queues(self):
        processed_comfy = 0; processed_flask = 0; max_lines = 50
        try:
            while not self.comfyui_output_queue.empty() and processed_comfy < max_lines:
                source, line = self.comfyui_output_queue.get_nowait()
                if line.strip() == _COMFYUI_READY_MARKER_.strip(): self._trigger_backend_browser_opening()
                else: self.insert_output(self.main_output_text, line, source)
                processed_comfy += 1
        except queue.Empty: pass
        except Exception as e: print(f"Error processing ComfyUI queue: {e}")
        try:
            while not self.flask_output_queue.empty() and processed_flask < max_lines:
                source, line = self.flask_output_queue.get_nowait()
                self.insert_output(self.app_output_text, line, source)
                processed_flask += 1
        except queue.Empty: pass
        except Exception as e: print(f"Error processing Flask queue: {e}")
        self.root.after(UPDATE_INTERVAL_MS, self.process_output_queues)

    def stream_output(self, process_stream, output_queue, stream_name):
        marker_sent = False; api_port = self.config.get("comfyui_api_port", DEFAULT_COMFYUI_API_PORT)
        ready_str1 = f"Set up connection listening on: ::{api_port}"; ready_str2 = f"To see the GUI go to: http://127.0.0.1:{api_port}"
        try:
            for line_bytes in iter(process_stream.readline, b''):
                if self.stop_event.is_set(): break
                line = line_bytes.decode('utf-8', errors='replace')
                if line:
                    output_queue.put((stream_name, line))
                    if stream_name == "[ComfyUI]" and not marker_sent and (ready_str1 in line or ready_str2 in line):
                        print(f"DEBUG STREAM: Found ComfyUI ready string. Queuing marker."); output_queue.put((stream_name, _COMFYUI_READY_MARKER_)); marker_sent = True; self.comfyui_ready_marker_sent = True
        except ValueError: print(f"{stream_name} stream closed (ValueError).")
        except Exception as e: print(f"Error reading {stream_name}: {e}")
        finally:
            print(f"{stream_name} stream reader thread finished.")
            try: process_stream.close()
            except Exception: pass

    # --- Service Management ---
    def _is_comfyui_running(self): return self.comfyui_process and self.comfyui_process.poll() is None
    def _is_flask_running(self): return self.flask_process and self.flask_process.poll() is None
    def _validate_paths_for_execution(self, check_comfyui=True, check_flask=True, show_error=True):
        paths_ok = True; missing = []
        if check_comfyui:
            if not self.comfyui_portable_python or not os.path.isfile(self.comfyui_portable_python): missing.append(f"后端 Python"); paths_ok = False
            if not self.comfyui_main_script or not os.path.isfile(self.comfyui_main_script): missing.append(f"后端主脚本"); paths_ok = False
            if not self.comfyui_install_dir or not os.path.isdir(self.comfyui_install_dir): missing.append(f"后端 ComfyUI 目录"); paths_ok = False
        if check_flask:
            if not self.venv_python_exe or not os.path.isfile(self.venv_python_exe): missing.append(f"前端 Venv Python"); paths_ok = False
            if not self.app_script or not os.path.isfile(self.app_script): missing.append(f"前端 App 脚本"); paths_ok = False
        if not paths_ok and show_error: messagebox.showerror("路径错误", "缺少以下文件或目录：\n" + "\n".join(missing) + "\n\n请检查设置。", parent=self.root)
        return paths_ok

    def start_comfyui_service_thread(self):
        if self._is_comfyui_running(): self.log_to_gui("ComfyUI", "后端已在运行", "warn"); return
        # No need to validate flask paths here / 此处无需验证 flask 路径
        if not self._validate_paths_for_execution(check_comfyui=True, check_flask=False): return
        self.stop_event.clear()
        # Reset external detection flag on new start attempt / 在新的启动尝试中重置外部检测标志
        self.comfyui_externally_detected = False
        if hasattr(self, 'comfy_run_button'): self.comfy_run_button.config(state=tk.DISABLED)
        self.progress_bar.start(10); self.status_label.config(text="状态: 启动后端..."); self.notebook.select(self.main_frame)
        thread = threading.Thread(target=self._start_comfyui_service, daemon=True); thread.start()

    # --- MODIFIED: Added port check before launching ---
    # --- 修改：在启动前添加端口检查 ---
    def _start_comfyui_service(self):
        if self._is_comfyui_running(): return # Already managed by this launcher / 已由此启动器管理

        # --- Check if ComfyUI API is already running on the configured port ---
        # --- 检查 ComfyUI API 是否已在配置的端口上运行 ---
        port_to_check = int(self.config.get("comfyui_api_port", DEFAULT_COMFYUI_API_PORT))
        check_url = f"http://127.0.0.1:{port_to_check}/queue" # Use a lightweight endpoint / 使用轻量级端点
        is_already_running = False
        try:
            print(f"Checking if ComfyUI is running on {check_url} before launch...")
            response = requests.get(check_url, timeout=2) # Short timeout / 短超时
            if response.status_code == 200:
                is_already_running = True
                self.log_to_gui("ComfyUI", f"检测到 ComfyUI 已在端口 {port_to_check} 运行，跳过启动。", "info")
                print(f"ComfyUI detected running on port {port_to_check}. Skipping launch.")
                self.comfyui_externally_detected = True # Set the flag / 设置标志
                # Update UI immediately to reflect this state / 立即更新 UI 以反映此状态
                self.root.after(0, self._update_ui_state)
                # Explicitly set comfyui_process to None as we are not managing it
                # 显式将 comfyui_process 设置为 None，因为我们不管理它
                self.comfyui_process = None
                return # Exit the function, do not proceed with Popen / 退出函数，不继续执行 Popen
            else:
                # Received a response, but not 200 OK (unexpected) / 收到响应，但不是 200 OK（意外）
                 print(f"Port check received unexpected status {response.status_code}. Proceeding with launch.")
        except requests.exceptions.Timeout:
            print(f"Port check timed out. Port {port_to_check} likely free. Proceeding with launch.")
            # Port is likely free / 端口可能空闲
            pass
        except requests.exceptions.ConnectionError:
            print(f"Port check connection refused. Port {port_to_check} likely free. Proceeding with launch.")
            # Port is likely free / 端口可能空闲
            pass
        except Exception as e:
            print(f"Port check failed unexpectedly: {e}. Proceeding with launch.")
            # Other errors, proceed cautiously / 其他错误，谨慎进行
            pass
        # --- End Port Check ---

        # If we reached here, the port check did not detect a running ComfyUI
        # 如果我们到达这里，端口检查未检测到正在运行的 ComfyUI
        self.backend_browser_triggered_for_session = False
        self.comfyui_ready_marker_sent = False
        self.comfyui_externally_detected = False # Ensure flag is false if we launch / 确保如果我们启动，标志为 false

        try:
            self.log_to_gui("ComfyUI", f"启动 Backend_ComfyUI 于 {self.comfyui_install_dir}...")
            base_cmd = [self.comfyui_portable_python, "-s", "-u", self.comfyui_main_script]; current_args = list(self.comfyui_base_args)
            if self.fp16_vae_var.get(): current_args.append("--fp16-vae")
            if self.fp8_unet_var.get(): current_args.append("--fp8_e4m3fn-unet")
            if self.fp8_textenc_var.get(): current_args.append("--fp8_e4m3fn-text-enc")
            if self.disable_cuda_malloc_var.get(): current_args.append("--disable-cuda-malloc")
            vram_mode = self.vram_mode_var.get()
            if vram_mode == "high": current_args.append("--highvram")
            elif vram_mode == "low": current_args.append("--lowvram")
            comfyui_cmd_list = base_cmd + current_args
            self.log_to_gui("ComfyUI", f"最终参数: {' '.join(current_args)}")
            self.log_to_gui("ComfyUI", f"完整命令: {' '.join(comfyui_cmd_list)}")
            creationflags = 0; startupinfo = None
            if os.name == 'nt': creationflags = subprocess.CREATE_NO_WINDOW
            self.comfyui_process = subprocess.Popen(comfyui_cmd_list, cwd=self.comfyui_install_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, creationflags=creationflags, startupinfo=startupinfo)
            self.log_to_gui("ComfyUI", f"Backend PID: {self.comfyui_process.pid}")
            self.comfyui_reader_thread_stdout = threading.Thread(target=self.stream_output, args=(self.comfyui_process.stdout, self.comfyui_output_queue, "[ComfyUI]"), daemon=True); self.comfyui_reader_thread_stdout.start()
            self.comfyui_reader_thread_stderr = threading.Thread(target=self.stream_output, args=(self.comfyui_process.stderr, self.comfyui_output_queue, "[ComfyUI ERR]"), daemon=True); self.comfyui_reader_thread_stderr.start()
            time.sleep(2) # Give process time to potentially fail early / 给进程时间可能提前失败
            if not self._is_comfyui_running():
                # Check again if it failed immediately / 再次检查是否立即失败
                exit_code = self.comfyui_process.poll() if self.comfyui_process else 'N/A'
                # Check if the reason might be port conflict (common issue) / 检查原因是否可能是端口冲突（常见问题）
                error_reason = f"后端进程意外终止，代码 {exit_code}。"
                if port_to_check and exit_code: # Simplified check for common exit codes on port conflict / 简化对端口冲突常见退出代码的检查
                     error_reason += f"\n可能原因：端口 {port_to_check} 已被占用？\nPossible reason: Port {port_to_check} already in use?"
                raise Exception(error_reason)
            self.log_to_gui("ComfyUI", "后端服务已启动"); self.root.after(0, self._update_ui_state)
        except Exception as e:
            error_msg = f"启动 Backend 失败: {e}"
            print(error_msg)
            self.log_to_gui("ComfyUI", error_msg, "stderr")
            # Schedule error message display / 安排错误消息显示
            self.root.after(0, lambda msg=str(e): messagebox.showerror("后端错误", f"启动 Backend 失败:\n{msg}", parent=self.root))
            self.comfyui_process = None # Ensure process is None on failure / 确保失败时进程为 None
            self.root.after(0, self.reset_ui_on_error) # Reset UI state / 重置 UI 状态


    def _stop_comfyui_service(self):
        # Reset external detection flag when stopping / 停止时重置外部检测标志
        self.comfyui_externally_detected = False
        if not self._is_comfyui_running():
            self.log_to_gui("ComfyUI", "后端未由此启动器管理或未运行", "warn")
            self._update_ui_state()
            return
        self.log_to_gui("ComfyUI", "停止 Backend_ComfyUI...")
        if hasattr(self, 'comfy_stop_button'): self.comfy_stop_button.config(state=tk.DISABLED)
        self.status_label.config(text="状态: 停止后端..."); self.progress_bar.start(10)
        try:
            self.stop_event.set(); time.sleep(0.1); self.comfyui_process.terminate()
            try: self.comfyui_process.wait(timeout=3); self.log_to_gui("ComfyUI", "后端已终止")
            except subprocess.TimeoutExpired: print("Killing ComfyUI"); self.log_to_gui("ComfyUI", "强制终止后端...", "warn"); self.comfyui_process.kill(); self.log_to_gui("ComfyUI", "后端已强制终止")
        except Exception as e: error_msg = f"停止后端出错: {e}"; print(error_msg); self.log_to_gui("ComfyUI", error_msg, "stderr")
        finally: self.comfyui_process = None; self.stop_event.clear(); self.backend_browser_triggered_for_session = False; self.comfyui_ready_marker_sent = False; self.root.after(0, self._update_ui_state)

    def start_flask_service_thread(self):
        if self._is_flask_running(): self.log_to_gui("Flask", "前端已在运行", "warn"); return
        if not self._validate_paths_for_execution(check_comfyui=False, check_flask=True): return

        # --- MODIFIED: Check external ComfyUI state as well ---
        # --- 修改：同时检查外部 ComfyUI 状态 ---
        comfy_running_internally = self._is_comfyui_running()
        comfy_detected_externally = self.comfyui_externally_detected

        if not comfy_running_internally and not comfy_detected_externally:
            self.log_to_gui("Flask", "后端未运行，尝试启动...")
            self.start_comfyui_service_thread() # This now handles external detection / 现在处理外部检测
            self.log_to_gui("Flask", "等待后端就绪(10s)...")
            self.root.after(10000, self._proceed_with_flask_start)
        else:
             if comfy_detected_externally:
                 self.log_to_gui("Flask", "检测到外部 ComfyUI，尝试启动前端...")
             else: # Must be running internally
                 self.log_to_gui("Flask", "内部 ComfyUI 运行中，启动前端...")
             self._proceed_with_flask_start()

    def _proceed_with_flask_start(self):
        # --- MODIFIED: Check external ComfyUI state again ---
        # --- 修改：再次检查外部 ComfyUI 状态 ---
        if not self._is_comfyui_running() and not self.comfyui_externally_detected:
             self.log_to_gui("Flask", "无法启动或检测到后端服务，前端中止", "stderr")
             messagebox.showerror("依赖错误 / Dependency Error", "无法启动或检测到 ComfyUI 后端服务，前端无法启动。\nCould not start or detect ComfyUI backend service, frontend cannot start.", parent=self.root)
             self.root.after(0, self._update_ui_state)
             return

        if self._is_flask_running(): self.log_to_gui("Flask", "前端似乎已启动", "warn"); return
        self.log_to_gui("Flask", "后端就绪，启动前端...")
        if hasattr(self, 'flask_run_button'): self.flask_run_button.config(state=tk.DISABLED)
        self.progress_bar.start(10); self.status_label.config(text="状态: 启动前端..."); self.notebook.select(self.app_frame)
        thread = threading.Thread(target=self._start_flask_service, daemon=True)
        thread.start()

    def _start_flask_service(self):
        if self._is_flask_running(): return
        try:
            self.log_to_gui("Flask", f"启动 Frontend_Web 于 {self.flask_working_dir}...")
            flask_cmd_list = [self.venv_python_exe, "-u", self.app_script]
            self.log_to_gui("Flask", f"命令: {' '.join(flask_cmd_list)}")
            creationflags = 0; startupinfo = None
            if os.name == 'nt': creationflags = subprocess.CREATE_NO_WINDOW
            flask_env = os.environ.copy()
            flask_env['COMFYUI_HOST'] = "127.0.0.1" # Flask connects to localhost
            flask_env['COMFYUI_API_PORT'] = self.comfyui_api_port
            self.flask_process = subprocess.Popen( flask_cmd_list, cwd=self.flask_working_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, creationflags=creationflags, startupinfo=startupinfo, env=flask_env )
            self.log_to_gui("Flask", f"Frontend PID: {self.flask_process.pid}")
            self.flask_reader_thread_stdout = threading.Thread(target=self.stream_output, args=(self.flask_process.stdout, self.flask_output_queue, "[Flask]"), daemon=True); self.flask_reader_thread_stdout.start()
            self.flask_reader_thread_stderr = threading.Thread(target=self.stream_output, args=(self.flask_process.stderr, self.flask_output_queue, "[Flask ERR]"), daemon=True); self.flask_reader_thread_stderr.start()
            time.sleep(2)
            if not self._is_flask_running(): exit_code = self.flask_process.poll() if self.flask_process else 'N/A'; raise Exception(f"前端进程意外终止，代码 {exit_code}。")
            self.log_to_gui("Flask", "前端服务已启动"); self.root.after(1000, self._open_frontend_browser); self.root.after(0, self._update_ui_state)
        except Exception as e: error_msg = f"启动 Frontend 失败: {e}"; print(error_msg); self.log_to_gui("Flask", error_msg, "stderr"); self.root.after(0, lambda: messagebox.showerror("前端错误", error_msg, parent=self.root)); self.flask_process = None; self.root.after(0, self.reset_ui_on_error)

    def _stop_flask_service(self):
        if not self._is_flask_running(): self.log_to_gui("Flask", "前端未运行", "warn"); self._update_ui_state(); return
        self.log_to_gui("Flask", "停止 Frontend_Web...")
        if hasattr(self, 'flask_stop_button'): self.flask_stop_button.config(state=tk.DISABLED)
        self.status_label.config(text="状态: 停止前端..."); self.progress_bar.start(10)
        try:
            self.stop_event.set(); time.sleep(0.1); self.flask_process.terminate()
            try: self.flask_process.wait(timeout=2); self.log_to_gui("Flask", "前端已终止")
            except subprocess.TimeoutExpired: print("Killing Flask"); self.log_to_gui("Flask", "强制终止前端...", "warn"); self.flask_process.kill(); self.log_to_gui("Flask", "前端已强制终止")
        except Exception as e: error_msg = f"停止前端出错: {e}"; print(error_msg); self.log_to_gui("Flask", error_msg, "stderr")
        finally: self.flask_process = None; self.stop_event.clear(); self.root.after(0, self._update_ui_state)

    def start_all_services_thread(self):
        # Check external state as well / 同时检查外部状态
        if (self._is_comfyui_running() or self.comfyui_externally_detected) and self._is_flask_running():
            messagebox.showinfo("服务已运行", "所有必需的服务已在运行或已被检测到。", parent=self.root); return
        # Validation needs to check ComfyUI paths even if starting externally detected / 即使启动外部检测到的 ComfyUI，验证也需要检查其路径
        if not self._validate_paths_for_execution(check_comfyui=True, check_flask=True): return
        if hasattr(self, 'run_all_button'): self.run_all_button.config(state=tk.DISABLED)
        self.progress_bar.start(10); self.status_label.config(text="状态: 启动所有服务..."); self.clear_output_widgets(); self.notebook.select(self.main_frame)
        thread = threading.Thread(target=self._run_all_services, daemon=True); thread.start()

    def _run_all_services(self):
        comfy_started = False # Tracks if ComfyUI is running (internally or externally) / 跟踪 ComfyUI 是否正在运行（内部或外部）
        flask_started = False

        # --- Start/Check ComfyUI Section ---
        if not self._is_comfyui_running() and not self.comfyui_externally_detected:
            self._start_comfyui_service() # This now includes the external check / 现在包括外部检查
            # If external was detected inside _start_..., comfyui_externally_detected will be True
            # 如果在 _start_... 内部检测到外部，comfyui_externally_detected 将为 True
            if self.comfyui_externally_detected:
                comfy_started = True # Mark as started (externally) / 标记为已启动（外部）
            else:
                # If not external, wait and check if internal process started
                # 如果不是外部的，等待并检查内部进程是否已启动
                time.sleep(10)
                if self._is_comfyui_running():
                    comfy_started = True
                else:
                    self.log_to_gui("ComfyUI", "启动后端失败，中止启动", "stderr")
                    self.root.after(0, self.reset_ui_on_error)
                    return
        else:
             # Already running (internally or externally detected before clicking 'Run All')
             # 已在运行（内部或在点击“全部运行”之前检测到外部）
            self.log_to_gui("ComfyUI", "后端已运行或已被检测到，跳过")
            comfy_started = True

        # --- Start Flask Section ---
        if comfy_started and not self._is_flask_running():
            self._start_flask_service()
            time.sleep(3)
            if self._is_flask_running():
                flask_started = True
            else:
                self.log_to_gui("Flask", "启动前端失败", "stderr")
                self.root.after(0, self.reset_ui_on_error)
                return
        elif comfy_started and self._is_flask_running():
            self.log_to_gui("Flask", "前端已运行，跳过")
            flask_started = True

        self.root.after(0, self._update_ui_state)

    def stop_all_services(self):
        """Stops both ComfyUI and Flask services if they are running."""
        # Check external detection too - we cannot stop external process
        # 同时检查外部检测 - 我们无法停止外部进程
        if not self._is_comfyui_running() and not self._is_flask_running() and not self.comfyui_externally_detected:
            print("Stop all: No processes active or detected.")
            self._update_ui_state(); return

        self.log_to_gui("Launcher", "停止所有服务...", "info")
        self.status_label.config(text="状态: 停止所有服务...")
        self.progress_bar.start(10)

        if hasattr(self, 'stop_all_button'): self.stop_all_button.config(state=tk.DISABLED)
        if hasattr(self, 'comfy_stop_button'): self.comfy_stop_button.config(state=tk.DISABLED)
        if hasattr(self, 'flask_stop_button'): self.flask_stop_button.config(state=tk.DISABLED)

        if self._is_flask_running(): self._stop_flask_service()
        # Only stop ComfyUI if we are managing it (not external)
        # 仅当我们管理 ComfyUI 时才停止它（非外部）
        if self._is_comfyui_running(): self._stop_comfyui_service()
        else:
            # If only external was detected, just reset the flag
            # 如果仅检测到外部，则仅重置标志
            self.comfyui_externally_detected = False

        self.root.after(1000, self._update_ui_state)

    # --- UI State and Helpers ---
    # --- MODIFIED: Added check for comfyui_externally_detected ---
    # --- 修改：添加了对 comfyui_externally_detected 的检查 ---
    def _update_ui_state(self):
        """Central function to update all button states and status label."""
        comfy_running_internally = self._is_comfyui_running()
        flask_running = self._is_flask_running()
        comfy_detected_externally = getattr(self, 'comfyui_externally_detected', False) # Safely check flag / 安全地检查标志

        status_text = ""; main_stop_style = ""; main_run_enabled = tk.NORMAL; main_stop_enabled = tk.NORMAL; should_stop_progress = True

        if comfy_detected_externally and not comfy_running_internally:
             # Special state: Detected externally, but not managed by us / 特殊状态：外部检测到，但不由我们管理
             status_text = f"状态: 外部 ComfyUI 运行中 (端口 {self.comfyui_api_port})"
             main_stop_style = "Stop.TButton" # Can't stop external process / 无法停止外部进程
             main_run_enabled = tk.DISABLED # Don't allow starting over it / 不允许在其上启动
             main_stop_enabled = tk.DISABLED # Cannot stop external / 无法停止外部
             if flask_running: # If Flask is also running with external ComfyUI / 如果 Flask 也与外部 ComfyUI 一起运行
                  status_text += " | 前端运行中"
                  main_stop_enabled = tk.NORMAL # Allow stopping Flask / 允许停止 Flask
                  main_stop_style = "StopRunning.TButton" # Red for Flask running / Flask 运行时为红色
        elif comfy_running_internally and flask_running:
            status_text = "状态: 全部运行中 / Status: All Running"
            main_stop_style = "StopRunning.TButton"
            main_run_enabled = tk.DISABLED
            main_stop_enabled = tk.NORMAL
        elif comfy_running_internally:
            status_text = "状态: 仅后端运行中 / Status: Backend Running"
            main_stop_style = "StopRunning.TButton"
            main_run_enabled = tk.NORMAL
            main_stop_enabled = tk.NORMAL
        elif flask_running: # Must be comfy_detected_externally == False here / 此处 comfy_detected_externally 必须为 False
             status_text = "状态: 仅前端运行中 (后端未运行) / Status: Frontend Running (Backend stopped)"
             main_stop_style = "StopRunning.TButton"
             main_run_enabled = tk.NORMAL
             main_stop_enabled = tk.NORMAL
        else: # Neither running internally nor detected externally / 既未在内部运行也未在外部检测到
             is_stopping_or_starting = False
             try:
                 if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists():
                    is_stopping_or_starting = self.progress_bar.cget('mode') == 'indeterminate' and self.progress_bar.winfo_ismapped()
             except tk.TclError: pass
             if is_stopping_or_starting:
                 current_status = "状态: 处理中..."
                 try:
                     if hasattr(self, 'status_label') and self.status_label.winfo_exists(): current_status = self.status_label.cget("text")
                 except tk.TclError: pass
                 status_text = current_status
                 should_stop_progress = False
             else:
                 status_text = "状态: 服务已停止 / Status: Services Stopped"
                 should_stop_progress = True
             main_stop_style = "Stop.TButton"
             main_run_enabled = tk.NORMAL
             main_stop_enabled = tk.DISABLED

        if should_stop_progress:
            try:
                if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists() and self.progress_bar.winfo_ismapped(): self.progress_bar.stop()
            except tk.TclError: pass

        # Update main controls safely
        try:
            if hasattr(self, 'status_label') and self.status_label.winfo_exists(): self.status_label.config(text=status_text)
            if hasattr(self, 'run_all_button') and self.run_all_button.winfo_exists(): self.run_all_button.config(state=main_run_enabled, style="Accent.TButton")
            if hasattr(self, 'stop_all_button') and self.stop_all_button.winfo_exists(): self.stop_all_button.config(state=main_stop_enabled, style=main_stop_style)

            # Update Backend Tab Controls
            comfy_can_run = self._validate_paths_for_execution(check_comfyui=True, check_flask=False, show_error=False)
            if hasattr(self, 'comfy_run_button') and self.comfy_run_button.winfo_exists():
                # Disable Run if running internally OR detected externally / 如果内部运行或外部检测到则禁用运行
                comfy_run_state = tk.DISABLED if (comfy_running_internally or comfy_detected_externally) else (tk.NORMAL if comfy_can_run else tk.DISABLED)
                self.comfy_run_button.config(state=comfy_run_state)
            if hasattr(self, 'comfy_stop_button') and self.comfy_stop_button.winfo_exists():
                 # Can only stop if running internally / 仅当内部运行时才能停止
                 comfy_stop_state = tk.NORMAL if comfy_running_internally else tk.DISABLED
                 self.comfy_stop_button.config(state=comfy_stop_state, style="TabStopRunning.TButton" if comfy_running_internally else "TabStop.TButton")

            # Update Frontend Tab Controls
            flask_can_run_paths = self._validate_paths_for_execution(check_comfyui=False, check_flask=True, show_error=False)
            # Can only run Flask if ComfyUI is running (internally or externally) AND paths are valid
            # 仅当 ComfyUI 正在运行（内部或外部）且路径有效时才能运行 Flask
            can_run_flask = (comfy_running_internally or comfy_detected_externally) and flask_can_run_paths
            if hasattr(self, 'flask_run_button') and self.flask_run_button.winfo_exists():
                self.flask_run_button.config(state=tk.DISABLED if flask_running else (tk.NORMAL if can_run_flask else tk.DISABLED))
            if hasattr(self, 'flask_stop_button') and self.flask_stop_button.winfo_exists():
                self.flask_stop_button.config(state=tk.NORMAL if flask_running else tk.DISABLED, style="TabStopRunning.TButton" if flask_running else "TabStop.TButton")

        except tk.TclError as e: print(f"Warning: Error updating UI state (widget might not exist): {e}")
        except AttributeError as e: print(f"Warning: Error updating UI state (attribute missing): {e}")

    def reset_ui_on_error(self):
        try:
            if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists() and self.progress_bar.winfo_ismapped(): self.progress_bar.stop()
        except tk.TclError: pass
        comfy_crashed = self.comfyui_process and self.comfyui_process.poll() is not None
        flask_crashed = self.flask_process and self.flask_process.poll() is not None
        if comfy_crashed: self.comfyui_process = None
        if flask_crashed: self.flask_process = None
        # Status update handled by _update_ui_state which is called after this
        # 状态更新由之后调用的 _update_ui_state 处理
        self._update_ui_state() # Call update state to reflect crashed processes / 调用更新状态以反映崩溃的进程

    def _open_frontend_browser(self):
        if self._is_flask_running():
            flask_url = f"http://127.0.0.1:5000"
            print(f"DEBUG: Opening Frontend URL: {flask_url}")
            try: webbrowser.open_new_tab(flask_url)
            except Exception as e: print(f"Error opening frontend browser tab: {e}")
        else: print(f"DEBUG: Skip frontend browser open - Flask not running.")

    def _trigger_backend_browser_opening(self):
        # Trigger only if running internally OR detected externally, and not already triggered
        # 仅当内部运行或外部检测到，并且尚未触发时才触发
        comfy_is_active = self._is_comfyui_running() or self.comfyui_externally_detected
        if comfy_is_active and not self.backend_browser_triggered_for_session:
            self.backend_browser_triggered_for_session = True
            api_port = self.config.get("comfyui_api_port", DEFAULT_COMFYUI_API_PORT)
            comfyui_url = f"http://127.0.0.1:{api_port}"
            print(f"Opening backend browser: {comfyui_url}")
            try: webbrowser.open_new_tab(comfyui_url)
            except Exception as e: print(f"Error opening backend: {e}")
        elif not comfy_is_active: print("DEBUG TRIGGER: ComfyUI stopped or not detected.")
        else: print("DEBUG TRIGGER: Backend browser already opened for this session.")

    def clear_output_widgets(self):
        for widget in [self.main_output_text, self.app_output_text]:
            try:
                if widget and widget.winfo_exists(): widget.config(state=tk.NORMAL); widget.delete('1.0', tk.END); widget.config(state=tk.DISABLED)
            except tk.TclError: pass
    def on_closing(self):
        print("Closing application...")
        # Check external detection as well / 同时检查外部检测
        if self._is_comfyui_running() or self._is_flask_running():
             if messagebox.askyesno("服务运行中", "服务仍在运行。\n是否在退出前停止 (仅停止此启动器管理的服务)？", parent=self.root):
                 self.stop_all_services() # Will only stop internal processes / 只会停止内部进程
                 self.root.after(1000, self.root.destroy)
             else:
                  # Still try to terminate managed processes if user says no to graceful stop
                  # 如果用户拒绝正常停止，仍然尝试终止托管进程
                  if self._is_flask_running(): self.flask_process.terminate()
                  if self._is_comfyui_running(): self.comfyui_process.terminate()
                  self.stop_event.set(); self.root.destroy()
        else:
             self.root.destroy()

# --- Main Execution ---
if __name__ == "__main__":
    base_project_dir_check = os.path.dirname(os.path.abspath(__file__))
    venv_python_check = os.path.join(base_project_dir_check, "venv", "Scripts", "python.exe")
    app_script_check = os.path.join(base_project_dir_check, "app.py")
    # --- REMOVED workflows_config.json check ---
    # --- 移除 workflows_config.json 检查 ---
    # expected_workflow_config_file = 'workflows_config.json'
    # config_check = os.path.join(base_project_dir_check, expected_workflow_config_file)
    critical_error = False; error_msg = ""

    # Critical checks
    if not os.path.isfile(venv_python_check):
        error_msg += f"未找到前端 Venv Python:\n{venv_python_check}\n(请确保已创建虚拟环境)\n\n"
        critical_error = True
    if not os.path.isfile(app_script_check):
        error_msg += f"未找到前端 App 脚本:\n{app_script_check}\n\n"
        critical_error = True

    # --- REMOVED workflows_config.json check ---
    # if not os.path.isfile(config_check):
    #     error_msg += f"警告：未找到工作流配置文件:\n{config_check}\n(某些功能可能受影响)\n\n"

    # Check default ComfyUI install dir (if set) as a hint
    if DEFAULT_COMFYUI_INSTALL_DIR and not os.path.isdir(DEFAULT_COMFYUI_INSTALL_DIR):
        error_msg += f"警告：默认 ComfyUI 目录不存在:\n{DEFAULT_COMFYUI_INSTALL_DIR}\n(请在设置中指定正确路径)\n\n"

    # Handle errors
    if critical_error:
        root_err = tk.Tk(); root_err.withdraw()
        messagebox.showerror("启动错误 / Startup Error", error_msg + "应用程序将退出。 / Application will exit.")
        root_err.destroy(); exit()
    elif error_msg:
        root_warn = tk.Tk(); root_warn.withdraw()
        messagebox.showwarning("启动警告 / Startup Warning", error_msg + "应用程序将继续启动。 / Application will continue.")
        root_warn.destroy()

    # Start the application
    root = tk.Tk()
    app = ConfigurableServiceRunnerApp(root)
    root.mainloop()