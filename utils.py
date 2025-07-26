import subprocess
import os
import sys

def get_ffmpeg_path():
    """
    Determines the correct path to the FFmpeg executable, whether running
    as a PyInstaller bundled app or a regular Python script.
    """
    if getattr(sys, 'frozen', False):
        # When running as a PyInstaller bundled app, _MEIPASS is the path to the temp folder
        base_path = sys._MEIPASS
    else:
        # When running as a regular Python script, get the directory of the current file
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