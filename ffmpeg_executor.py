import subprocess
import re
import time
import os
import tempfile
import threading
from tkinter import messagebox

class FFmpegExecutor:
    def __init__(self, app_instance):
        self.app = app_instance
        self.ffmpeg_process = None
        self.current_pass = 0 # 0: idle, 1: pass1, 2: pass2

    def execute_ffmpeg_command(self, command, duration_in_seconds, pass_number, total_passes):
        self.current_pass = pass_number
        pass_prefix = f"Pass {pass_number}/{total_passes}: "
        self.app.master.after(0, lambda: self.app.status_label.config(text=f"{pass_prefix}Starting FFmpeg..."))

        print(f"FFmpeg Command ({pass_prefix.strip()}):", " ".join(command))
        
        try:
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

        try:
            for line in iter(self.ffmpeg_process.stderr.readline, ''):
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
                        # Cap progress within the current pass's segment (e.g., 0-50% for pass 1)
                        total_progress_percentage = start_progress_offset + current_pass_progress
                        total_progress_percentage = min(total_progress_percentage, start_progress_offset + (100 / total_passes) - 0.1) # Keep it slightly below 100% of the pass

                        self.app.master.after(0, lambda p=total_progress_percentage: self.app.progress_bar.config(value=p))
                        self.app.master.after(0, lambda ct=current_time: self.app.status_label.config(text=f"{pass_prefix}Processing: {ct} / {int(duration_in_seconds)} seconds"))
                
                time.sleep(0.005) # Small delay to prevent UI freeze and excessive CPU usage from parsing

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