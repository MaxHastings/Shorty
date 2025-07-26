import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import cv2
from PIL import Image, ImageTk
import sys
import threading
import re # For parsing FFmpeg progress output
import time # For simulating progress in parsing
import tempfile # For temporary log file

# Helper function (can be outside class as it's general purpose)
def get_ffmpeg_path():
    """
    Determines the correct path to the FFmpeg executable, whether running
    as a PyInstaller bundled app or a regular Python script.
    """
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    ffmpeg_exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    ffmpeg_path = os.path.join(base_path, ffmpeg_exe_name)
    
    if not os.path.exists(ffmpeg_path):
        try:
            # Try to run from PATH if not found next to the script/exe
            subprocess.run([ffmpeg_exe_name, "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return ffmpeg_exe_name
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
            
    return ffmpeg_path

class VideoEditorApp:
    def __init__(self, master):
        self.master = master
        master.title("Video Trimmer + Compressor")

        # --- Model/State Variables ---
        self.input_filepath = tk.StringVar()
        self.output_filepath = tk.StringVar(value="output_trimmed.mp4")
        self.half_res_enabled = tk.BooleanVar(value=False)
        
        # Optimization variables
        self.target_size_mb = tk.StringVar(value="10") # For target bitrate mode
        self.video_crf = tk.StringVar(value="23")      # For CRF mode (quality-based)
        self.use_crf = tk.BooleanVar(value=True)       # Toggle between target size and CRF
        
        self.remove_audio = tk.BooleanVar(value=False)
        self.audio_bitrate_choice = tk.StringVar(value="128k") # Default audio bitrate
        self.target_framerate = tk.StringVar(value="Original") # Default framerate
        self.ffmpeg_preset = tk.StringVar(value="medium") # Default preset for CPU encoders
        self.use_hevc = tk.BooleanVar(value=False) # Use H.265 (HEVC) instead of H.264
        self.gpu_accel_choice = tk.StringVar(value="None") # New: For GPU acceleration

        # Video capture object
        self.video_cap = None
        self.video_duration_sec = 0
        self.original_video_width = 0
        self.original_video_height = 0
        self.original_video_fps = 0 # To store original FPS

        # Cropping state
        self.crop_start_x = -1
        self.crop_start_y = -1
        self.crop_end_x = -1
        self.crop_end_y = -1
        self.crop_rectangle_id = None
        self.displayed_frame_on_canvas = None
        self.current_preview_cv_frame = None

        # Canvas image display properties (to map canvas coords to video coords)
        self.canvas_img_offset_x = 0
        self.canvas_img_offset_y = 0
        self.canvas_img_display_width = 0
        self.canvas_img_display_height = 0

        # FFmpeg process handle for potential cancellation
        self.ffmpeg_process = None
        self.current_pass = 0 # 0: idle, 1: pass1, 2: pass2

        # --- GUI Setup ---
        self._create_widgets()
        self._bind_events()

        # Handle window closing to release resources
        self.master.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Initial UI update
        self._update_slider_labels()
        self._toggle_bitrate_crf_options() # Set initial state for size/CRF
        self._toggle_audio_options() # Set initial state for audio bitrate
        self._toggle_gpu_preset_options() # Initial state for GPU/Preset

    def _create_widgets(self):
        # Configure grid weights for main window for resizing
        self.master.grid_rowconfigure(4, weight=1) # Row containing the canvas
        self.master.grid_columnconfigure(0, weight=1) 
        self.master.grid_columnconfigure(1, weight=1) 
        self.master.grid_columnconfigure(2, weight=1) 

        # Input/Output Frame
        input_output_frame = ttk.LabelFrame(self.master, text="File & Basic Settings")
        input_output_frame.grid(row=0, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        input_output_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(input_output_frame, text="Input Video:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        ttk.Entry(input_output_frame, textvariable=self.input_filepath, width=60).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(input_output_frame, text="Browse", command=self._browse_input_file).grid(row=0, column=2, padx=5, pady=5)

        # Target Size/CRF Options
        self.size_crf_frame = ttk.Frame(input_output_frame)
        self.size_crf_frame.grid(row=1, column=0, columnspan=3, sticky="ew")
        self.size_crf_frame.grid_columnconfigure(1, weight=1)

        self.radio_crf = ttk.Radiobutton(self.size_crf_frame, text="Target Quality (CRF):", variable=self.use_crf, value=True, command=self._toggle_bitrate_crf_options)
        self.radio_crf.grid(row=0, column=0, sticky="e", padx=5, pady=2)
        self.entry_crf = ttk.Entry(self.size_crf_frame, textvariable=self.video_crf, width=10)
        self.entry_crf.grid(row=0, column=1, sticky="w", padx=5, pady=2)
        
        self.radio_size = ttk.Radiobutton(self.size_crf_frame, text="Target Size (MB):", variable=self.use_crf, value=False, command=self._toggle_bitrate_crf_options)
        self.radio_size.grid(row=1, column=0, sticky="e", padx=5, pady=2)
        self.entry_size = ttk.Entry(self.size_crf_frame, textvariable=self.target_size_mb, width=10)
        self.entry_size.grid(row=1, column=1, sticky="w", padx=5, pady=2)

        # Output file
        ttk.Label(input_output_frame, text="Output Video:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        ttk.Entry(input_output_frame, textvariable=self.output_filepath, width=60).grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(input_output_frame, text="Save As", command=self._browse_output_file).grid(row=2, column=2, padx=5, pady=5)

        # Output Options Frame
        options_frame = ttk.LabelFrame(self.master, text="Advanced Output Options")
        options_frame.grid(row=1, column=0, columnspan=3, padx=10, pady=5, sticky="ew") # Placed below input frame
        options_frame.grid_columnconfigure(1, weight=1) 

        ttk.Checkbutton(options_frame, text="Half Resolution Output", variable=self.half_res_enabled).grid(row=0, column=0, sticky="w", padx=5, pady=2)
        
        ttk.Checkbutton(options_frame, text="Remove Audio", variable=self.remove_audio, command=self._toggle_audio_options).grid(row=0, column=1, sticky="w", padx=5, pady=2)
        ttk.Label(options_frame, text="Audio Bitrate:").grid(row=1, column=0, sticky="e", padx=5, pady=2)
        self.audio_bitrate_menu = ttk.Combobox(options_frame, textvariable=self.audio_bitrate_choice, 
                                               values=["64k", "96k", "128k", "192k", "256k"], state="readonly", width=8)
        self.audio_bitrate_menu.grid(row=1, column=1, sticky="w", padx=5, pady=2)
        self.audio_bitrate_menu.set("128k")

        ttk.Label(options_frame, text="Target Frame Rate:").grid(row=2, column=0, sticky="e", padx=5, pady=2)
        self.framerate_menu = ttk.Combobox(options_frame, textvariable=self.target_framerate, 
                                           values=["Original", "30", "24", "15"], state="readonly", width=8)
        self.framerate_menu.grid(row=2, column=1, sticky="w", padx=5, pady=2)
        self.framerate_menu.set("Original")

        ttk.Label(options_frame, text="FFmpeg Preset:").grid(row=3, column=0, sticky="e", padx=5, pady=2)
        self.preset_menu = ttk.Combobox(options_frame, textvariable=self.ffmpeg_preset, 
                                         values=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"], state="readonly", width=10)
        self.preset_menu.grid(row=3, column=1, sticky="w", padx=5, pady=2)
        self.preset_menu.set("medium")

        ttk.Checkbutton(options_frame, text="Use H.265 (HEVC) Codec", variable=self.use_hevc, command=self._toggle_gpu_preset_options).grid(row=4, column=0, sticky="w", padx=5, pady=2)

        # New: GPU Acceleration option
        ttk.Label(options_frame, text="GPU Acceleration:").grid(row=5, column=0, sticky="e", padx=5, pady=2)
        self.gpu_accel_menu = ttk.Combobox(options_frame, textvariable=self.gpu_accel_choice, 
                                           values=["None", "NVIDIA (NVENC)", "AMD (AMF)", "Intel (QSV)"], 
                                           state="readonly", width=15)
        self.gpu_accel_menu.grid(row=5, column=1, sticky="w", padx=5, pady=2)
        self.gpu_accel_menu.set("None") # Default to no GPU acceleration
        self.gpu_accel_menu.bind("<<ComboboxSelected>>", lambda e: self._toggle_gpu_preset_options())


        # Video Preview Canvas
        self.canvas = tk.Canvas(self.master, width=640, height=360, bg="black", bd=2, relief="sunken")
        self.canvas.grid(row=2, column=0, columnspan=3, pady=10, padx=10, sticky="nsew") # Adjusted row
        self.canvas.create_text(self.canvas.winfo_width()/2, self.canvas.winfo_height()/2,
                                     text="Load a video to see preview\nDrag on preview to select crop area",
                                     fill="white", font=("Arial", 16))

        # Trimming Controls Frame
        trim_frame = ttk.LabelFrame(self.master, text="Video Trimming")
        trim_frame.grid(row=3, column=0, columnspan=3, padx=10, pady=5, sticky="ew") # Adjusted row
        trim_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(trim_frame, text="Start Time:").grid(row=0, column=0, sticky="e", padx=5, pady=2)
        self.start_scale = ttk.Scale(trim_frame, from_=0, to=10, orient="horizontal", length=450,
                                         command=self._on_slider_move)
        self.start_scale.grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        self.start_time_label = ttk.Label(trim_frame, text="0 sec", width=8)
        self.start_time_label.grid(row=0, column=2, sticky="w", padx=5)

        ttk.Label(trim_frame, text="End Time:").grid(row=1, column=0, sticky="e", padx=5, pady=2)
        self.end_scale = ttk.Scale(trim_frame, from_=0, to=10, orient="horizontal", length=450,
                                         command=self._on_slider_move)
        self.end_scale.grid(row=1, column=1, padx=5, pady=2, sticky="ew")
        self.end_time_label = ttk.Label(trim_frame, text="0 sec", width=8)
        self.end_time_label.grid(row=1, column=2, sticky="w", padx=5)

        # Crop Reset Button
        ttk.Button(trim_frame, text="Reset Crop Selection", command=self._reset_crop_selection).grid(row=2, column=1, pady=5, sticky="w")

        # Process Button & Progress Bar
        process_frame = ttk.Frame(self.master)
        process_frame.grid(row=5, column=0, columnspan=3, pady=10, padx=10, sticky="ew")
        process_frame.grid_columnconfigure(0, weight=1)
        process_frame.grid_columnconfigure(1, weight=1)

        self.process_button = ttk.Button(process_frame, text="Trim & Compress Video", command=self._start_compression_thread,
                                         style="Accent.TButton")
        self.process_button.grid(row=0, column=0, pady=5, sticky="ew")

        self.cancel_button = ttk.Button(process_frame, text="Cancel", command=self._cancel_compression, state=tk.DISABLED)
        self.cancel_button.grid(row=0, column=1, pady=5, padx=(5,0), sticky="ew")

        self.progress_bar = ttk.Progressbar(self.master, orient="horizontal", length=100, mode="determinate")
        self.progress_bar.grid(row=6, column=0, columnspan=3, pady=5, padx=10, sticky="ew")

        self.status_label = ttk.Label(self.master, text="", foreground="blue")
        self.status_label.grid(row=7, column=0, columnspan=3, pady=5)

    def _bind_events(self):
        self.canvas.bind("<ButtonPress-1>", self._on_button_press)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_button_release)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _toggle_audio_options(self):
        if self.remove_audio.get():
            self.audio_bitrate_menu.config(state="disabled")
        else:
            self.audio_bitrate_menu.config(state="readonly")

    def _toggle_bitrate_crf_options(self):
        if self.use_crf.get():
            self.entry_crf.config(state="normal")
            self.entry_size.config(state="disabled")
            self.status_label.config(text="Using CRF: Output size will vary based on quality setting.")
        else:
            self.entry_crf.config(state="disabled")
            self.entry_size.config(state="normal")
            self.status_label.config(text="Using Target Size: FFmpeg will use two-pass encoding for accuracy.")

    def _toggle_gpu_preset_options(self):
        """
        Adjusts the state of the FFmpeg preset and potentially other related options
        based on GPU acceleration and HEVC choice.
        """
        gpu_selected = self.gpu_accel_choice.get() != "None"

        if gpu_selected:
            # When GPU is selected, disable the general FFmpeg preset dropdown.
            # GPU encoders often have their own specific presets (e.g., 'p1'-'p7' for NVENC)
            # which will be handled directly in the FFmpeg command construction.
            self.preset_menu.config(state="disabled")
            self.status_label.config(text=f"Using GPU encoder ({self.gpu_accel_choice.get()}). Presets are typically handled internally or use specific GPU-vendor presets.")
        else:
            # If no GPU is selected, re-enable the general FFmpeg preset dropdown.
            self.preset_menu.config(state="readonly")
            # If GPU is not selected, revert to the status message for CRF/Target Size
            self._toggle_bitrate_crf_options() # Re-sync status message related to quality/size

    def _browse_input_file(self):
        filepath = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi")])
        if filepath:
            self.input_filepath.set(filepath)
            base_name = os.path.splitext(os.path.basename(filepath))[0]
            self.output_filepath.set(f"{base_name}_compressed.mp4")
            self._load_video(filepath)

    def _browse_output_file(self):
        filepath = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4 files", "*.mp4")])
        if filepath:
            self.output_filepath.set(filepath)

    def _load_video(self, path):
        if self.video_cap is not None:
            self.video_cap.release()
            self.video_cap = None

        self.video_cap = cv2.VideoCapture(path)
        if not self.video_cap.isOpened():
            messagebox.showerror("Error", "Unable to open video.")
            self.input_filepath.set("")
            return

        fps = self.video_cap.get(cv2.CAP_PROP_FPS)
        frame_count = self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self.original_video_width = int(self.video_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.original_video_height = int(self.video_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.original_video_fps = fps
        self.video_duration_sec = int(frame_count / fps)

        self.start_scale.config(to=self.video_duration_sec)
        self.end_scale.config(to=self.video_duration_sec)

        self.start_scale.set(0)
        self.end_scale.set(self.video_duration_sec)

        self._reset_crop_selection()
        self._update_frame_preview(0)
        self._update_slider_labels()
        
        # Update framerate menu to reflect original FPS
        fps_options = ["Original", "30", "24", "15"]
        if self.original_video_fps > 0:
            # Add original FPS to options if it's not one of the fixed ones
            if int(self.original_video_fps) not in [30, 24, 15]:
                fps_options.insert(1, str(int(self.original_video_fps))) # Add next to Original
            self.framerate_menu['values'] = fps_options
            self.framerate_menu.set(f"Original ({int(self.original_video_fps)} FPS)")
        else:
            self.framerate_menu['values'] = fps_options
            self.framerate_menu.set("Original")


    def _update_frame_preview(self, current_time_sec):
        if self.video_cap is None:
            return

        current_time_sec = max(0, min(current_time_sec, self.video_duration_sec))

        self.video_cap.set(cv2.CAP_PROP_POS_MSEC, current_time_sec * 1000)
        ret, frame = self.video_cap.read()

        if ret:
            canvas_w = self.canvas.winfo_width()
            canvas_h = self.canvas.winfo_height()
            
            if canvas_w == 1 and canvas_h == 1: # Default size before first configure event
                canvas_w = 640
                canvas_h = 360

            h, w, _ = frame.shape
            aspect_ratio = w / h

            if aspect_ratio > (canvas_w / canvas_h):
                new_width = canvas_w
                new_height = int(canvas_w / aspect_ratio)
            else:
                new_height = canvas_h
                new_width = int(canvas_h * aspect_ratio)

            self.current_preview_cv_frame = cv2.resize(frame, (new_width, new_height))
            img = Image.fromarray(cv2.cvtColor(self.current_preview_cv_frame, cv2.COLOR_BGR2RGB))
            self.displayed_frame_on_canvas = ImageTk.PhotoImage(image=img)

            self.canvas.delete("all")
            self.canvas_img_offset_x = (canvas_w - new_width) // 2
            self.canvas_img_offset_y = (canvas_h - new_height) // 2
            self.canvas_img_display_width = new_width
            self.canvas_img_display_height = new_height

            self.canvas.create_image(self.canvas_img_offset_x, self.canvas_img_offset_y,
                                         anchor=tk.NW, image=self.displayed_frame_on_canvas)
            self._draw_crop_rectangle()
        else:
            self.canvas.delete("all")
            self.canvas.create_text(self.canvas.winfo_width()/2, self.canvas.winfo_height()/2,
                                         text="Failed to load frame", fill="white", font=("Arial", 16))

    def _on_canvas_configure(self, event):
        if self.video_cap and self.video_cap.isOpened():
            self._update_frame_preview(self.start_scale.get())
        else:
            self.canvas.delete("all")
            self.canvas.create_text(event.width / 2, event.height / 2,
                                         text="Load a video to see preview\nDrag on preview to select crop area",
                                         fill="white", font=("Arial", 16))

    def _on_slider_move(self, value):
        current_time_sec = float(value)
        self._update_slider_labels()
        self._update_frame_preview(current_time_sec)

    def _update_slider_labels(self):
        self.start_time_label.config(text=f"{int(self.start_scale.get())} sec")
        self.end_time_label.config(text=f"{int(self.end_scale.get())} sec")

    # --- Cropping Logic ---
    def _on_button_press(self, event):
        if self.video_cap is None or not self.video_cap.isOpened() or self.current_preview_cv_frame is None:
            return

        # Ensure click is within the displayed image area
        if not (self.canvas_img_offset_x <= event.x <= self.canvas_img_offset_x + self.canvas_img_display_width and
                self.canvas_img_offset_y <= event.y <= self.canvas_img_offset_y + self.canvas_img_display_height):
            return

        self.crop_start_x = event.x
        self.crop_start_y = event.y
        self.crop_end_x = event.x
        self.crop_end_y = event.y

        if self.crop_rectangle_id:
            self.canvas.delete(self.crop_rectangle_id)

        self.crop_rectangle_id = self.canvas.create_rectangle(
            self.crop_start_x, self.crop_start_y, self.crop_end_x, self.crop_end_y,
            outline="red", width=2, dash=(5, 2)
        )

    def _on_mouse_drag(self, event):
        if self.crop_start_x == -1:
            return

        # Constrain drag within the displayed image area
        current_x = max(self.canvas_img_offset_x, min(event.x, self.canvas_img_offset_x + self.canvas_img_display_width))
        current_y = max(self.canvas_img_offset_y, min(event.y, self.canvas_img_offset_y + self.canvas_img_display_height))

        self.crop_end_x = current_x
        self.crop_end_y = current_y

        if self.crop_rectangle_id:
            self.canvas.coords(self.crop_rectangle_id, self.crop_start_x, self.crop_start_y, self.crop_end_x, self.crop_end_y)

    def _on_button_release(self, event):
        if self.crop_start_x == -1:
            return

        # Finalize crop coordinates, clamping them to the image display area
        x1_raw = max(self.canvas_img_offset_x, min(self.crop_start_x, self.canvas_img_offset_x + self.canvas_img_display_width))
        y1_raw = max(self.canvas_img_offset_y, min(self.crop_start_y, self.canvas_img_offset_y + self.canvas_img_display_height))
        x2_raw = max(self.canvas_img_offset_x, min(self.crop_end_x, self.canvas_img_offset_x + self.canvas_img_display_width))
        y2_raw = max(self.canvas_img_offset_y, min(self.crop_end_y, self.canvas_img_offset_y + self.canvas_img_display_height))

        self.crop_start_x = min(x1_raw, x2_raw)
        self.crop_start_y = min(y1_raw, y2_raw)
        self.crop_end_x = max(x1_raw, x2_raw)
        self.crop_end_y = max(y1_raw, y2_raw)

        self._draw_crop_rectangle()
        print(f"Crop selection (canvas pixels): ({self.crop_start_x}, {self.crop_start_y}) to ({self.crop_end_x}, {self.crop_end_y})")

    def _draw_crop_rectangle(self):
        if self.crop_rectangle_id:
            self.canvas.delete(self.crop_rectangle_id)
            self.crop_rectangle_id = None

        if self.crop_start_x != -1 and self.crop_end_x != -1 and \
           abs(self.crop_start_x - self.crop_end_x) >= 2 and \
           abs(self.crop_start_y - self.crop_end_y) >= 2: # Only draw if valid selection (at least 2x2 pixels)
            self.crop_rectangle_id = self.canvas.create_rectangle(
                self.crop_start_x, self.crop_start_y, self.crop_end_x, self.crop_end_y,
                outline="red", width=2, dash=(5, 2)
            )

    def _reset_crop_selection(self):
        self.crop_start_x = -1
        self.crop_start_y = -1
        self.crop_end_x = -1
        self.crop_end_y = -1
        if self.crop_rectangle_id:
            self.canvas.delete(self.crop_rectangle_id)
        self.crop_rectangle_id = None
        print("Crop selection reset.")

    def _get_ffmpeg_crop_params(self):
        if self.crop_start_x == -1 or self.crop_end_x == -1 or \
           abs(self.crop_start_x - self.crop_end_x) < 2 or \
           abs(self.crop_start_y - self.crop_end_y) < 2:
            return None

        # Calculate relative coordinates on the displayed image within the canvas
        rel_x1_canvas = self.crop_start_x - self.canvas_img_offset_x
        rel_y1_canvas = self.crop_start_y - self.canvas_img_offset_y
        rel_x2_canvas = self.crop_end_x - self.canvas_img_offset_x
        rel_y2_canvas = self.crop_end_y - self.canvas_img_offset_y

        if self.canvas_img_display_width == 0 or self.canvas_img_display_height == 0:
            print("Warning: canvas_img_display_width or height is zero. Cannot calculate crop.")
            return None

        # Scale canvas coordinates back to original video resolution
        scale_x = self.original_video_width / self.canvas_img_display_width
        scale_y = self.original_video_height / self.canvas_img_display_height

        crop_x = int(rel_x1_canvas * scale_x)
        crop_y = int(rel_y1_canvas * scale_y)
        crop_width = int((rel_x2_canvas - rel_x1_canvas) * scale_x)
        crop_height = int((rel_y2_canvas - rel_y1_canvas) * scale_y)

        # Ensure coordinates and dimensions are valid and even (for video compatibility)
        crop_x = max(0, crop_x)
        crop_y = max(0, crop_y)
        crop_width = max(2, min(crop_width, self.original_video_width - crop_x))
        crop_height = max(2, min(crop_height, self.original_video_height - crop_y))

        crop_x = (crop_x // 2) * 2
        crop_y = (crop_y // 2) * 2
        crop_width = (crop_width // 2) * 2
        crop_height = (crop_height // 2) * 2

        print(f"Calculated FFmpeg crop: w={crop_width}, h={crop_height}, x={crop_x}, y={crop_y}")
        return f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y}"

    # --- Compression Logic ---
    def _calculate_bitrate(self, size_mb, duration_sec, audio_bitrate_kbps_str):
        if duration_sec <= 0:
            raise ValueError("Duration must be positive to calculate bitrate.")
        
        total_kbits = size_mb * 8192 # Convert MB to kilobits (1 MB = 8192 Kbits)

        audio_bitrate_kbps = 0
        if not self.remove_audio.get():
            try:
                audio_bitrate_kbps = int(audio_bitrate_kbps_str.replace('k', ''))
            except ValueError:
                audio_bitrate_kbps = 128 # Fallback if parsing fails

        # Account for potential overhead (container, metadata) by reducing target by a small percentage
        # A 5-10% reduction is common. Let's use 8% as a starting point.
        overhead_factor = 0.08
        target_kbits_for_streams = total_kbits * (1 - overhead_factor)

        min_audio_kbits_needed = audio_bitrate_kbps * duration_sec
        
        # If the remaining target for streams is too small, adjust audio bitrate or ensure positive video bitrate
        if target_kbits_for_streams <= min_audio_kbits_needed:
            if target_kbits_for_streams > 0 and duration_sec > 0:
                # Try to allocate 70% to video, 30% to audio if target is tight
                target_video_kbits = target_kbits_for_streams * 0.7 
                target_audio_kbits = target_kbits_for_streams * 0.3
                
                audio_bitrate_kbps = int(target_audio_kbits / duration_sec)
                # Ensure a reasonable minimum for audio (e.g., 32kbps if target is very small)
                if audio_bitrate_kbps < 32 and not self.remove_audio.get(): audio_bitrate_kbps = 32
                
                video_kbits_per_sec = (target_kbits_for_streams - (audio_bitrate_kbps * duration_sec)) / duration_sec
                video_bitrate_kbps = max(50, int(video_kbits_per_sec)) # Minimum 50 kbps for video
            else: # Very small/zero target size or duration
                video_bitrate_kbps = 50 # Minimal video bitrate
                audio_bitrate_kbps = 32 # Minimal audio bitrate
        else:
            video_kbits_per_sec = (target_kbits_for_streams - (audio_bitrate_kbps * duration_sec)) / duration_sec
            video_bitrate_kbps = max(50, int(video_kbits_per_sec)) # Minimum 50 kbps for video
        
        print(f"Calculated Video Bitrate: {video_bitrate_kbps} kbps, Audio Bitrate: {audio_bitrate_kbps} kbps")
        return video_bitrate_kbps, audio_bitrate_kbps

    def _start_compression_thread(self):
        self.process_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.NORMAL)
        self.status_label.config(text="Initializing compression...")
        self.progress_bar.config(value=0, mode="determinate") # Reset progress bar

        compression_thread = threading.Thread(target=self._compress_video_task)
        compression_thread.daemon = True
        compression_thread.start()

    def _cancel_compression(self):
        if self.ffmpeg_process and self.ffmpeg_process.poll() is None: # If process is running
            self.ffmpeg_process.terminate() # or .kill() for a more forceful termination
            self.master.after(0, lambda: self.status_label.config(text="Compression cancelled by user."))
            self.master.after(0, lambda: self.progress_bar.config(value=0))
            self.master.after(0, lambda: self.process_button.config(state=tk.NORMAL))
            self.master.after(0, lambda: self.cancel_button.config(state=tk.DISABLED))
            self.current_pass = 0 # Reset pass state

    def _execute_ffmpeg_command(self, command, duration_in_seconds, pass_number, total_passes, log_file_path=None):
        """
        Executes an FFmpeg command and updates progress.
        Returns True on success, False on failure or cancellation.
        """
        self.current_pass = pass_number
        pass_prefix = f"Pass {pass_number}/{total_passes}: "
        self.master.after(0, lambda: self.status_label.config(text=f"{pass_prefix}Starting FFmpeg..."))

        print(f"FFmpeg Command ({pass_prefix.strip()}):", " ".join(command))
        
        # Use a pipe for stderr to capture progress
        self.ffmpeg_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        
        # --- Progress Parsing (stderr) ---
        time_re = re.compile(r"time=(\d{2}):(\d{2}):(\d{2})\.\d+")
        
        start_progress_offset = (pass_number - 1) * (100 / total_passes)
        progress_scale_factor = (100 / total_passes) / duration_in_seconds if duration_in_seconds > 0 else 0

        for line in self.ffmpeg_process.stderr:
            # Check for cancellation
            if self.ffmpeg_process.poll() is not None: # Process has terminated
                if self.ffmpeg_process.returncode != 0:
                    # If the process terminated prematurely (e.g., due to cancellation or error)
                    if "Compression cancelled" not in self.status_label.cget("text"):
                        # Only show error if not user cancelled
                        print(f"FFmpeg ({pass_prefix.strip()}) process ended unexpectedly with code {self.ffmpeg_process.returncode}. Stderr: {line.strip()}")
                        self.master.after(0, lambda: self.status_label.config(text=f"{pass_prefix}Error: FFmpeg process failed."))
                    return False # Indicate failure or cancellation
                else: # Process completed successfully (e.g., pass 1 null output)
                    break # Exit loop, move to next step

            match = time_re.search(line)
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = int(match.group(3))
                current_time = hours * 3600 + minutes * 60 + seconds

                if duration_in_seconds > 0:
                    current_pass_progress = (current_time * progress_scale_factor)
                    total_progress_percentage = start_progress_offset + current_pass_progress
                    total_progress_percentage = min(total_progress_percentage, start_progress_offset + (100 / total_passes) - 1) # Cap
                    
                    self.master.after(0, lambda p=total_progress_percentage: self.progress_bar.config(value=p))
                    self.master.after(0, lambda ct=current_time: self.status_label.config(text=f"{pass_prefix}Processing: {ct} / {int(duration_in_seconds)} seconds"))
            
            # Small delay to prevent UI freeze and excessive CPU usage from parsing
            time.sleep(0.005) # Slightly reduced delay

        # Wait for the process to finish and get the return code
        self.ffmpeg_process.wait()
        
        if self.ffmpeg_process.returncode != 0:
            stderr_output = self.ffmpeg_process.stderr.read() # Read any remaining stderr output
            print(f"FFmpeg ({pass_prefix.strip()}) Error Output:\n{stderr_output}")
            return False # Indicate failure
        return True # Indicate success

    def _compress_video_task(self):
        log_file_path = None
        try:
            input_file = self.input_filepath.get()
            start_sec = int(self.start_scale.get())
            end_sec = int(self.end_scale.get())
            output_file = self.output_filepath.get()
            remove_audio = self.remove_audio.get()
            audio_bitrate_str = self.audio_bitrate_choice.get()
            half_res_enabled = self.half_res_enabled.get()
            use_crf = self.use_crf.get()
            crf_value = self.video_crf.get()
            target_size_mb = self.target_size_mb.get()
            target_framerate = self.target_framerate.get()
            ffmpeg_preset = self.ffmpeg_preset.get()
            use_hevc = self.use_hevc.get()
            gpu_accelerator = self.gpu_accel_choice.get()

            # --- Input Validation ---
            if not input_file or not os.path.exists(input_file):
                raise ValueError("Please select a valid input video file.")
            if not output_file:
                raise ValueError("Please specify an output file name.")
            if not output_file.lower().endswith(".mp4"):
                output_file += ".mp4"

            if start_sec >= end_sec:
                raise ValueError("Start time must be before end time.")

            total_duration_to_process = end_sec - start_sec
            if total_duration_to_process <= 0:
                raise ValueError("The selected trim duration is too short.")

            ffmpeg_path = get_ffmpeg_path()
            if ffmpeg_path is None:
                raise FileNotFoundError("FFmpeg executable not found. Please ensure it's in the same directory as the script/exe or in your system's PATH.")
            
            # Generate a temporary log file name
            temp_dir = tempfile.gettempdir()
            log_file_base = os.path.join(temp_dir, "ffmpeg2pass")
            log_file_path = f"{log_file_base}-0.log" # FFmpeg adds -0.log, -1.log etc.

            # Common FFmpeg arguments for both passes
            common_args = ["-ss", str(start_sec), "-to", str(end_sec), "-i", input_file]
            
            # --- Hardware Acceleration (Decoder - placed BEFORE input file in common_args) ---
            hwaccel_decoder_args = []
            if gpu_accelerator == "NVIDIA (NVENC)":
                hwaccel_decoder_args.extend(["-hwaccel", "cuda"]) 
            elif gpu_accelerator == "AMD (AMF)":
                hwaccel_decoder_args.extend(["-hwaccel", "dxva2"]) # Or 'd3d11va' for D3d11VA
            elif gpu_accelerator == "Intel (QSV)":
                hwaccel_decoder_args.extend(["-hwaccel", "qsv", "-qsv_decode", "true"])
            
            # Insert hwaccel args right after ffmpeg_path
            command_base = [ffmpeg_path, "-y"] + hwaccel_decoder_args + common_args

            # --- Video Codec and Encoder Options ---
            video_codec_params = []
            video_filters = []
            
            video_codec = "libx264" # Default CPU encoder (H.264)
            if gpu_accelerator == "NVIDIA (NVENC)":
                video_codec = "hevc_nvenc" if use_hevc else "h264_nvenc"
                video_codec_params.extend(["-preset", ffmpeg_preset]) # NVENC uses its own presets
            elif gpu_accelerator == "AMD (AMF)":
                video_codec = "hevc_amf" if use_hevc else "h264_amf"
                video_codec_params.extend(["-quality", ffmpeg_preset]) # AMF uses -quality
            elif gpu_accelerator == "Intel (QSV)":
                video_codec = "hevc_qsv" if use_hevc else "h264_qsv"
                video_codec_params.extend(["-preset", ffmpeg_preset]) # QSV also uses presets

            # --- Video Filters (Resolution, Frame Rate, Cropping) ---
            if half_res_enabled:
                new_width = self.original_video_width // 2
                new_height = self.original_video_height // 2
                new_width = (new_width // 2) * 2 # Ensure dimensions are even
                new_height = (new_height // 2) * 2
                video_filters.append(f"scale={new_width}:{new_height}")

            if target_framerate != "Original" and self.original_video_fps > 0:
                try:
                    original_fps_int = int(self.original_video_fps)
                    target_fps_int = int(target_framerate)
                    if target_fps_int < original_fps_int: # Only apply if target is lower
                        video_filters.append(f"fps={target_fps_int}")
                except ValueError:
                    pass

            crop_params = self._get_ffmpeg_crop_params()
            if crop_params:
                video_filters.append(crop_params)

            filter_complex_cmd = []
            if video_filters:
                filter_complex_cmd.extend(["-vf", ",".join(video_filters)])

            # --- Pass 1 Command (Target Size only) ---
            if not use_crf:
                try:
                    target_size_mb_val = float(target_size_mb)
                    if target_size_mb_val <= 0:
                        raise ValueError("Target size must be a positive number.")
                    
                    video_bitrate_kbps, audio_bitrate_kbps = self._calculate_bitrate(
                        target_size_mb_val, total_duration_to_process, audio_bitrate_str
                    )

                    # Pass 1 command construction
                    command_pass1 = command_base + [
                        "-c:v", video_codec,
                    ] + video_codec_params + [
                        "-b:v", f"{video_bitrate_kbps}k",
                        "-pass", "1",
                        "-an", # No audio in pass 1
                        "-f", "null", # Output to null
                        "-passlogfile", log_file_base,
                    ] + filter_complex_cmd + [
                        os.devnull # Actual output file is null
                    ]

                    # Execute Pass 1
                    if not self._execute_ffmpeg_command(command_pass1, total_duration_to_process, 1, 2):
                        raise Exception("FFmpeg Pass 1 failed or was cancelled.")

                    self.master.after(0, lambda: self.status_label.config(text="Pass 1 complete. Starting Pass 2..."))
                    self.master.after(0, lambda: self.progress_bar.config(value=50)) # Set progress to 50% after Pass 1

                    # --- Pass 2 Command ---
                    command_pass2 = command_base + [
                        "-c:v", video_codec,
                    ] + video_codec_params + [
                        "-b:v", f"{video_bitrate_kbps}k",
                        "-pass", "2",
                        "-passlogfile", log_file_base,
                    ] 
                    
                    # Audio options for Pass 2
                    if remove_audio:
                        command_pass2.extend(["-an"])
                    else:
                        command_pass2.extend(["-c:a", "aac", "-b:a", audio_bitrate_str])

                    command_pass2.extend(filter_complex_cmd)
                    command_pass2.extend(["-movflags", "+faststart", output_file])

                    # Execute Pass 2
                    if not self._execute_ffmpeg_command(command_pass2, total_duration_to_process, 2, 2):
                        raise Exception("FFmpeg Pass 2 failed or was cancelled.")

                    self.master.after(0, lambda: self.progress_bar.config(value=100))
                    self.master.after(0, lambda: self.status_label.config(text="Video trimmed and compressed successfully!"))
                    messagebox.showinfo("Success", "Video trimmed and compressed successfully!")

                except ValueError as e:
                    raise ValueError(f"Invalid target size: {e}. Please enter a valid number.")
            else: # CRF mode (single pass)
                command = command_base + [
                    "-c:v", video_codec,
                ] + video_codec_params
                
                try:
                    crf_val = int(crf_value)
                    if not (0 <= crf_val <= 51):
                        raise ValueError("CRF value must be between 0 and 51.")
                    command.extend(["-crf", str(crf_val)])
                except ValueError:
                    raise ValueError("Invalid CRF value. Please enter an integer.")

                # Audio options for CRF mode
                if remove_audio:
                    command.extend(["-an"]) # No audio
                else:
                    command.extend(["-c:a", "aac", "-b:a", audio_bitrate_str])
                
                command.extend(filter_complex_cmd)
                command.extend(["-movflags", "+faststart", output_file])

                # Execute single pass for CRF
                if not self._execute_ffmpeg_command(command, total_duration_to_process, 1, 1):
                    raise Exception("FFmpeg process failed or was cancelled.")

                self.master.after(0, lambda: self.progress_bar.config(value=100))
                self.master.after(0, lambda: self.status_label.config(text="Video trimmed and compressed successfully!"))
                messagebox.showinfo("Success", "Video trimmed and compressed successfully!")


        except ValueError as e:
            self.master.after(0, lambda: self.status_label.config(text=f"Input Error: {e}"))
            messagebox.showerror("Input Error", str(e))
        except FileNotFoundError as e:
            self.master.after(0, lambda: self.status_label.config(text=f"FFmpeg Error: {e}"))
            messagebox.showerror("FFmpeg Not Found", str(e))
        except Exception as e:
            self.master.after(0, lambda: self.status_label.config(text=f"An unexpected error occurred: {e}"))
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")
        finally:
            self.master.after(0, lambda: self.process_button.config(state=tk.NORMAL))
            self.master.after(0, lambda: self.cancel_button.config(state=tk.DISABLED))
            self.current_pass = 0 # Reset pass state
            if self.ffmpeg_process:
                self.ffmpeg_process.stdout.close()
                self.ffmpeg_process.stderr.close()
                self.ffmpeg_process = None # Clear process handle
            
            # Clean up temporary log files
            if log_file_path and os.path.exists(log_file_path):
                try:
                    os.remove(log_file_path)
                    # FFmpeg might also create .mbtree or other temporary files
                    # A more robust cleanup might iterate and delete files starting with the log_file_base
                    # E.g., for f in os.listdir(temp_dir): if f.startswith("ffmpeg2pass"): os.remove(os.path.join(temp_dir, f))
                    for ext in [".log", ".log.mbtree"]: # Common FFmpeg log extensions
                        if os.path.exists(log_file_base + ext):
                            os.remove(log_file_base + ext)
                except Exception as e:
                    print(f"Warning: Could not delete temporary FFmpeg log files: {e}")


    def _on_closing(self):
        if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
            if messagebox.askyesno("Quit", "FFmpeg is still running. Do you want to cancel and quit?"):
                self.ffmpeg_process.terminate()
                self.master.destroy()
            else:
                pass # Do nothing, user wants to keep app open
        else:
            if self.video_cap:
                self.video_cap.release()
            self.master.destroy()

def main():
    root = tk.Tk()
    app = VideoEditorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()