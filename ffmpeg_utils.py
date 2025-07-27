import subprocess
import os
import sys
from tkinter import messagebox # Still needed for showing FFmpeg path error

class FFmpegUtils:
    def __init__(self, app_instance=None): # Added app_instance for potential future use or consistency
        self.ffmpeg_path = self._get_ffmpeg_path()
        self.app = app_instance # Store app_instance if needed for UI updates from here

    def _get_ffmpeg_path(self):
        """
        Determines the correct path to the FFmpeg executable, whether running
        as a PyInstaller bundled app or a regular Python script.
        """
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS # sys._MEIPASS is directly available on sys
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        ffmpeg_exe_name = "ffmpeg.exe" if os.sys.platform == "win32" else "ffmpeg"
        ffmpeg_path = os.path.join(base_path, ffmpeg_exe_name)
        
        if not os.path.exists(ffmpeg_path):
            try:
                # Try running without a full path, assuming it's in system PATH
                subprocess.run([ffmpeg_exe_name, "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return ffmpeg_exe_name
            except (subprocess.CalledProcessError, FileNotFoundError):
                return None
            
        return ffmpeg_path

    def build_ffmpeg_command(self, input_filepath, output_filepath, start_time_sec, end_time_sec, 
                             resolution_choice, use_crf, video_crf, target_size_mb, 
                             remove_audio_var, audio_bitrate_choice, target_framerate, 
                             ffmpeg_preset, video_codec_choice, gpu_accel_choice, original_video_width, # Changed use_hevc to video_codec_choice
                             original_video_height, original_video_fps, crop_params, 
                             pass_number=1, total_passes=1, video_bitrate_kbps=None, audio_bitrate_kbps=None):
        
        if not self.ffmpeg_path:
            messagebox.showerror("FFmpeg Error", "FFmpeg executable not found. Please ensure it's in your PATH or in the same directory as the script.")
            return None

        command = [self.ffmpeg_path, "-y"] # -y to overwrite output file without asking

        # Input file and trimming
        command.extend(["-ss", str(start_time_sec), "-i", input_filepath])
        if end_time_sec > start_time_sec:
            command.extend(["-t", str(end_time_sec - start_time_sec)])

        # Determine Video Codec and Encoder (CPU or GPU)
        final_video_codec = ""
        apply_cpu_preset = True # Flag to control if -preset should be added for CPU encoders

        if gpu_accel_choice == "NVIDIA (NVENC)":
            # For NVIDIA, -hwaccel cuda is often used for decoding/filters,
            # but the NVENC encoder itself is directly specified.
            command.insert(1, "-hwaccel")
            command.insert(2, "cuda")
            
            if video_codec_choice == "H264":
                final_video_codec = "h264_nvenc"
            elif video_codec_choice == "H265":
                final_video_codec = "hevc_nvenc"
            elif video_codec_choice == "AV1":
                final_video_codec = "av1_nvenc"
            apply_cpu_preset = False # NVENC has its own internal presets/tuning

        elif gpu_accel_choice == "AMD (AMF)":
            # For AMD, dxva2 is a common hardware acceleration method on Windows
            command.insert(1, "-hwaccel")
            command.insert(2, "dxva2") 
            if video_codec_choice == "H264":
                final_video_codec = "h264_amf"
            elif video_codec_choice == "H265":
                final_video_codec = "hevc_amf"
            elif video_codec_choice == "AV1":
                final_video_codec = "av1_amf" # Assuming av1_amf is available for AMD
            apply_cpu_preset = False

        elif gpu_accel_choice == "Intel (QSV)":
            # For Intel QSV, specify -hwaccel qsv and -qsv_device
            command.insert(1, "-hwaccel")
            command.insert(2, "qsv")
            command.insert(3, "-qsv_device")
            command.insert(4, "hw") # Auto-detect QSV device
            if video_codec_choice == "H264":
                final_video_codec = "h264_qsv"
            elif video_codec_choice == "H265":
                final_video_codec = "hevc_qsv"
            elif video_codec_choice == "AV1":
                final_video_codec = "av1_qsv"
            apply_cpu_preset = False

        else: # No GPU acceleration chosen, use CPU encoders
            if video_codec_choice == "H264":
                final_video_codec = "libx264"
            elif video_codec_choice == "H265":
                final_video_codec = "libx265"
            elif video_codec_choice == "AV1":
                final_video_codec = "libsvtav1" # Use SVT-AV1 for software AV1 encoding
            # apply_cpu_preset remains True

        command.extend(["-c:v", final_video_codec])

        if apply_cpu_preset:
            command.extend(["-preset", ffmpeg_preset])
        # Note: For hardware encoders, specific presets like -preset:v for NVENC
        # or -quality for QSV might be needed for fine-tuning, but default
        # settings are often reasonable.

        # Quality/Size Control
        if use_crf:
            command.extend(["-crf", video_crf])
        else:
            # These bitrates will now be calculated by BitrateCalculator and passed in
            if video_bitrate_kbps is not None:
                command.extend(["-b:v", f"{video_bitrate_kbps}k"])
            
            # Two-pass encoding for target size
            if pass_number == 1:
                command.extend(["-pass", "1", "-f", "mp4", os.devnull]) # Output to null for pass 1
            else: # pass_number == 2
                command.extend(["-pass", "2"])
        
        # Scaling and Cropping
        filters = []
        if crop_params:
            filters.append(crop_params)

        # Handle resolution choice
        target_width = original_video_width
        target_height = original_video_height

        if resolution_choice == "Half":
            target_width = original_video_width // 2
            target_height = original_video_height // 2
        elif resolution_choice == "Quarter":
            target_width = original_video_width // 4
            target_height = original_video_height // 4
            
        # Ensure even dimensions for FFmpeg compatibility
        target_width = (target_width // 2) * 2
        target_height = (target_height // 2) * 2

        if resolution_choice != "Full": # Apply scale filter only if not full resolution
            filters.append(f"scale={target_width}:{target_height}")

        # Frame Rate
        if target_framerate != "Original":
            try:
                filters.append(f"fps={int(target_framerate)}")
            except ValueError:
                pass # Fallback to original if invalid value

        if filters:
            command.extend(["-vf", ",".join(filters)])
        
        # Audio Options
        if remove_audio_var.get(): # remove_audio_var is the tk.BooleanVar object
            command.extend(["-an"]) # No audio
        else:
            command.extend(["-c:a", "aac"])
            if audio_bitrate_kbps is not None:
                command.extend(["-b:a", f"{audio_bitrate_kbps}k"])
            else:
                command.extend(["-b:a", audio_bitrate_choice]) # Fallback if not calculated

        # Output file
        if not (not use_crf and pass_number == 1): # Don't specify output for pass 1 of 2-pass encoding
            command.append(output_filepath)

        return command
