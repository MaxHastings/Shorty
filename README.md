# Shorty - A Video Trimmer + Compressor
This is a simple desktop application built with Python's Tkinter, OpenCV, and FFmpeg for trimming and compressing video files. It provides a user-friendly graphical interface to select video segments, apply optional cropping and half-resolution scaling, and compress videos to a target file size.

## Download EXE on Itch.io easier

https://maxhastings.itch.io/shorty

## Discord Group

https://discord.gg/ydByedFbvU

## Screenshots and Video

https://github.com/user-attachments/assets/a14836a5-bae3-40d3-8a0d-17e352ae43da

## Features
Video Trimming: Select start and end times to extract a specific portion of a video.

Video Compression: Compress videos to a desired target size in MB, automatically calculating the appropriate bitrate.

Video Preview: Live preview of the video frame at the selected start/end times.

Cropping Tool: Visually select a crop area directly on the video preview.

Half Resolution Option: Reduce video resolution by half for further compression.

Self-Contained Executable: Can be bundled into a single executable file using PyInstaller, eliminating the need for users to manually install FFmpeg.

## Requirements
To run the script directly, you need:

Python 3.x

tkinter (usually comes with Python)

opencv-python

Pillow (PIL fork)

ffmpeg (command-line tool) - Note: If you are using the PyInstaller bundled executable, you do not need to install FFmpeg separately.

Installation (for running the script directly)
Install Python: If you don't have Python, download and install it from python.org.

Install Libraries: Open your terminal or command prompt and run:

pip install opencv-python Pillow

Install FFmpeg:

Windows: Download a static build from ffmpeg.org and add its bin directory to your system's PATH environment variable.

macOS: Install via Homebrew: brew install ffmpeg

Linux: Install via your package manager (e.g., sudo apt install ffmpeg on Debian/Ubuntu).

## How to Run the Script
Save the provided Python code as video_editor.py.

Open your terminal or command prompt.

Navigate to the directory where you saved video_editor.py.

### Run the script:

python video_editor.py

## How to Build the Executable (for distribution)
This project is designed to be bundled into a single executable using PyInstaller, making it easy to share without requiring users to install Python or FFmpeg.

Install PyInstaller:

pip install pyinstaller

Download FFmpeg Binaries: Download the ffmpeg.exe and ffprobe.exe (if you plan to use ffprobe in the future) binaries for your operating system from ffmpeg.org.

Place Binaries: Put ffmpeg.exe and ffprobe.exe in the same directory as your video_editor.py script.

Run PyInstaller: Open your terminal or command prompt in the directory containing video_editor.py and the FFmpeg binaries, then run:

pyinstaller --onefile --windowed --add-binary "ffmpeg.exe;." --add-binary "ffprobe.exe;." video_editor.py

--onefile: Creates a single executable file.

--windowed: Prevents a console window from appearing when the GUI app runs.

--add-binary "ffmpeg.exe;.": Tells PyInstaller to include ffmpeg.exe in the bundle and place it in the root of the temporary extraction directory (.).

--add-binary "ffprobe.exe;.": Same for ffprobe.exe.

Find the Executable: The generated executable (video_editor.exe on Windows) will be located in the dist folder. You can now distribute this single file.

## Usage
Browse Input File: Click "Browse" next to "Input File" to select the video you want to trim/compress.

Set Target Size: Enter the desired output file size in megabytes (MB) in the "Target Size (MB)" field.

Browse Output File: Click "Browse" next to "Output File" to choose where to save the processed video and its filename.

Adjust Trim Times: Use the "Start Time (sec)" and "End Time (sec)" sliders to select the portion of the video you want to keep. The preview will update.

Crop Video (Optional):

Click and drag on the video preview canvas to draw a rectangle. This will define the cropping area.

Click "Reset Crop" to clear the selection.

Half Resolution (Optional): Check the "Half Res" checkbox to reduce the video's resolution by half.

Trim & Compress: Click the "Trim & Compress" button to start the processing. A message box will inform you when it begins and when it's finished (or if an error occurred).

## Troubleshooting
"FFmpeg not found" error when running the script directly: Ensure FFmpeg is installed and its bin directory is correctly added to your system's PATH environment variable.

"FFmpeg not found" error when running the bundled executable: This should be resolved by the --add-binary flags in the PyInstaller command and the get_ffmpeg_path() function in the script. Double-check that ffmpeg.exe was in the same directory as your script when you ran PyInstaller.

Video not loading: Ensure the input video file is not corrupted and is in a supported format (.mp4, .mov, .mkv, .avi).

Output file not created: Check the output path and filename for validity. Ensure you have write permissions to the chosen directory.

Application freezes during compression: Video compression can be CPU-intensive and take time, especially for large files. The application will appear unresponsive until FFmpeg finishes. Check the terminal output (if running the script directly) or the task manager for FFmpeg process activity.
