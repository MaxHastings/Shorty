import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import cv2
from PIL import Image, ImageTk
import os
import threading
import tempfile
from video_processor import VideoProcessor # Import the VideoProcessor

# Import ctypes for Windows AppID setting
import ctypes
import sys # Import sys to check OS

class VideoEditorApp:
    def __init__(self, master):
        self.master = master
        master.title("Shorty - Video Trimmer + Compressor")

        # --- Set the AppID for Windows Taskbar Icon ---
        if sys.platform.startswith('win'): # Check if running on Windows
            try:
                # This should be a unique string for your application.
                # Use your company name, product name, etc. to make it unique.
                # Example: 'MyCompany.ShortyVideoEditor.1.0'
                myappid = 'com.yourcompany.ShortyVideoEditor.1' # <-- CHANGE THIS TO SOMETHING UNIQUE FOR YOUR APP
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except AttributeError:
                # This can happen if ctypes is not available or if the OS is not Windows
                print("Warning: Could not set AppUserModelID (not on Windows or unsupported version). Taskbar icon might be generic.")
            except Exception as e:
                print(f"Error setting AppUserModelID: {e}")
        # --- End AppID setting ---

        # --- Icon Loading (Place this AFTER AppID setting, but before other widgets) ---
        try:
            script_dir = os.path.dirname(__file__)

            icon_path = os.path.join(script_dir, "favicon.ico") 

            if os.path.exists(icon_path):
                # Use iconbitmap for .ico files (best for Windows)
                master.iconbitmap(icon_path) 
            else:
                print(f"Warning: Icon file not found at {icon_path}. Looked for: {icon_path}")
                # Fallback to PNG if ICO not found (less reliable for taskbar)
                try:
                    png_icon_path = os.path.join(script_dir, "favicon.png")
                    if os.path.exists(png_icon_path):
                        icon_image = Image.open(png_icon_path)
                        icon_photo = ImageTk.PhotoImage(icon_image)
                        master.iconphoto(True, icon_photo) # Apply to main window and any future Toplevels
                        print(f"Using PNG fallback icon: {png_icon_path}")
                    else:
                        print(f"No PNG fallback icon found at: {png_icon_path}")
                except Exception as png_e:
                    print(f"Error loading PNG fallback icon: {png_e}")

        except tk.TclError as e:
            print(f"Tkinter TclError loading icon: {e}. Ensure '{icon_path}' is a valid .ico file.")
        except Exception as e:
            print(f"An unexpected error occurred while setting the main icon: {e}")
        # --- End of icon setting section ---

        # --- Model/State Variables ---
        self.input_filepath = tk.StringVar()
        self.output_filepath = tk.StringVar(value="output_trimmed.mp4")
        self.resolution_choice = tk.StringVar(value="Full") # Default to Full Resolution
        
        # Optimization variables
        self.target_size_mb = tk.StringVar(value="10")
        self.video_crf = tk.StringVar(value="23")
        self.use_crf = tk.BooleanVar(value=False)
        
        self.remove_audio = tk.BooleanVar(value=False)
        self.audio_bitrate_choice = tk.StringVar(value="96k")
        self.target_framerate = tk.StringVar(value="Original")
        self.ffmpeg_preset = tk.StringVar(value="medium")
        # CHANGED: Replaced use_hevc with video_codec_choice
        self.video_codec_choice = tk.StringVar(value="H265") # Default to H.265 (HEVC)
        self.gpu_accel_choice = tk.StringVar(value="None")

        # Video capture object
        self.video_cap = None
        self.video_duration_sec = 0
        self.original_video_width = 0
        self.original_video_height = 0
        self.original_video_fps = 0

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

        # Initialize VideoProcessor
        self.video_processor = VideoProcessor(self)

        # --- GUI Setup ---
        self._create_widgets()
        self._bind_events()

        # Handle window closing to release resources
        self.master.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Initial UI update
        self._update_slider_labels()
        self._toggle_bitrate_crf_options()
        self._toggle_audio_options()
        self._toggle_gpu_preset_options() # Call this initially to set correct states

    def _create_widgets(self):
        self.master.grid_rowconfigure(4, weight=1)
        self.master.grid_columnconfigure(0, weight=1) 
        self.master.grid_columnconfigure(1, weight=1) 
        self.master.grid_columnconfigure(2, weight=1) 

        input_output_frame = ttk.LabelFrame(self.master, text="File & Basic Settings")
        input_output_frame.grid(row=0, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        input_output_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(input_output_frame, text="Input Video:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        ttk.Entry(input_output_frame, textvariable=self.input_filepath, width=60).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(input_output_frame, text="Browse", command=self._browse_input_file).grid(row=0, column=2, padx=5, pady=5)

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

        ttk.Label(input_output_frame, text="Output Video:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        ttk.Entry(input_output_frame, textvariable=self.output_filepath, width=60).grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(input_output_frame, text="Save As", command=self._browse_output_file).grid(row=2, column=2, padx=5, pady=5)

        options_frame = ttk.LabelFrame(self.master, text="Advanced Output Options")
        options_frame.grid(row=1, column=0, columnspan=3, padx=10, pady=5, sticky="ew")
        options_frame.grid_columnconfigure(1, weight=1) 
        options_frame.grid_columnconfigure(2, weight=1) # Added column for Quarter Res radio button

        # Resolution options using Radiobuttons
        ttk.Label(options_frame, text="Output Resolution:").grid(row=0, column=0, sticky="e", padx=5, pady=2)
        ttk.Radiobutton(options_frame, text="Full", variable=self.resolution_choice, value="Full").grid(row=0, column=1, sticky="w", padx=5, pady=2)
        ttk.Radiobutton(options_frame, text="Half", variable=self.resolution_choice, value="Half").grid(row=0, column=2, sticky="w", padx=5, pady=2)
        ttk.Radiobutton(options_frame, text="Quarter", variable=self.resolution_choice, value="Quarter").grid(row=0, column=3, sticky="w", padx=5, pady=2)
        
        # Shifted rows for other options
        ttk.Checkbutton(options_frame, text="Remove Audio", variable=self.remove_audio, command=self._toggle_audio_options).grid(row=1, column=0, sticky="w", padx=5, pady=2) 
        ttk.Label(options_frame, text="Audio Bitrate:").grid(row=1, column=1, sticky="e", padx=5, pady=2) 
        self.audio_bitrate_menu = ttk.Combobox(options_frame, textvariable=self.audio_bitrate_choice, 
                                               values=["64k", "96k", "128k", "192k", "256k"], state="readonly", width=8)
        self.audio_bitrate_menu.grid(row=1, column=2, sticky="w", padx=5, pady=2) 
        self.audio_bitrate_menu.set("96k")

        ttk.Label(options_frame, text="Target Frame Rate:").grid(row=1, column=3, sticky="e", padx=5, pady=2) 
        self.framerate_menu = ttk.Combobox(options_frame, textvariable=self.target_framerate, 
                                           values=["Original", "30", "24", "15"], state="readonly", width=8)
        self.framerate_menu.grid(row=1, column=4, sticky="w", padx=5, pady=2) 
        self.framerate_menu.set("Original")

        ttk.Label(options_frame, text="FFmpeg Preset:").grid(row=4, column=0, sticky="e", padx=5, pady=2) 
        self.preset_menu = ttk.Combobox(options_frame, textvariable=self.ffmpeg_preset, 
                                           values=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"], state="readonly", width=10)
        self.preset_menu.grid(row=4, column=1, sticky="w", padx=5, pady=2) 
        self.preset_menu.set("medium")

        # CHANGED: Replaced Checkbutton for H.265 with Combobox for Video Codec
        ttk.Label(options_frame, text="Video Codec:").grid(row=4, column=2, sticky="e", padx=5, pady=2)
        self.video_codec_menu = ttk.Combobox(options_frame, textvariable=self.video_codec_choice,
                                             values=["H264", "H265", "AV1"], state="readonly", width=8)
        self.video_codec_menu.grid(row=4, column=3, sticky="w", padx=5, pady=2)
        self.video_codec_menu.set("H265") # Default selection
        self.video_codec_menu.bind("<<ComboboxSelected>>", lambda e: self._toggle_gpu_preset_options()) # Bind to update GPU/preset options

        # Shifted GPU Acceleration to row 6
        ttk.Label(options_frame, text="GPU Acceleration:").grid(row=4, column=4, sticky="e", padx=5, pady=2) 
        self.gpu_accel_menu = ttk.Combobox(options_frame, textvariable=self.gpu_accel_choice, 
                                           values=["None", "NVIDIA (NVENC)", "AMD (AMF)", "Intel (QSV)"], 
                                           state="readonly", width=15)
        self.gpu_accel_menu.grid(row=4, column=5, sticky="w", padx=5, pady=2) 
        self.gpu_accel_menu.set("None")
        self.gpu_accel_menu.bind("<<ComboboxSelected>>", lambda e: self._toggle_gpu_preset_options())

        self.canvas = tk.Canvas(self.master, width=640, height=360, bg="black", bd=2, relief="sunken")
        self.canvas.grid(row=2, column=0, columnspan=3, pady=10, padx=10, sticky="nsew")
        self.canvas.create_text(self.canvas.winfo_width()/2, self.canvas.winfo_height()/2,
                                    text="Load a video to see preview\nDrag on preview to select crop area",
                                    fill="white", font=("Arial", 16))

        trim_frame = ttk.LabelFrame(self.master, text="Video Trimming")
        trim_frame.grid(row=3, column=0, columnspan=3, padx=10, pady=5, sticky="ew")
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

        ttk.Button(trim_frame, text="Reset Crop Selection", command=self._reset_crop_selection).grid(row=2, column=1, pady=5, sticky="w")

        # Shifted process_frame to row 7
        process_frame = ttk.Frame(self.master)
        process_frame.grid(row=7, column=0, columnspan=3, pady=10, padx=10, sticky="ew")
        process_frame.grid_columnconfigure(0, weight=1)
        process_frame.grid_columnconfigure(1, weight=1)

        self.process_button = ttk.Button(process_frame, text="Trim & Compress Video", command=self._start_compression_thread,
                                             style="Accent.TButton")
        self.process_button.grid(row=0, column=0, pady=5, sticky="ew")

        self.cancel_button = ttk.Button(process_frame, text="Cancel", command=self.video_processor.cancel_compression, state=tk.DISABLED)
        self.cancel_button.grid(row=0, column=1, pady=5, padx=(5,0), sticky="ew")

        # Shifted progress_bar to row 8
        self.progress_bar = ttk.Progressbar(self.master, orient="horizontal", length=100, mode="determinate")
        self.progress_bar.grid(row=8, column=0, columnspan=3, pady=5, padx=10, sticky="ew")

        # Shifted status_label to row 9
        self.status_label = ttk.Label(self.master, text="", foreground="blue")
        self.status_label.grid(row=9, column=0, columnspan=3, pady=5)

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
        gpu_selected = self.gpu_accel_choice.get() != "None"
        selected_codec = self.video_codec_choice.get()

        if gpu_selected:
            self.preset_menu.config(state="disabled")
            # Update status label to reflect both GPU and selected codec
            self.status_label.config(text=f"Using GPU encoder ({self.gpu_accel_choice.get()}) for {selected_codec}. Presets are handled internally.")
        else:
            self.preset_menu.config(state="readonly")
            # Revert status label if no GPU is selected
            self.status_label.config(text=f"Using CPU encoder for {selected_codec}. Select a preset for quality/speed.")
            self._toggle_bitrate_crf_options() # Re-apply the CRF/Bitrate status if GPU is deselected

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
        
        fps_options = ["Original", "30", "24", "15"]
        if self.original_video_fps > 0:
            if int(self.original_video_fps) not in [30, 24, 15]:
                fps_options.insert(1, str(int(self.original_video_fps)))
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
            
            if canvas_w == 1 and canvas_h == 1:
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

        current_x = max(self.canvas_img_offset_x, min(event.x, self.canvas_img_offset_x + self.canvas_img_display_width))
        current_y = max(self.canvas_img_offset_y, min(event.y, self.canvas_img_offset_y + self.canvas_img_display_height))

        self.crop_end_x = current_x
        self.crop_end_y = current_y

        if self.crop_rectangle_id:
            self.canvas.coords(self.crop_rectangle_id, self.crop_start_x, self.crop_start_y, self.crop_end_x, self.crop_end_y)

    def _on_button_release(self, event):
        if self.crop_start_x == -1:
            return

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
           abs(self.crop_start_y - self.crop_end_y) >= 2:
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

        rel_x1_canvas = self.crop_start_x - self.canvas_img_offset_x
        rel_y1_canvas = self.crop_start_y - self.canvas_img_offset_y
        rel_x2_canvas = self.crop_end_x - self.canvas_img_offset_x
        rel_y2_canvas = self.crop_end_y - self.canvas_img_offset_y

        if self.canvas_img_display_width == 0 or self.canvas_img_display_height == 0:
            print("Warning: canvas_img_display_width or height is zero. Cannot calculate crop.")
            return None

        scale_x = self.original_video_width / self.canvas_img_display_width
        scale_y = self.original_video_height / self.canvas_img_display_height

        crop_x = int(rel_x1_canvas * scale_x)
        crop_y = int(rel_y1_canvas * scale_y)
        crop_width = int((rel_x2_canvas - rel_x1_canvas) * scale_x)
        crop_height = int((rel_y2_canvas - rel_y1_canvas) * scale_y)

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

    def _start_compression_thread(self):
        input_file = self.input_filepath.get()
        output_file = self.output_filepath.get()

        if not input_file or not os.path.exists(input_file):
            messagebox.showerror("Error", "Please select a valid input video file.")
            return
        if not output_file:
            messagebox.showerror("Error", "Please specify an output video file.")
            return
        
        start_time = self.start_scale.get()
        end_time = self.end_scale.get()

        if end_time <= start_time:
            messagebox.showerror("Error", "End time must be greater than start time.")
            return

        self.process_button.config(state=tk.DISABLED)
        self.cancel_button.config(state=tk.NORMAL)
        self.status_label.config(text="Initializing compression...")
        self.progress_bar.config(value=0, mode="determinate")

        compression_thread = threading.Thread(target=self._compress_video_task, 
                                              args=(input_file, output_file, start_time, end_time))
        compression_thread.daemon = True
        compression_thread.start()

    def _compress_video_task(self, input_file, output_file, start_time_sec, end_time_sec):
        duration_of_trim = end_time_sec - start_time_sec
        crop_params = self._get_ffmpeg_crop_params()

        total_passes = 2 if not self.use_crf.get() else 1

        success = True

        for pass_number in range(1, total_passes + 1):
            command = self.video_processor.build_ffmpeg_command(
                input_file, 
                output_file, 
                start_time_sec, 
                end_time_sec, 
                self.resolution_choice.get(), # Pass the selected resolution string
                self.use_crf.get(), 
                self.video_crf.get(), 
                self.target_size_mb.get(), 
                self.remove_audio,
                self.audio_bitrate_choice.get(), 
                self.target_framerate.get(), 
                self.ffmpeg_preset.get(), 
                self.video_codec_choice.get(), # CHANGED: Pass video_codec_choice.get()
                self.gpu_accel_choice.get(), 
                self.original_video_width, 
                self.original_video_height, 
                self.original_video_fps, 
                crop_params,
                pass_number,
                total_passes
            )

            if not command:
                success = False
                break
            
            # If target size and it's pass 1, use a temporary log file for FFmpeg to store stats
            log_file_path = None # Initialize log_file_path
            if not self.use_crf.get() and pass_number == 1:
                temp_dir = tempfile.gettempdir()
                log_file_path = os.path.join(temp_dir, "ffmpeg2pass-0.log")
                command.extend(["-passlogfile", log_file_path.replace("\\", "/")])
                
            success = self.video_processor.execute_ffmpeg_command(command, duration_of_trim, pass_number, total_passes)

            if not success:
                break # Stop if a pass fails or is cancelled
            
            if not self.use_crf.get() and pass_number == 1:
                # Clean up the log file after pass 1
                try:
                    if log_file_path and os.path.exists(log_file_path):
                        os.remove(log_file_path)
                    # Also remove .mbtree file if created by some FFmpeg versions
                    mbtree_file = log_file_path + ".mbtree"
                    if os.path.exists(mbtree_file):
                        os.remove(mbtree_file)
                except Exception as e:
                    print(f"Warning: Could not remove FFmpeg pass log file: {e}")

        self.master.after(0, lambda: self.process_button.config(state=tk.NORMAL))
        self.master.after(0, lambda: self.cancel_button.config(state=tk.DISABLED))
        
        if success:
            self.master.after(0, lambda: self.status_label.config(text=f"Compression complete! Output saved to: {output_file}"))
            self.master.after(0, lambda: self.progress_bar.config(value=100))
        else:
            if "Compression cancelled" not in self.status_label.cget("text"):
                self.master.after(0, lambda: self.status_label.config(text="Compression failed or was interrupted."))
            self.master.after(0, lambda: self.progress_bar.config(value=0))

    def _on_closing(self):
        if self.video_processor.ffmpeg_process and self.video_processor.ffmpeg_process.poll() is None:
            if messagebox.askokcancel("Quit", "A compression is in progress. Do you want to cancel and quit?"):
                self.video_processor.cancel_compression()
                if self.video_cap:
                    self.video_cap.release()
                self.master.destroy()
            else:
                # Do nothing, user decided not to quit
                pass
        else:
            if self.video_cap:
                self.video_cap.release()
            self.master.destroy()

# This is crucial: Set the AppID BEFORE creating the Tkinter root window
if sys.platform.startswith('win'):
    try:
        # It's good practice to set this outside the class if possible,
        # as it should ideally be set once per process.
        # Make sure this is unique for your application.
        # Use your company name, product name, etc.
        myappid = 'com.yourcompany.ShortyVideoEditor.1' # <-- CHANGE THIS TO SOMETHING UNIQUE!
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except AttributeError:
        # This will happen on non-Windows systems or older Windows versions
        pass
    except Exception as e:
        print(f"Error setting AppUserModelID outside class: {e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = VideoEditorApp(root)
    root.mainloop()

