"""
Passport Photo Studio — Indian Passport Edition
Offline desktop application for creating standard passport photos.
"""

import sys
import os
import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QComboBox, QSlider, QGroupBox,
    QRadioButton, QButtonGroup, QCheckBox, QScrollArea, QFrame,
    QProgressBar, QMessageBox, QSizePolicy, QSpacerItem, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QPixmap, QImage, QFont, QColor, QPalette, QIcon
import io

from processor import PassportProcessor

# ── Indian Passport Specification ─────────────────────────────────────────────
INDIAN_PASSPORT = {
    "name": "Indian Passport (35×45 mm)",
    "width_mm": 35,
    "height_mm": 45,
    "dpi": 600,
    "width_px": 827,   # 35mm at 600dpi
    "height_px": 1063, # 45mm at 600dpi
    "face_ratio": 0.70,  # face height should be 70-80% of photo height
    "face_top_ratio": 0.10,  # face top at 10% from photo top
}

BG_WHITE = "white"
BG_BLUE  = "blue"  # Indian passport official light blue


class WorkerThread(QThread):
    """Runs image processing off the main thread so UI stays responsive."""
    finished = pyqtSignal(object, str)   # (PIL Image or None, message)
    progress = pyqtSignal(int, str)

    def __init__(self, processor, image_path, settings):
        super().__init__()
        self.processor = processor
        self.image_path = image_path
        self.settings = settings

    def run(self):
        try:
            self.progress.emit(10, "Loading image…")
            img = Image.open(self.image_path).convert("RGBA")

            self.progress.emit(25, "Detecting face…")
            img, face_found = self.processor.detect_and_center_face(img)
            if not face_found:
                self.finished.emit(None, "No face detected. Please use a photo with a clearly visible face.")
                return

            self.progress.emit(45, "Removing background…")
            img = self.processor.remove_background(img)

            self.progress.emit(60, "Applying background colour…")
            img = self.processor.apply_background(img, self.settings["bg_color"])

            self.progress.emit(72, "Cropping to passport dimensions…")
            img = self.processor.crop_to_passport(img)

            self.progress.emit(82, "Enhancing photo quality…")
            img = self.processor.enhance_quality(img, self.settings)

            self.progress.emit(90, "Adding border…")
            if self.settings.get("border"):
                img = self.processor.add_border(img)

            self.progress.emit(100, "Done!")
            self.finished.emit(img, "")
        except Exception as e:
            self.finished.emit(None, f"Processing error: {str(e)}")


# ── Main Window ───────────────────────────────────────────────────────────────

class PassportPhotoApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.processor = PassportProcessor()
        self.original_image_path = None
        self.result_image = None   # PIL Image
        self.worker = None

        self.setWindowTitle("Passport Photo Studio — India")
        self.setMinimumSize(1000, 700)
        self.resize(1120, 760)
        self._apply_stylesheet()
        self._build_ui()

    # ── Stylesheet ────────────────────────────────────────────────────────────

    def _apply_stylesheet(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #F5F5F5;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QGroupBox {
                font-size: 13px;
                font-weight: bold;
                color: #333;
                border: 1px solid #DDD;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 10px;
                background: #FFFFFF;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #1a5276;
            }
            QPushButton {
                font-size: 14px;
                padding: 10px 20px;
                border-radius: 7px;
                border: 1px solid #CCC;
                background: #FFFFFF;
                color: #333;
            }
            QPushButton:hover { background: #EAF3FB; border-color: #378ADD; color: #185FA5; }
            QPushButton:pressed { background: #D0E8F8; }
            QPushButton#primary {
                background: #1a5276;
                color: white;
                border: none;
                font-size: 15px;
                font-weight: bold;
                padding: 12px 28px;
            }
            QPushButton#primary:hover { background: #21618C; }
            QPushButton#primary:disabled { background: #AAA; }
            QPushButton#download {
                background: #1E8449;
                color: white;
                border: none;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton#download:hover { background: #27AE60; }
            QPushButton#download:disabled { background: #AAA; }
            QLabel { color: #333; font-size: 13px; }
            QLabel#title { font-size: 22px; font-weight: bold; color: #1a5276; }
            QLabel#subtitle { font-size: 13px; color: #666; }
            QLabel#spec { font-size: 12px; color: #555; background: #EAF3FB;
                          padding: 6px 10px; border-radius: 5px; }
            QRadioButton { font-size: 13px; color: #333; spacing: 8px; }
            QRadioButton::indicator { width: 18px; height: 18px; }
            QCheckBox { font-size: 13px; color: #333; spacing: 8px; }
            QCheckBox::indicator { width: 18px; height: 18px; }
            QSlider::groove:horizontal { height: 5px; background: #DDD; border-radius: 3px; }
            QSlider::handle:horizontal {
                background: #1a5276; width: 18px; height: 18px;
                margin: -7px 0; border-radius: 9px;
            }
            QSlider::sub-page:horizontal { background: #378ADD; border-radius: 3px; }
            QProgressBar {
                border: 1px solid #CCC; border-radius: 5px;
                text-align: center; font-size: 12px; background: #FFF;
                height: 20px;
            }
            QProgressBar::chunk { background: #1a5276; border-radius: 4px; }
        """)

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # Header
        header = QHBoxLayout()
        title = QLabel("Passport Photo Studio")
        title.setObjectName("title")
        subtitle = QLabel("Indian Passport · Offline · Studio Quality")
        subtitle.setObjectName("subtitle")
        hbox = QVBoxLayout()
        hbox.setSpacing(2)
        hbox.addWidget(title)
        hbox.addWidget(subtitle)
        header.addLayout(hbox)
        header.addStretch()
        spec = QLabel("📐  35 × 45 mm  ·  600 DPI  ·  ICAO compliant")
        spec.setObjectName("spec")
        header.addWidget(spec)
        root.addLayout(header)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #DDD;")
        root.addWidget(line)

        # Main body: left panel + preview
        body = QHBoxLayout()
        body.setSpacing(16)
        body.addLayout(self._build_left_panel(), 1)
        body.addLayout(self._build_preview_panel(), 2)
        root.addLayout(body, 1)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("font-size: 12px; color: #555;")
        root.addWidget(self.progress_bar)
        root.addWidget(self.progress_label)

    def _build_left_panel(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)

        # ── Upload ────────────────────────────────────────────────────────────
        upload_grp = QGroupBox("Step 1 — Load Photo")
        ug_layout = QVBoxLayout(upload_grp)
        ug_layout.setSpacing(8)

        self.upload_btn = QPushButton("  📂   Open Photo")
        self.upload_btn.setMinimumHeight(48)
        self.upload_btn.clicked.connect(self.open_image)
        ug_layout.addWidget(self.upload_btn)

        self.file_label = QLabel("No photo selected")
        self.file_label.setStyleSheet("color: #888; font-size: 12px;")
        self.file_label.setWordWrap(True)
        ug_layout.addWidget(self.file_label)
        layout.addWidget(upload_grp)

        # ── Background ────────────────────────────────────────────────────────
        bg_grp = QGroupBox("Step 2 — Background Colour")
        bg_layout = QVBoxLayout(bg_grp)
        bg_layout.setSpacing(6)
        self.bg_group = QButtonGroup()

        self.bg_white = QRadioButton("⬜  White  (most common)")
        self.bg_white.setChecked(True)
        self.bg_blue  = QRadioButton("🟦  Light Blue  (official Indian)")
        self.bg_group.addButton(self.bg_white)
        self.bg_group.addButton(self.bg_blue)
        bg_layout.addWidget(self.bg_white)
        bg_layout.addWidget(self.bg_blue)
        layout.addWidget(bg_grp)

        # ── Border ───────────────────────────────────────────────────────────
        border_grp = QGroupBox("Step 3 — Border")
        br_layout = QVBoxLayout(border_grp)
        br_layout.setSpacing(6)
        self.border_none = QRadioButton("No border  (borderless)")
        self.border_none.setChecked(True)
        self.border_thin = QRadioButton("Thin border  (0.5 mm)")
        self.border_grp_btn = QButtonGroup()
        self.border_grp_btn.addButton(self.border_none)
        self.border_grp_btn.addButton(self.border_thin)
        br_layout.addWidget(self.border_none)
        br_layout.addWidget(self.border_thin)
        layout.addWidget(border_grp)

        # ── Enhancements ──────────────────────────────────────────────────────
        enh_grp = QGroupBox("Step 4 — Enhancements")
        en_layout = QVBoxLayout(enh_grp)
        en_layout.setSpacing(10)

        self.auto_enhance = QCheckBox("Auto studio enhancement  (recommended)")
        self.auto_enhance.setChecked(True)
        en_layout.addWidget(self.auto_enhance)

        def make_slider(label, min_val, max_val, default):
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(90)
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(min_val, max_val)
            s.setValue(default)
            val_lbl = QLabel(str(default))
            val_lbl.setFixedWidth(30)
            val_lbl.setStyleSheet("color: #1a5276; font-weight: bold;")
            s.valueChanged.connect(lambda v, l=val_lbl: l.setText(str(v)))
            row.addWidget(lbl)
            row.addWidget(s)
            row.addWidget(val_lbl)
            en_layout.addLayout(row)
            return s

        self.brightness_slider  = make_slider("Brightness",  70, 130, 105)
        self.contrast_slider    = make_slider("Contrast",    70, 130, 108)
        self.sharpness_slider   = make_slider("Sharpness",    0, 100,  60)

        layout.addWidget(enh_grp)

        # ── Process ───────────────────────────────────────────────────────────
        self.process_btn = QPushButton("✨   Generate Passport Photo")
        self.process_btn.setObjectName("primary")
        self.process_btn.setMinimumHeight(52)
        self.process_btn.setEnabled(False)
        self.process_btn.clicked.connect(self.process_image)
        layout.addWidget(self.process_btn)

        # ── Download ──────────────────────────────────────────────────────────
        self.download_btn = QPushButton("💾   Save Photo")
        self.download_btn.setObjectName("download")
        self.download_btn.setMinimumHeight(46)
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self.save_image)
        layout.addWidget(self.download_btn)

        self.print_sheet_btn = QPushButton("🖨   Save Print Sheet  (6 photos)")
        self.print_sheet_btn.setMinimumHeight(40)
        self.print_sheet_btn.setEnabled(False)
        self.print_sheet_btn.clicked.connect(self.save_print_sheet)
        layout.addWidget(self.print_sheet_btn)

        layout.addStretch()
        return layout

    def _build_preview_panel(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)

        row = QHBoxLayout()

        # Original preview
        orig_grp = QGroupBox("Original Photo")
        orig_layout = QVBoxLayout(orig_grp)
        self.original_label = QLabel("No photo loaded")
        self.original_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.original_label.setMinimumSize(300, 360)
        self.original_label.setStyleSheet("background:#EEE; border-radius:6px; color:#AAA; font-size:13px;")
        orig_layout.addWidget(self.original_label)
        row.addWidget(orig_grp)

        # Result preview
        res_grp = QGroupBox("Passport Photo")
        res_layout = QVBoxLayout(res_grp)
        self.result_label = QLabel("Result will appear here")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setMinimumSize(300, 360)
        self.result_label.setStyleSheet("background:#EEE; border-radius:6px; color:#AAA; font-size:13px;")
        res_layout.addWidget(self.result_label)

        self.result_info = QLabel("")
        self.result_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_info.setStyleSheet("font-size: 11px; color: #666;")
        res_layout.addWidget(self.result_info)
        row.addWidget(res_grp)

        layout.addLayout(row)
        return layout

    # ── Actions ───────────────────────────────────────────────────────────────

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Photo", "",
            "Image Files (*.jpg *.jpeg *.png *.bmp *.tiff *.webp)"
        )
        if not path:
            return
        self.original_image_path = path
        self.file_label.setText(os.path.basename(path))
        self.file_label.setStyleSheet("color: #1a5276; font-size: 12px; font-weight: bold;")

        # Show thumbnail
        pix = QPixmap(path)
        self.original_label.setPixmap(
            pix.scaled(300, 360, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
        )
        self.process_btn.setEnabled(True)
        self.result_label.setText("Press 'Generate' to process")
        self.result_image = None
        self.download_btn.setEnabled(False)
        self.print_sheet_btn.setEnabled(False)

    def _gather_settings(self):
        return {
            "bg_color":   BG_WHITE if self.bg_white.isChecked() else BG_BLUE,
            "border":     self.border_thin.isChecked(),
            "auto_enhance": self.auto_enhance.isChecked(),
            "brightness": self.brightness_slider.value() / 100.0,
            "contrast":   self.contrast_slider.value()   / 100.0,
            "sharpness":  self.sharpness_slider.value()  / 100.0,
        }

    def process_image(self):
        if not self.original_image_path:
            return
        self.process_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.print_sheet_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.result_label.setText("Processing…")

        self.worker = WorkerThread(
            self.processor,
            self.original_image_path,
            self._gather_settings()
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.progress_label.setText(message)

    def _on_finished(self, image, error):
        self.process_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")

        if error or image is None:
            QMessageBox.warning(self, "Processing Error", error or "Unknown error occurred.")
            self.result_label.setText("Processing failed.\nPlease try another photo.")
            return

        self.result_image = image

        # Show result thumbnail
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        buf.seek(0)
        qpix = QPixmap()
        qpix.loadFromData(buf.read())
        self.result_label.setPixmap(
            qpix.scaled(300, 360, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
        )
        self.result_info.setText(
            f"35×45 mm  ·  {image.width}×{image.height} px  ·  600 DPI"
        )
        self.download_btn.setEnabled(True)
        self.print_sheet_btn.setEnabled(True)

    def save_image(self):
        if not self.result_image:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Passport Photo", "passport_photo.jpg",
            "JPEG (*.jpg);;PNG (*.png)"
        )
        if not path:
            return
        fmt = "JPEG" if path.lower().endswith(".jpg") else "PNG"
        out = self.result_image.convert("RGB") if fmt == "JPEG" else self.result_image
        out.save(path, format=fmt, dpi=(600, 600), quality=95)
        QMessageBox.information(self, "Saved", f"Photo saved to:\n{path}")

    def save_print_sheet(self):
        if not self.result_image:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Print Sheet", "passport_print_sheet.jpg",
            "JPEG (*.jpg);;PNG (*.png)"
        )
        if not path:
            return
        sheet = self.processor.make_print_sheet(self.result_image)
        fmt = "JPEG" if path.lower().endswith(".jpg") else "PNG"
        sheet.convert("RGB").save(path, format=fmt, dpi=(600, 600), quality=95)
        QMessageBox.information(self, "Saved", f"Print sheet (6 photos on A4) saved to:\n{path}")


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Passport Photo Studio")
    win = PassportPhotoApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()