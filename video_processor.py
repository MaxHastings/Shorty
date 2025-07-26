import subprocess
import re
import time
import os
import tempfile
import threading
from tkinter import messagebox # Import messagebox for showing errors in a GUI context
import sys

class VideoProcessor:
    def __init__(self, app_instance):
        """
        Initializes the VideoProcessor with a reference to the main application
        instance to allow for UI updates (status, progress bar).
        """
        self.app = app_instance
        self.ffmpeg_process = None
        self.current_pass = 0 # 0: idle, 1: pass1, 2: pass2
        self.ffmpeg_path = self._get_ffmpeg_path() # Get FFmpeg path once

    def _get_ffmpeg_path(self):
        """
        Determines the correct path to the FFmpeg executable, whether running
        as a PyInstaller bundled app or a regular Python script.
        Moved here to avoid circular dependency with utils if utils also imports VideoProcessor.
        """
        if getattr(sys, 'frozen', False):
            base_path = os.sys._MEIPASS # sys._MEIPASS is directly available on sys
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        ffmpeg_exe_name = "ffmpeg.exe" if os.sys.platform == "win32" else "ffmpeg"
        ffmpeg_path = os.path.join(base_path, ffmpeg_exe_name)
        
        if not os.path.exists(ffmpeg_path):
            try:
                subprocess.run([ffmpeg_exe_name, "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return ffmpeg_exe_name
            except (subprocess.CalledProcessError, FileNotFoundError):
                return None
            
        return ffmpeg_path # CORRECTED LINE HERE

    def calculate_bitrate(self, size_mb, duration_sec, audio_bitrate_kbps_str, remove_audio):
        if duration_sec <= 0:
            raise ValueError("Duration must be positive to calculate bitrate.")
        
        total_kbits = size_mb * 8192 # Convert MB to kilobits (1 MB = 8192 Kbits)

        audio_bitrate_kbps = 0
        if not remove_audio:
            try:
                audio_bitrate_kbps = int(audio_bitrate_kbps_str.replace('k', ''))
            except ValueError:
                audio_bitrate_kbps = 128 # Fallback if parsing fails

        # Account for potential overhead (container, metadata)
        overhead_factor = 0.08
        target_kbits_for_streams = total_kbits * (1 - overhead_factor)

        min_audio_kbits_needed = audio_bitrate_kbps * duration_sec
        
        if target_kbits_for_streams <= min_audio_kbits_needed:
            if target_kbits_for_streams > 0 and duration_sec > 0:
                target_video_kbits = target_kbits_for_streams * 0.7 
                target_audio_kbits = target_kbits_for_streams * 0.3
                
                audio_bitrate_kbps = int(target_audio_kbits / duration_sec)
                if audio_bitrate_kbps < 32 and not remove_audio: audio_bitrate_kbps = 32
                
                video_kbits_per_sec = (target_kbits_for_streams - (audio_bitrate_kbps * duration_sec)) / duration_sec
                video_bitrate_kbps = max(50, int(video_kbits_per_sec))
            else:
                video_bitrate_kbps = 50
                audio_bitrate_kbps = 32
        else:
            video_kbits_per_sec = (target_kbits_for_streams - (audio_bitrate_kbps * duration_sec)) / duration_sec
            video_bitrate_kbps = max(50, int(video_kbits_per_sec))
        
        print(f"Calculated Video Bitrate: {video_bitrate_kbps} kbps, Audio Bitrate: {audio_bitrate_kbps} kbps")
        return video_bitrate_kbps, audio_bitrate_kbps

    def build_ffmpeg_command(self, input_filepath, output_filepath, start_time_sec, end_time_sec, 
                             half_res_enabled, use_crf, video_crf, target_size_mb, 
                             remove_audio, audio_bitrate_choice, target_framerate, 
                             ffmpeg_preset, use_hevc, gpu_accel_choice, original_video_width, 
                             original_video_height, original_video_fps, crop_params, pass_number=1, total_passes=1):
        
        if not self.ffmpeg_path:
            messagebox.showerror("FFmpeg Error", "FFmpeg executable not found. Please ensure it's in your PATH or in the same directory as the script.")
            return None

        command = [self.ffmpeg_path, "-y"] # -y to overwrite output file without asking

        # Input file and trimming
        command.extend(["-ss", str(start_time_sec), "-i", input_filepath])
        if end_time_sec > start_time_sec:
            command.extend(["-t", str(end_time_sec - start_time_sec)])

        # Video Codec and Options
        video_codec = "libx265" if use_hevc else "libx264"
        command.extend(["-c:v", video_codec])

        # GPU Acceleration
        gpu_encoder = None
        if gpu_accel_choice == "NVIDIA (NVENC)":
            gpu_encoder = "h264_nvenc" if not use_hevc else "hevc_nvenc"
        elif gpu_accel_choice == "AMD (AMF)":
            gpu_encoder = "h264_amf" if not use_hevc else "hevc_amf"
        elif gpu_accel_choice == "Intel (QSV)":
            # For QSV, it's generally good practice to add -hwaccel auto before -i
            # However, for encoding, the encoder name itself implies QSV.
            # Example: -c:v h264_qsv or hevc_qsv
            gpu_encoder = "h264_qsv" if not use_hevc else "hevc_qsv"
            command.insert(1, "-hwaccel")
            command.insert(2, "auto")

        if gpu_encoder:
            command[command.index(video_codec)] = gpu_encoder # Replace CPU encoder with GPU encoder
            # GPU encoders usually have different preset options or none at all
            # For NVENC, typically '-preset' p1-p7 (performance to quality)
            # For QSV, '-preset' values like 'veryfast', 'medium', 'slow' might work.
            # For simplicity, we'll omit the general preset for GPU encoders unless specific ones are desired.
        else:
            # Apply CPU preset only if no GPU acceleration is chosen
            command.extend(["-preset", ffmpeg_preset])

        # Quality/Size Control
        if use_crf:
            command.extend(["-crf", video_crf])
        else:
            duration_of_trim = end_time_sec - start_time_sec
            try:
                target_size_mb_float = float(target_size_mb)
                video_bitrate_kbps, audio_bitrate_kbps = self.calculate_bitrate(
                    target_size_mb_float, duration_of_trim, audio_bitrate_choice, remove_audio.get()
                )
                command.extend(["-b:v", f"{video_bitrate_kbps}k"])
                
                # Two-pass encoding for target size
                if pass_number == 1:
                    command.extend(["-pass", "1", "-f", "mp4", os.devnull]) # Output to null for pass 1
                else: # pass_number == 2
                    command.extend(["-pass", "2"])
            except ValueError:
                messagebox.showerror("Input Error", "Invalid Target Size or Duration.")
                return None
        
        # Scaling and Cropping
        filters = []
        if crop_params:
            filters.append(crop_params)

        if half_res_enabled:
            # Calculate target resolution based on original aspect ratio
            # and ensuring dimensions are even
            target_width = original_video_width // 2
            target_height = original_video_height // 2
            
            # Ensure even dimensions
            target_width = (target_width // 2) * 2
            target_height = (target_height // 2) * 2
            
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
        if remove_audio.get():
            command.extend(["-an"]) # No audio
        else:
            command.extend(["-c:a", "aac", "-b:a", audio_bitrate_choice])

        # Output file
        if not (not use_crf and pass_number == 1): # Don't specify output for pass 1 of 2-pass encoding
            command.append(output_filepath)

        return command

    def execute_ffmpeg_command(self, command, duration_in_seconds, pass_number, total_passes):
        self.current_pass = pass_number
        pass_prefix = f"Pass {pass_number}/{total_passes}: "
        self.app.master.after(0, lambda: self.app.status_label.config(text=f"{pass_prefix}Starting FFmpeg..."))

        print(f"FFmpeg Command ({pass_prefix.strip()}):", " ".join(command))
        
        try:
            # Added `encoding='utf-8', errors='replace'` for better handling of diverse console output
            self.ffmpeg_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, encoding='utf-8', errors='replace')
        except FileNotFoundError:
            self.app.master.after(0, lambda: messagebox.showerror("Error", "FFmpeg executable not found. Please ensure it's in your PATH or in the same directory as the script."))
            return False
        except Exception as e:
            self.app.master.after(0, lambda: messagebox.showerror("Error", f"Failed to start FFmpeg process: {e}"))
            return False

        time_re = re.compile(r"time=(\d{2}):(\d{2}):(\d{2})\.\d+")
        
        start_progress_offset = (pass_number - 1) * (100 / total_passes)
        progress_scale_factor = (100 / total_passes) / duration_in_seconds if duration_in_seconds > 0 else 0

        # Create a temporary log file for stderr if needed (e.g., for debugging)
        # with tempfile.TemporaryFile(mode='w+', delete=False, encoding='utf-8') as log_file:
        #     print(f"FFmpeg stderr log: {log_file.name}")

        try:
            for line in iter(self.ffmpeg_process.stderr.readline, ''):
                # if log_file:
                #     log_file.write(line)
                #     log_file.flush()

                if self.ffmpeg_process.poll() is not None and not line: # Process terminated and no more lines to read
                    break

                match = time_re.search(line)
                if match:
                    hours = int(match.group(1))
                    minutes = int(match.group(2))
                    seconds = int(match.group(3))
                    current_time = hours * 3600 + minutes * 60 + seconds

                    if duration_in_seconds > 0:
                        current_pass_progress = (current_time * progress_scale_factor)
                        total_progress_percentage = start_progress_offset + current_pass_progress
                        total_progress_percentage = min(total_progress_percentage, start_progress_offset + (100 / total_passes) - 1)
                        
                        self.app.master.after(0, lambda p=total_progress_percentage: self.app.progress_bar.config(value=p))
                        self.app.master.after(0, lambda ct=current_time: self.app.status_label.config(text=f"{pass_prefix}Processing: {ct} / {int(duration_in_seconds)} seconds"))
                
                # Small delay to prevent UI freeze and excessive CPU usage from parsing
                time.sleep(0.005)

            # Ensure all remaining output is read if process exited
            self.ffmpeg_process.stderr.read() 

            self.ffmpeg_process.wait()
            
            if self.ffmpeg_process.returncode != 0:
                stderr_output = self.ffmpeg_process.stderr.read() # Read any remaining stderr output
                print(f"FFmpeg ({pass_prefix.strip()}) Error Output:\n{stderr_output}")
                self.app.master.after(0, lambda: self.app.status_label.config(text=f"{pass_prefix}Error: FFmpeg process failed. Check console for details."))
                if "Compression cancelled" not in self.app.status_label.cget("text"): # Avoid showing error if cancelled
                    self.app.master.after(0, lambda: messagebox.showerror("FFmpeg Error", f"FFmpeg process failed for {pass_prefix.strip()}. See console for details."))
                return False
            return True
        except Exception as e:
            print(f"An error occurred during FFmpeg execution: {e}")
            self.app.master.after(0, lambda: messagebox.showerror("Error", f"An unexpected error occurred during compression: {e}"))
            if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                self.ffmpeg_process.terminate()
            return False
        finally:
            if self.ffmpeg_process:
                self.ffmpeg_process.stdout.close()
                self.ffmpeg_process.stderr.close()
                self.ffmpeg_process = None # Clear the process handle
            self.current_pass = 0 # Reset pass state

    def cancel_compression(self):
        if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
            self.ffmpeg_process.terminate()
            self.app.master.after(0, lambda: self.app.status_label.config(text="Compression cancelled by user."))
            self.app.master.after(0, lambda: self.app.progress_bar.config(value=0))
            # Enable the process button and disable the cancel button
            self.app.master.after(0, lambda: self.app.process_button.config(state='!disabled'))
            self.app.master.after(0, lambda: self.app.cancel_button.config(state='disabled'))
            self.current_pass = 0