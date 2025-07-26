import sys
import threading
from pynput import keyboard
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QRect, QTimer, QPoint
from PyQt5.QtGui import QRegion
from PyQt5.QtGui import QPainter, QPen, QColor


should_show_overlay = False
overlay_instance = None


class DimOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.showFullScreen()

        self.start = None
        self.end = None
        self.box_drawn = False

    def mousePressEvent(self, event):
        if not self.box_drawn:
            self.start = event.pos()
            self.end = self.start

    def mouseMoveEvent(self, event):
        if not self.box_drawn and self.start:
            self.end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.start and self.end:
            self.box_drawn = True
            self.update()
            self.apply_hole_mask()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw dimmed full screen
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.setPen(Qt.NoPen)
        painter.drawRect(self.rect())

        if self.start and self.end:
            rect = QRect(self.start, self.end).normalized()

            # Draw red outline box
            if self.box_drawn:
                painter.setPen(QPen(Qt.red, 2))
            else:
                painter.setPen(QPen(Qt.red, 2, Qt.DashLine))

            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

    def apply_hole_mask(self):
        """Cut a real transparent hole in the dimmed window."""
        full_region = QRegion(self.rect())
        clear_rect = QRect(self.start, self.end).normalized()
        hole_region = QRegion(clear_rect)
        self.setMask(full_region.subtracted(hole_region))


def on_hotkey(key):
    global should_show_overlay
    if key == keyboard.Key.f3:
        should_show_overlay = True


def run_app():
    global should_show_overlay, overlay_instance

    app = QApplication(sys.argv)

    def check_overlay():
        global should_show_overlay, overlay_instance
        if should_show_overlay:
            should_show_overlay = False
            if overlay_instance:
                overlay_instance.close()
            overlay_instance = DimOverlay()
            overlay_instance.show()

    timer = QTimer()
    timer.timeout.connect(check_overlay)
    timer.start(100)

    print("[*] Press F3 to activate overlay. Press ESC to close.")
    app.exec_()


if __name__ == "__main__":
    listener = keyboard.Listener(on_press=on_hotkey)
    listener.start()
    run_app()
