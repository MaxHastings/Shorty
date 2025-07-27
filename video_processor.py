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
        self.ffmpeg_utils = FFmpegUtils(app_instance) # Pass app_instance to ffmpeg_utils
        self.bitrate_calculator = BitrateCalculator()
        self.ffmpeg_executor = FFmpegExecutor(app_instance) # Pass app_instance to executor

        # Expose ffmpeg_process and current_pass from FFmpegExecutor
        self.ffmpeg_process = self.ffmpeg_executor.ffmpeg_process # Will be updated by executor
        self.current_pass = self.ffmpeg_executor.current_pass # Will be updated by executor

    def build_ffmpeg_command(self, input_filepath, output_filepath, start_time_sec, end_time_sec, 
                             resolution_choice, use_crf, video_crf, target_size_mb, 
                             remove_audio_var, audio_bitrate_choice, target_framerate, 
                             ffmpeg_preset, video_codec_choice, gpu_accel_choice, original_video_width, 
                             original_video_height, original_video_fps, crop_params, 
                             pass_number=1, total_passes=1):
        """
        Builds the FFmpeg command based on GUI selections.
        This method acts as a wrapper to call ffmpeg_utils.build_ffmpeg_command
        and potentially calculate bitrates if target size is used.
        """
        video_bitrate_kbps = None
        audio_bitrate_kbps = None

        if not use_crf:
            # Calculate bitrates using the single calculate_bitrate method
            try:
                duration_sec = end_time_sec - start_time_sec
                video_bitrate_kbps, audio_bitrate_kbps = self.bitrate_calculator.calculate_bitrate(
                    float(target_size_mb), 
                    duration_sec, 
                    audio_bitrate_choice, 
                    remove_audio_var.get() # Pass the boolean value from the Tkinter variable
                )
                
                if video_bitrate_kbps <= 0:
                    self.app.master.after(0, lambda: self.app.status_label.config(text="Error: Calculated video bitrate is too low. Try a larger target size or lower audio bitrate."))
                    return None

            except ValueError as e:
                self.app.master.after(0, lambda: self.app.status_label.config(text=f"Error calculating bitrate: {e}"))
                return None

        # Call the ffmpeg_utils to build the actual command
        command = self.ffmpeg_utils.build_ffmpeg_command(
            input_filepath, 
            output_filepath, 
            start_time_sec, 
            end_time_sec, 
            resolution_choice, 
            use_crf, 
            video_crf, 
            target_size_mb, 
            remove_audio_var, 
            audio_bitrate_choice, 
            target_framerate, 
            ffmpeg_preset, 
            video_codec_choice, # Pass the selected video codec
            gpu_accel_choice, 
            original_video_width, 
            original_video_height, 
            original_video_fps, 
            crop_params,
            pass_number,
            total_passes,
            video_bitrate_kbps,
            audio_bitrate_kbps # Pass the calculated audio bitrate if applicable
        )
        return command

    def execute_ffmpeg_command(self, command, duration_of_trim, pass_number, total_passes):
        """
        Executes the FFmpeg command using the FFmpegExecutor.
        """
        return self.ffmpeg_executor.execute_ffmpeg_command(command, duration_of_trim, pass_number, total_passes)

    def cancel_compression(self):
        """
        Calls the FFmpegExecutor to cancel the ongoing compression.
        """
        self.ffmpeg_executor.cancel_compression()
