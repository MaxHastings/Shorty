import os
import tempfile
from tkinter import messagebox # Import messagebox for showing errors in a GUI context

# Import the new modules
from ffmpeg_utils import FFmpegUtils
from bitrate_calculator import BitrateCalculator
from ffmpeg_executor import FFmpegExecutor

class VideoProcessor:
    def __init__(self, app_instance):
        """
        Initializes the VideoProcessor with a reference to the main application
        instance to allow for UI updates (status, progress bar).
        """
        self.app = app_instance
        
        # Instantiate the helper classes
        self.ffmpeg_utils = FFmpegUtils()
        self.bitrate_calculator = BitrateCalculator()
        self.ffmpeg_executor = FFmpegExecutor(app_instance) # Pass app_instance to executor

        # Expose ffmpeg_process and current_pass from FFmpegExecutor
        self.ffmpeg_process = self.ffmpeg_executor.ffmpeg_process # Will be updated by executor
        self.current_pass = self.ffmpeg_executor.current_pass # Will be updated by executor

    def build_ffmpeg_command(self, input_filepath, output_filepath, start_time_sec, end_time_sec, 
                             half_res_enabled, use_crf, video_crf, target_size_mb, 
                             remove_audio_var, audio_bitrate_choice, target_framerate, 
                             ffmpeg_preset, use_hevc, gpu_accel_choice, original_video_width, 
                             original_video_height, original_video_fps, crop_params, pass_number=1, total_passes=1):
        
        video_bitrate_kbps = None
        audio_bitrate_kbps = None

        if not use_crf:
            duration_of_trim = end_time_sec - start_time_sec
            try:
                target_size_mb_float = float(target_size_mb)
                video_bitrate_kbps, audio_bitrate_kbps = self.bitrate_calculator.calculate_bitrate(
                    target_size_mb_float, duration_of_trim, audio_bitrate_choice, remove_audio_var.get()
                )
            except ValueError as e:
                messagebox.showerror("Input Error", f"Invalid Target Size or Duration: {e}")
                return None
        
        return self.ffmpeg_utils.build_ffmpeg_command(
            input_filepath, output_filepath, start_time_sec, end_time_sec, 
            half_res_enabled, use_crf, video_crf, target_size_mb, 
            remove_audio_var, audio_bitrate_choice, target_framerate, 
            ffmpeg_preset, use_hevc, gpu_accel_choice, original_video_width, 
            original_video_height, original_video_fps, crop_params, 
            pass_number, total_passes, video_bitrate_kbps, audio_bitrate_kbps
        )

    def execute_ffmpeg_command(self, command, duration_in_seconds, pass_number, total_passes):
        # Update self.ffmpeg_process and self.current_pass to reflect executor's state
        success = self.ffmpeg_executor.execute_ffmpeg_command(command, duration_in_seconds, pass_number, total_passes)
        self.ffmpeg_process = self.ffmpeg_executor.ffmpeg_process
        self.current_pass = self.ffmpeg_executor.current_pass
        return success

    def cancel_compression(self):
        self.ffmpeg_executor.cancel_compression()
        self.ffmpeg_process = self.ffmpeg_executor.ffmpeg_process # Update after cancellation
        self.current_pass = self.ffmpeg_executor.current_pass # Update after cancellation