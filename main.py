import tkinter as tk
from gui import VideoEditorApp

def main():
    root = tk.Tk()
    app = VideoEditorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()