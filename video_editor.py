import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import cv2
from PIL import Image, ImageTk
import sys
import threading
import time # For potential progress updates (though not fully implemented yet)

# Helper function (can be outside class as it's general purpose)
def get_ffmpeg_path():
    """
    Determines the correct path to the FFmpeg executable, whether running
    as a PyInstaller bundled app or a regular Python script.
    """
    if getattr(sys, 'frozen', False):
        # If running as a bundled executable (e.g., .exe from PyInstaller)
        # sys._MEIPASS is the path to the temporary folder where PyInstaller extracts bundled files
        base_path = sys._MEIPASS
    else:
        # If running as a normal Python script
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    # Construct the full path to ffmpeg.exe or ffmpeg (for Linux/macOS)
    ffmpeg_exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    ffmpeg_path = os.path.join(base_path, ffmpeg_exe_name)
    
    # Fallback for common development setups (e.g., if ffmpeg is in system PATH or /usr/local/bin)
    # This might be useful during development but for bundling, rely on the above.
    if not os.path.exists(ffmpeg_path):
        try:
            # Check if it's in PATH
            subprocess.run([ffmpeg_exe_name, "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return ffmpeg_exe_name # Use the name directly if found in PATH
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None # Not found
            
    return ffmpeg_path

class VideoEditorApp:
    def __init__(self, master):
        self.master = master
        master.title("Video Trimmer + Compressor")

        # --- Model/State Variables ---
        self.input_filepath = tk.StringVar()
        self.target_size_mb = tk.StringVar(value="10")
        self.output_filepath = tk.StringVar(value="output_trimmed.mp4")
        self.half_res_enabled = tk.BooleanVar(value=False)

        # Video capture object
        self.video_cap = None
        self.video_duration_sec = 0
        self.original_video_width = 0
        self.original_video_height = 0

        # Cropping state
        self.crop_start_x = -1
        self.crop_start_y = -1
        self.crop_end_x = -1
        self.crop_end_y = -1
        self.crop_rectangle_id = None # Canvas item ID
        self.displayed_frame_on_canvas = None # PIL/Pillow PhotoImage for canvas
        self.current_preview_cv_frame = None # OpenCV frame (resized)

        # Canvas image display properties (to map canvas coords to video coords)
        self.canvas_img_offset_x = 0
        self.canvas_img_offset_y = 0
        self.canvas_img_display_width = 0
        self.canvas_img_display_height = 0

        # --- GUI Setup ---
        self._create_widgets()
        self._bind_events()

        # Handle window closing to release resources
        self.master.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Initial UI update
        self._update_slider_labels()

    def _create_widgets(self):
        # Configure grid weights for main window for resizing
        self.master.grid_rowconfigure(1, weight=1) # Row containing the canvas
        self.master.grid_columnconfigure(0, weight=1) # Column 0 (spanned by others)
        self.master.grid_columnconfigure(1, weight=1) # Column 1 (spanned by others)
        self.master.grid_columnconfigure(2, weight=1) # Column 2 (spanned by others)

        # Input/Output Frame
        input_output_frame = ttk.LabelFrame(self.master, text="File & Settings")
        input_output_frame.grid(row=0, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        input_output_frame.grid_columnconfigure(1, weight=1) # Allow entry field to expand

        ttk.Label(input_output_frame, text="Input Video:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        ttk.Entry(input_output_frame, textvariable=self.input_filepath, width=60).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(input_output_frame, text="Browse", command=self._browse_input_file).grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(input_output_frame, text="Target Size (MB):").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        ttk.Entry(input_output_frame, textvariable=self.target_size_mb, width=10).grid(row=1, column=1, sticky="w", padx=5, pady=5)

        ttk.Label(input_output_frame, text="Output Video:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        ttk.Entry(input_output_frame, textvariable=self.output_filepath, width=60).grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(input_output_frame, text="Save As", command=self._browse_output_file).grid(row=2, column=2, padx=5, pady=5)

        ttk.Checkbutton(input_output_frame, text="Half Resolution Output", variable=self.half_res_enabled).grid(row=3, column=1, sticky="w", padx=5, pady=5)

        # Video Preview Canvas
        self.canvas = tk.Canvas(self.master, width=640, height=360, bg="black", bd=2, relief="sunken") # Increased canvas size
        self.canvas.grid(row=1, column=0, columnspan=3, pady=10, padx=10, sticky="nsew")
        self.canvas.create_text(self.canvas.winfo_width()/2, self.canvas.winfo_height()/2,
                                text="Load a video to see preview\nDrag on preview to select crop area",
                                fill="white", font=("Arial", 16))

        # Trimming Controls Frame
        trim_frame = ttk.LabelFrame(self.master, text="Video Trimming")
        trim_frame.grid(row=2, column=0, columnspan=3, padx=10, pady=5, sticky="ew")
        trim_frame.grid_columnconfigure(1, weight=1) # Allow slider to expand

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

        # Process Button
        self.process_button = ttk.Button(self.master, text="Trim & Compress Video", command=self._start_compression_thread,
                                         style="Accent.TButton") # A custom style might be defined
        self.process_button.grid(row=3, column=0, columnspan=3, pady=15)

        # Status Label (for progress messages)
        self.status_label = ttk.Label(self.master, text="", foreground="blue")
        self.status_label.grid(row=4, column=0, columnspan=3, pady=5)

    def _bind_events(self):
        self.canvas.bind("<ButtonPress-1>", self._on_button_press)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_button_release)
        # Bind resize event to canvas to dynamically update preview
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _browse_input_file(self):
        filepath = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi")])
        if filepath:
            self.input_filepath.set(filepath)
            self._load_video(filepath)

    def _browse_output_file(self):
        filepath = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4 files", "*.mp4")])
        if filepath:
            self.output_filepath.set(filepath)

    def _load_video(self, path):
        if self.video_cap is not None:
            self.video_cap.release()
            self.video_cap = None # Ensure it's explicitly None

        self.video_cap = cv2.VideoCapture(path)
        if not self.video_cap.isOpened():
            messagebox.showerror("Error", "Unable to open video.")
            self.input_filepath.set("") # Clear path if load fails
            return

        fps = self.video_cap.get(cv2.CAP_PROP_FPS)
        frame_count = self.video_cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self.original_video_width = int(self.video_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.original_video_height = int(self.video_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.video_duration_sec = int(frame_count / fps)

        # Update slider ranges
        self.start_scale.config(to=self.video_duration_sec)
        self.end_scale.config(to=self.video_duration_sec)

        # Set initial slider values
        self.start_scale.set(0)
        self.end_scale.set(self.video_duration_sec)

        self._reset_crop_selection()
        self._update_frame_preview(0) # Show the start frame
        self._update_slider_labels()

    def _update_frame_preview(self, current_time_sec):
        if self.video_cap is None:
            return

        # Ensure current_time_sec is within video bounds
        current_time_sec = max(0, min(current_time_sec, self.video_duration_sec))

        self.video_cap.set(cv2.CAP_PROP_POS_MSEC, current_time_sec * 1000)
        ret, frame = self.video_cap.read()

        if ret:
            # Get current canvas dimensions for dynamic resizing
            canvas_w = self.canvas.winfo_width()
            canvas_h = self.canvas.winfo_height()
            
            # Fallback for initial state before widgets are drawn
            if canvas_w == 1 and canvas_h == 1:
                canvas_w = 640 # Use the default width defined in _create_widgets
                canvas_h = 360 # Use the default height defined in _create_widgets

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
            self._draw_crop_rectangle() # Redraw crop rectangle on new frame
        else:
            self.canvas.delete("all")
            self.canvas.create_text(self.canvas.winfo_width()/2, self.canvas.winfo_height()/2,
                                    text="Failed to load frame", fill="white", font=("Arial", 16))

    def _on_canvas_configure(self, event):
        """
        Handles the canvas resize event.
        Redraws the current video frame to fit the new canvas dimensions.
        """
        # Event provides new width and height
        # new_canvas_width = event.width
        # new_canvas_height = event.height

        if self.video_cap and self.video_cap.isOpened():
            # Re-render the current frame to fit the new canvas size
            self._update_frame_preview(self.start_scale.get()) # Or whatever time you want to show
        else:
            # If no video is loaded, just clear the canvas and show the default text
            self.canvas.delete("all")
            # Using event.width/height to center text correctly on new canvas size
            self.canvas.create_text(event.width / 2, event.height / 2,
                                    text="Load a video to see preview\nDrag on preview to select crop area",
                                    fill="white", font=("Arial", 16))


    def _on_slider_move(self, value):
        # The `value` argument from scale is a string, convert to float
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

        # Ensure click is within the displayed image bounds
        if not (self.canvas_img_offset_x <= event.x <= self.canvas_img_offset_x + self.canvas_img_display_width and
                self.canvas_img_offset_y <= event.y <= self.canvas_img_offset_y + self.canvas_img_display_height):
            return

        self.crop_start_x = event.x
        self.crop_start_y = event.y
        self.crop_end_x = event.x # Initialize end point to start point
        self.crop_end_y = event.y

        if self.crop_rectangle_id:
            self.canvas.delete(self.crop_rectangle_id)

        self.crop_rectangle_id = self.canvas.create_rectangle(
            self.crop_start_x, self.crop_start_y, self.crop_end_x, self.crop_end_y,
            outline="red", width=2, dash=(5, 2)
        )

    def _on_mouse_drag(self, event):
        if self.crop_start_x == -1: # No drag started
            return

        # Constrain mouse position to the image area on canvas
        current_x = max(self.canvas_img_offset_x, min(event.x, self.canvas_img_offset_x + self.canvas_img_display_width))
        current_y = max(self.canvas_img_offset_y, min(event.y, self.canvas_img_offset_y + self.canvas_img_display_height))

        self.crop_end_x = current_x
        self.crop_end_y = current_y

        if self.crop_rectangle_id:
            self.canvas.coords(self.crop_rectangle_id, self.crop_start_x, self.crop_start_y, self.crop_end_x, self.crop_end_y)

    def _on_button_release(self, event):
        if self.crop_start_x == -1: # No drag started
            return

        # Finalize and sanitize coordinates
        x1_raw = max(self.canvas_img_offset_x, min(self.crop_start_x, self.canvas_img_offset_x + self.canvas_img_display_width))
        y1_raw = max(self.canvas_img_offset_y, min(self.crop_start_y, self.canvas_img_offset_y + self.canvas_img_display_height))
        x2_raw = max(self.canvas_img_offset_x, min(self.crop_end_x, self.canvas_img_offset_x + self.canvas_img_display_width))
        y2_raw = max(self.canvas_img_offset_y, min(self.crop_end_y, self.canvas_img_offset_y + self.canvas_img_display_height))

        # Ensure (x1,y1) is top-left and (x2,y2) is bottom-right of the selection
        self.crop_start_x = min(x1_raw, x2_raw)
        self.crop_start_y = min(y1_raw, y2_raw)
        self.crop_end_x = max(x1_raw, x2_raw)
        self.crop_end_y = max(y1_raw, y2_raw)

        # Redraw the rectangle with final, cleaned coordinates
        self._draw_crop_rectangle()
        print(f"Crop selection (canvas pixels): ({self.crop_start_x}, {self.crop_start_y}) to ({self.crop_end_x}, {self.crop_end_y})")

    def _draw_crop_rectangle(self):
        if self.crop_rectangle_id:
            self.canvas.delete(self.crop_rectangle_id)
            self.crop_rectangle_id = None # Clear ID before (re)creation

        if self.crop_start_x != -1 and self.crop_end_x != -1:
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
           abs(self.crop_start_y - self.crop_end_y) < 2: # Require at least 2 pixels for a valid crop
            return None # No valid crop selected or too small

        # Convert canvas coordinates relative to the *displayed image* on canvas
        # Then scale to original video dimensions
        rel_x1_canvas = self.crop_start_x - self.canvas_img_offset_x
        rel_y1_canvas = self.crop_start_y - self.canvas_img_offset_y
        rel_x2_canvas = self.crop_end_x - self.canvas_img_offset_x
        rel_y2_canvas = self.crop_end_y - self.canvas_img_offset_y

        # Handle cases where `canvas_img_display_width` or `height` might be 0
        # due to some edge cases or before image is fully loaded.
        if self.canvas_img_display_width == 0 or self.canvas_img_display_height == 0:
             # Fallback: if preview size is invalid, assume no valid crop
             print("Warning: canvas_img_display_width or height is zero. Cannot calculate crop.")
             return None

        scale_x = self.original_video_width / self.canvas_img_display_width
        scale_y = self.original_video_height / self.canvas_img_display_height

        # Calculate crop parameters for FFmpeg (integer pixels)
        crop_x = int(rel_x1_canvas * scale_x)
        crop_y = int(rel_y1_canvas * scale_y)
        crop_width = int((rel_x2_canvas - rel_x1_canvas) * scale_x)
        crop_height = int((rel_y2_canvas - rel_y1_canvas) * scale_y)

        # Ensure dimensions are positive and within original video bounds
        crop_x = max(0, crop_x)
        crop_y = max(0, crop_y)
        crop_width = max(2, min(crop_width, self.original_video_width - crop_x)) # Min 2 pixels
        crop_height = max(2, min(crop_height, self.original_video_height - crop_y)) # Min 2 pixels

        # Ensure crop coordinates and dimensions are even for H.264 compatibility
        # FFmpeg often prefers even dimensions for crop and output resolution.
        # This is a common requirement for video codecs.
        crop_x = (crop_x // 2) * 2
        crop_y = (crop_y // 2) * 2
        crop_width = (crop_width // 2) * 2
        crop_height = (crop_height // 2) * 2

        print(f"Calculated FFmpeg crop: w={crop_width}, h={crop_height}, x={crop_x}, y={crop_y}")
        return f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y}"

    # --- Compression Logic ---
    def _calculate_bitrate(self, size_mb, duration_sec):
        """Calculates video and audio bitrates based on target size and duration."""
        if duration_sec <= 0:
            raise ValueError("Duration must be positive to calculate bitrate.")
        
        # Convert MB to kilobits (1 MB = 8192 kilobits)
        total_kbits = size_mb * 8192
        
        # Assume a standard audio bitrate for common quality (e.g., 128 kbps)
        # You could also try to extract original audio bitrate or make it configurable
        audio_bitrate_kbps = 128 
        
        # Calculate available video kbits for the given duration
        # Subtract total audio kbits from total_kbits
        video_kbits_per_sec = (total_kbits - (audio_bitrate_kbps * duration_sec)) / duration_sec
        
        # Ensure video bitrate is not negative or too low
        video_bitrate_kbps = max(100, int(video_kbits_per_sec)) # Minimum 100 kbps for video
        
        return video_bitrate_kbps, audio_bitrate_kbps

    def _start_compression_thread(self):
        """Starts the compression in a separate thread to keep the GUI responsive."""
        # Disable button and update status message on the main thread
        self.process_button.config(state=tk.DISABLED)
        self.status_label.config(text="Processing video... Please wait.")
        
        # Start the long-running task in a new thread
        compression_thread = threading.Thread(target=self._compress_video_task)
        compression_thread.daemon = True # Allow the app to close even if thread is running
        compression_thread.start()

    def _compress_video_task(self):
        """The actual compression logic, run in a separate thread."""
        try:
            input_file = self.input_filepath.get()
            start_sec = int(self.start_scale.get())
            end_sec = int(self.end_scale.get())
            target_size_mb = int(self.target_size_mb.get())
            output_file = self.output_filepath.get()

            # --- Input Validation ---
            if not input_file or not os.path.exists(input_file):
                raise ValueError("Please select a valid input video file.")
            if not output_file:
                raise ValueError("Please specify an output file name.")
            if not output_file.lower().endswith(".mp4"):
                # Automatically add .mp4 if missing for consistency
                output_file += ".mp4" 
                self.master.after(0, lambda: self.output_filepath.set(output_file)) # Update GUI on main thread

            duration_sec = end_sec - start_sec
            if duration_sec <= 0:
                raise ValueError("End time must be after start time and duration must be positive.")
            if target_size_mb <= 0:
                raise ValueError("Target size must be a positive number.")

            v_bitrate, a_bitrate = self._calculate_bitrate(target_size_mb, duration_sec)

            ffmpeg_executable = get_ffmpeg_path()
            if ffmpeg_executable is None:
                raise FileNotFoundError("FFmpeg executable not found. Please ensure it's in the same directory as the script or in your system's PATH.")
            if not os.path.exists(ffmpeg_executable) and not (sys.platform != "win32" and os.path.basename(ffmpeg_executable) == "ffmpeg"):
                # This extra check handles cases where get_ffmpeg_path might return "ffmpeg" (for PATH)
                # but it's not actually found by os.path.exists if not full path
                # Subprocess will fail later, but this gives a clearer error upfront.
                raise FileNotFoundError(f"FFmpeg executable not found at: {ffmpeg_executable}")

            cmd = [
                ffmpeg_executable, '-y', # Overwrite output file without asking
                '-ss', str(start_sec),
                '-i', input_file,
                '-t', str(duration_sec),
                '-avoid_negative_ts', 'make_zero', # Handles negative timestamps if -ss seeks past start
                '-c:v', 'libx264',
                '-preset', 'medium', # Good balance of speed and compression. Use 'fast' for quicker results.
                '-b:v', f'{v_bitrate}k',
                '-minrate', f'{v_bitrate}k',
                '-maxrate', f'{v_bitrate}k',
                '-bufsize', f'{v_bitrate * 2}k',
            ]

            video_filters = []
            if self.half_res_enabled.get():
                video_filters.append('scale=iw/2:ih/2')

            crop_filter = self._get_ffmpeg_crop_params()
            if crop_filter:
                video_filters.append(crop_filter)

            if video_filters:
                # Add '-vf' (video filter) flag only if filters are present
                cmd += ['-vf', ','.join(video_filters)]

            cmd += [
                # If you use -crf, -b:v acts as a max bitrate. Otherwise, it's the target.
                # It's generally recommended to use -crf for quality and -b:v as a max if needed.
                # For target size, 2-pass encoding is best, but more complex for a simple GUI.
                # So, we'll stick with -b:v for now, as originally planned by calculate_bitrate.
                # If you want to use CRF, remove -b:v.
                '-b:v', f'{v_bitrate}k',
                '-c:a', 'aac',
                '-b:a', f'{a_bitrate}k',
                '-movflags', '+faststart', # Optimizes for web streaming
                output_file
            ]

            print("FFmpeg command:", " ".join(cmd))
            
            self.master.after(0, lambda: self.status_label.config(text="Starting FFmpeg..."))

            # Popen without text=True initially for potential binary output, then decode stderr
            # For FFmpeg, stderr often contains progress, stdout is usually empty.
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate() # Wait for the process to finish
            
            # Decode stderr only after process finishes, as it might contain progress updates
            stderr_decoded = stderr.decode(errors='ignore') # Ignore decoding errors for robustness

            if process.returncode == 0:
                self.master.after(0, lambda: messagebox.showinfo("Success", f"Video saved to {output_file}"))
                self.master.after(0, lambda: self.status_label.config(text=f"Successfully processed to {output_file}"))
            else:
                self.master.after(0, lambda: messagebox.showerror("FFmpeg Error", f"FFmpeg failed with error:\n{stderr_decoded}"))
                self.master.after(0, lambda: self.status_label.config(text="FFmpeg failed! Check error details."))

        except ValueError as ve:
            self.master.after(0, lambda: messagebox.showerror("Input Error", str(ve)))
            self.master.after(0, lambda: self.status_label.config(text=f"Error: {ve}"))
        except FileNotFoundError as fnfe:
            self.master.after(0, lambda: messagebox.showerror("File Not Found", str(fnfe)))
            self.master.after(0, lambda: self.status_label.config(text=f"Error: {fnfe}"))
        except Exception as e:
            self.master.after(0, lambda: messagebox.showerror("An Unexpected Error Occurred", str(e)))
            self.master.after(0, lambda: self.status_label.config(text=f"An unexpected error occurred: {e}"))
        finally:
            self.master.after(0, lambda: self.process_button.config(state=tk.NORMAL)) # Re-enable button

    def _on_closing(self):
        """Releases video capture object and destroys the window on close."""
        if self.video_cap is not None:
            self.video_cap.release()
        self.master.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    
    # Optional: Apply a ttk theme for a more modern look
    # Requires a .tcl theme file (e.g., 'azure.tcl') in the same directory.
    # You can find such files in projects like https://github.com/rdbende/tkinter-themes
    try:
        # Get the directory of the current script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        theme_path = os.path.join(script_dir, "azure.tcl")
        if os.path.exists(theme_path):
            root.tk.call("source", theme_path)
            ttk.Style().theme_use('azure')
            # Set a custom style for the main button
            ttk.Style().configure('Accent.TButton', background='#4CAF50', foreground='white', font=('Arial', 12, 'bold'))
            ttk.Style().map('Accent.TButton', 
                            background=[('active', '#5CB85C'), ('pressed', '#398439')],
                            foreground=[('active', 'white'), ('pressed', 'white')])
        else:
            print("Azure theme file (azure.tcl) not found. Using default ttk theme.")
            ttk.Style().theme_use('default') # Fallback to default ttk theme
    except Exception as e:
        print(f"Error loading theme: {e}. Using default ttk theme.")
        ttk.Style().theme_use('default') # Fallback to default ttk theme

    app = VideoEditorApp(root)
    root.mainloop()