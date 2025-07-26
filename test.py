import sys
import threading
from pynput import keyboard
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QFileDialog, QMessageBox
from PyQt5.QtCore import Qt, QRect, QTimer, QPoint
from PyQt5.QtGui import QRegion, QPainter, QPen, QColor
import subprocess
import os
import signal

should_show_overlay = False
overlay_instance = None
ffmpeg_process = None # To hold the FFmpeg subprocess


class DimOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.showFullScreen()

        self.start_pos = None
        self.end_pos = None
        self.box_drawn = False
        self.recording_rect = QRect() # To store the final selected recording area

        self.record_button = QPushButton("Start Recording", self)
        self.record_button.hide()
        self.record_button.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: black;
                border: 2px solid red;
                padding: 5px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: red;
                color: white;
            }
        """)
        self.record_button.clicked.connect(self.toggle_record)

        self.recording = False
        self.output_filename = "" # To store the path of the temporary recording file

    def mousePressEvent(self, event):
        if not self.box_drawn:
            self.start_pos = event.pos()
            self.end_pos = self.start_pos

    def mouseMoveEvent(self, event):
        if not self.box_drawn and self.start_pos:
            self.end_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.start_pos and self.end_pos:
            self.recording_rect = QRect(self.start_pos, self.end_pos).normalized()
            self.box_drawn = True
            self.update()
            self.apply_hole_mask()
            self.show_record_button()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.recording:
                self.stop_ffmpeg_recording()
                QMessageBox.information(self, "Recording Aborted", "Recording was stopped due to ESC key press.")
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw dimmed full screen
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.setPen(Qt.NoPen)
        painter.drawRect(self.rect())

        if self.start_pos and self.end_pos:
            current_rect = self.recording_rect if self.box_drawn else QRect(self.start_pos, self.end_pos).normalized()

            # Draw red outline box
            if self.box_drawn:
                painter.setPen(QPen(Qt.red, 2))
            else:
                painter.setPen(QPen(Qt.red, 2, Qt.DashLine))

            painter.setBrush(Qt.NoBrush)
            painter.drawRect(current_rect)

    def apply_hole_mask(self):
        """Cut a real transparent hole in the dimmed window."""
        full_region = QRegion(self.rect())
        clear_rect = self.recording_rect
        hole_region = QRegion(clear_rect)
        self.setMask(full_region.subtracted(hole_region))

    def show_record_button(self):
        """Place record button to the right of the box."""
        button_x = self.recording_rect.right() + 10
        button_y = self.recording_rect.top()
        self.record_button.move(button_x, button_y)
        self.record_button.show()

    def toggle_record(self):
        """Toggle button text and start/stop recording."""
        self.recording = not self.recording
        if self.recording:
            self.record_button.setText("Stop Recording")
            self.start_ffmpeg_recording()
        else:
            self.record_button.setText("Start Recording")
            self.stop_ffmpeg_recording()

    def start_ffmpeg_recording(self):
        global ffmpeg_process

        x = self.recording_rect.x()
        y = self.recording_rect.y()
        width = self.recording_rect.width()
        height = self.recording_rect.height()

        # Temporary output file
        self.output_filename = os.path.join(os.path.expanduser("~"), "Desktop", "temp_recording.mp4")

        script_dir = os.path.dirname(os.path.abspath(__file__))
        ffmpeg_executable = os.path.join(script_dir, "ffmpeg.exe")

        if not os.path.exists(ffmpeg_executable):
            QMessageBox.critical(self, "Error", f"ffmpeg.exe not found at: {ffmpeg_executable}\nPlease ensure ffmpeg.exe is in the same directory as the script.")
            self.recording = False
            self.record_button.setText("Start Recording")
            return

        # --- FFmpeg command using gdigrab for screen capture ---
        # gdigrab is often more reliable for direct screen capture than dshow inputs that are virtual cameras.
        # This command also correctly maps video (from gdigrab) and audio (from dshow).
        
        ffmpeg_command = [
            ffmpeg_executable,
            "-f", "gdigrab",        # Input format for screen capture on Windows
            "-framerate", "30",     # Frame rate for screen capture
            "-offset_x", str(x),    # X coordinate of the top-left corner
            "-offset_y", str(y),    # Y coordinate of the top-left corner
            "-video_size", f"{width}x{height}", # Dimensions of the capture area
            "-i", "desktop",        # Input source for gdigrab (captures the entire desktop)

            # Audio Input (using dshow) - MAKE SURE THIS DEVICE NAME IS CORRECT
            # Based on your ffmpeg -list_devices output: "Analogue 1 + 2 (Focusrite USB Audio)"
            "-f", "dshow",
            "-i", "audio=Analogue 1 + 2 (Focusrite USB Audio)", # Your actual audio device

            # Video Encoding
            "-c:v", "libx264",
            "-preset", "ultrafast", # Adjust preset for speed vs. file size/quality
            
            # Audio Encoding
            "-c:a", "aac",
            "-b:a", "128k", # Audio bitrate

            # Map streams: 0:v:0 for video from the first input (gdigrab), 1:a:0 for audio from the second input (dshow)
            "-map", "0:v:0",
            "-map", "1:a:0",
            
            "-y",                   # Overwrite output files without asking
            self.output_filename
        ]

        # --- Alternative: Video only (no audio) if you prefer ---
        # ffmpeg_command = [
        #     ffmpeg_executable,
        #     "-f", "gdigrab",
        #     "-framerate", "30",
        #     "-offset_x", str(x),
        #     "-offset_y", str(y),
        #     "-video_size", f"{width}x{height}",
        #     "-i", "desktop",
        #     "-c:v", "libx264",
        #     "-preset", "ultrafast",
        #     "-y",
        #     self.output_filename
        # ]


        print(f"[*] FFmpeg Command: {' '.join(ffmpeg_command)}")

        try:
            ffmpeg_process = subprocess.Popen(
                ffmpeg_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW # Hide console window on Windows
            )
            print(f"[*] Started FFmpeg recording to: {self.output_filename}")
            print(f"[*] Recording region: X={x}, Y={y}, Width={width}, Height={height}")
        except FileNotFoundError:
            QMessageBox.critical(self, "Error", "FFmpeg executable not found. This should not happen if the check passed.")
            self.recording = False
            self.record_button.setText("Start Recording")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start FFmpeg: {e}\nCheck FFmpeg command, device names, and if OBS Virtual Camera is actively streaming (if you chose to use it).")
            self.recording = False
            self.record_button.setText("Start Recording")


    def stop_ffmpeg_recording(self):
        global ffmpeg_process
        if ffmpeg_process and ffmpeg_process.poll() is None: # Check if process is still running
            try:
                print("[*] Attempting to gracefully stop FFmpeg (sending 'q')...")
                ffmpeg_process.stdin.write(b'q\n')
                ffmpeg_process.stdin.flush()
                ffmpeg_process.stdin.close() # Close stdin after writing

                return_code = ffmpeg_process.wait(timeout=5)
                print(f"[*] FFmpeg exited with code: {return_code}")
                if return_code is not None and return_code != 0:
                    stderr_output = ffmpeg_process.stderr.read().decode(sys.getfilesystemencoding(), errors='ignore')
                    if stderr_output:
                        print(f"[*] FFmpeg stderr during stop: \n{stderr_output}")

            except subprocess.TimeoutExpired:
                print("[*] FFmpeg did not terminate gracefully after 'q'. Attempting Ctrl+C...")
                try:
                    ffmpeg_process.send_signal(signal.CTRL_C_EVENT if sys.platform == "win32" else signal.SIGINT)
                    return_code = ffmpeg_process.wait(timeout=5)
                    print(f"[*] FFmpeg exited with code after Ctrl+C: {return_code}")
                except subprocess.TimeoutExpired:
                    print("[*] FFmpeg still not stopped. Forcibly killing...")
                    ffmpeg_process.kill()
                except Exception as e:
                    print(f"[*] Error sending Ctrl+C or killing FFmpeg: {e}")

            except Exception as e:
                print(f"[*] Error during graceful FFmpeg stop attempt: {e}")
                print("[*] Attempting to forcibly kill FFmpeg as a fallback...")
                try:
                    if ffmpeg_process.poll() is None:
                        ffmpeg_process.kill()
                        print("[*] FFmpeg forcibly killed.")
                    else:
                        print("[*] FFmpeg already stopped or never started properly.")
                except Exception as kill_e:
                    print(f"[*] Error during forced FFmpeg kill: {kill_e}")
            finally:
                ffmpeg_process = None
                self.prompt_save_location()
        else:
            print("[*] No active FFmpeg process or process already terminated.")
            if os.path.exists(self.output_filename):
                 self.prompt_save_location()
            else:
                 QMessageBox.warning(self, "No Recording Found", "No active recording to stop and no temporary file found.")


    def prompt_save_location(self):
        if not self.output_filename or not os.path.exists(self.output_filename):
            QMessageBox.warning(self, "No Recording Found", "No recording file was found. It might not have been created or saved correctly.")
            return

        options = QFileDialog.Options()

        suggested_filename = os.path.basename(self.output_filename)

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Recorded Video",
            os.path.join(os.path.expanduser("~"), "Videos", suggested_filename),
            "Video Files (*.mp4 *.mkv);;All Files (*)",
            options=options
        )

        if save_path:
            try:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                os.rename(self.output_filename, save_path)
                QMessageBox.information(self, "Save Complete", f"Video saved successfully to:\n{save_path}")
                print(f"[*] Video saved to: {save_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error Saving", f"Failed to save video:\n{e}")
                if os.path.exists(self.output_filename):
                    os.remove(self.output_filename)
        else:
            QMessageBox.information(self, "Save Cancelled", "Video save was cancelled. Temporary file will be deleted.")
            if os.path.exists(self.output_filename):
                try:
                    os.remove(self.output_filename)
                    print(f"[*] Deleted temporary recording: {self.output_filename}")
                except Exception as e:
                    print(f"Error deleting temporary file: {e}")


def on_hotkey(key):
    global should_show_overlay
    try:
        if key == keyboard.Key.f3:
            should_show_overlay = True
    except AttributeError:
        pass


def run_app():
    global should_show_overlay, overlay_instance

    app = QApplication(sys.argv)

    def check_overlay():
        global should_show_overlay, overlay_instance
        if should_show_overlay:
            should_show_overlay = False
            if overlay_instance:
                if overlay_instance.recording:
                    overlay_instance.stop_ffmpeg_recording()
                    QMessageBox.warning(overlay_instance, "Recording Interrupted", "Previous recording was stopped due to new overlay activation.")
                overlay_instance.close()
            overlay_instance = DimOverlay()
            overlay_instance.show()

    timer = QTimer()
    timer.timeout.connect(check_overlay)
    timer.start(100)

    print("[*] Press F3 to activate overlay. Press ESC to close and stop recording.")
    app.exec_()


if __name__ == "__main__":
    listener = keyboard.Listener(on_press=on_hotkey)
    listener.start()
    run_app()