"""
QuickPhoto — Passport Photo Studio
Indian Passport Edition · Offline · v5

NEW IN THIS VERSION:
- Manual reposition: after processing, drag the photo to reposition,
  use zoom slider to zoom in/out, then click "Apply Position" to finalise
- Print sheet: 6 photos for 35×45 mm, 9 photos for 20×20 / 20×25 mm
- Print layout: tight top margin (~10 mm), minimal whitespace, correct grid
- Sliders don't steal scroll (NoScrollSlider)
- Processing order: bg removal first, then face crop
"""

import sys
import os
import io
import numpy as np
from PIL import Image

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QGroupBox, QRadioButton,
    QButtonGroup, QCheckBox, QScrollArea, QFrame, QProgressBar,
    QMessageBox, QGridLayout, QSizePolicy, QSlider, QSplitter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QSize
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen, QCursor, QImage

from processor import PassportProcessor

BG_WHITE = "white"
BG_BLUE  = "blue"


# ─────────────────────────────────────────────────────────────────────────────
# Scroll-safe slider
# ─────────────────────────────────────────────────────────────────────────────

class NoScrollSlider(QSlider):
    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


# ─────────────────────────────────────────────────────────────────────────────
# Interactive crop/reposition canvas
# Lets the user drag the source image around and zoom it inside a fixed
# passport-shaped frame.  Call get_cropped() to get the final PIL Image.
# ─────────────────────────────────────────────────────────────────────────────

class CropCanvas(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_pil   = None
        self._zoom         = 1.0
        self._offset       = QPoint(0, 0)
        self._drag_start   = None
        self._offset_start = None
        self._target_w     = 827
        self._target_h     = 1063
        self._bg_color     = "white"
        self._size_mode    = "passport"

        self.setFrameSize("passport")
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))

    def setFrameSize(self, size_mode):
        self._size_mode = size_mode
        if size_mode == "passport":
            self._frame_w = 210
            self._frame_h = 270
        elif size_mode == "20x20":
            self._frame_w = 240
            self._frame_h = 240
        else:
            self._frame_w = 220
            self._frame_h = 280
        self.setMinimumSize(self._frame_w + 40, self._frame_h + 40)
        self.update()

    def load(self, pil_img_rgba, target_w, target_h, bg_color, size_mode="passport"):
        self._source_pil = pil_img_rgba.convert("RGBA")
        self._target_w   = target_w
        self._target_h   = target_h
        self._bg_color   = bg_color
        self.setFrameSize(size_mode)
        sw, sh = pil_img_rgba.size
        scale_w = self._frame_w / sw
        scale_h = self._frame_h / sh
        self._zoom   = min(scale_w, scale_h)
        self._offset = QPoint(
            int((self._frame_w  - sw * self._zoom) / 2),
            int((self._frame_h - sh * self._zoom) / 2)
        )
        self.update()
        self.changed.emit()

    def set_zoom(self, pct):
        if self._source_pil is None:
            return
        cx = self._frame_w  / 2
        cy = self._frame_h / 2
        old = self._zoom
        self._zoom = pct / 100.0
        self._offset = QPoint(
            int(cx - (cx - self._offset.x()) * self._zoom / old),
            int(cy - (cy - self._offset.y()) * self._zoom / old),
        )
        self.update()
        self.changed.emit()

    def get_zoom_pct(self):
        return int(self._zoom * 100)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        fw = self._frame_w; fh = self._frame_h
        fx = (self.width()  - fw) // 2
        fy = (self.height() - fh) // 2

        p.fillRect(self.rect(), QColor("#E8ECF0"))

        cs = 10
        for row in range(fh // cs + 1):
            for col in range(fw // cs + 1):
                c = QColor("#CCCCCC") if (row + col) % 2 == 0 else QColor("#FFFFFF")
                p.fillRect(fx + col*cs, fy + row*cs, cs, cs, c)

        if self._source_pil:
            sw = int(self._source_pil.width  * self._zoom)
            sh = int(self._source_pil.height * self._zoom)
            disp = self._source_pil.resize((max(1,sw), max(1,sh)), Image.LANCZOS)
            bg_col = (255,255,255) if self._bg_color == "white" else (165,200,230)
            bg = Image.new("RGB", disp.size, bg_col)
            if disp.mode == "RGBA":
                bg.paste(disp, mask=disp.split()[3])
            else:
                bg.paste(disp)
            data = bg.tobytes("raw", "RGB")
            qi   = QImage(data, bg.width, bg.height, bg.width*3,
                          QImage.Format.Format_RGB888)
            qpix = QPixmap.fromImage(qi)
            p.setClipRect(QRect(fx, fy, fw, fh))
            p.drawPixmap(fx + self._offset.x(), fy + self._offset.y(), qpix)
            p.setClipping(False)

        pen = QPen(QColor("#1A5276"), 2)
        p.setPen(pen)
        p.drawRect(fx, fy, fw, fh)

        pen2 = QPen(QColor(100, 149, 237, 60), 1)
        p.setPen(pen2)
        for i in [1, 2]:
            p.drawLine(fx + fw*i//3, fy, fx + fw*i//3, fy+fh)
            p.drawLine(fx, fy + fh*i//3, fx+fw, fy + fh*i//3)

        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start   = event.pos()
            self._offset_start = QPoint(self._offset)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            delta = event.pos() - self._drag_start
            self._offset = self._offset_start + delta
            self.update()
            self.changed.emit()

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))

    def get_cropped(self):
        if self._source_pil is None:
            return None

        src_x = -self._offset.x() / self._zoom
        src_y = -self._offset.y() / self._zoom
        src_w =  self._frame_w  / self._zoom
        src_h =  self._frame_h / self._zoom

        tw = self._target_w; th = self._target_h
        bg_col = (255,255,255) if self._bg_color == "white" else (165,200,230)
        out = Image.new("RGB", (tw, th), bg_col)

        sw, sh = self._source_pil.size
        paste_src_x = max(0, src_x)
        paste_src_y = max(0, src_y)
        paste_src_x2 = min(sw, src_x + src_w)
        paste_src_y2 = min(sh, src_y + src_h)
        if paste_src_x2 <= paste_src_x or paste_src_y2 <= paste_src_y:
            return out

        crop_region = self._source_pil.crop((
            int(paste_src_x), int(paste_src_y),
            int(paste_src_x2), int(paste_src_y2)
        ))

        dest_x = int((paste_src_x - src_x) / src_w * tw)
        dest_y = int((paste_src_y - src_y) / src_h * th)
        dest_w = int((paste_src_x2 - paste_src_x) / src_w * tw)
        dest_h = int((paste_src_y2 - paste_src_y) / src_h * th)

        if dest_w > 0 and dest_h > 0:
            scaled_crop = crop_region.resize((dest_w, dest_h), Image.LANCZOS)
            if scaled_crop.mode == "RGBA":
                out.paste(scaled_crop, (dest_x, dest_y), mask=scaled_crop.split()[3])
            else:
                out.paste(scaled_crop, (dest_x, dest_y))

        return out.convert("RGBA")


# ─────────────────────────────────────────────────────────────────────────────
# Background worker
# ─────────────────────────────────────────────────────────────────────────────

class WorkerThread(QThread):
    finished = pyqtSignal(object, str)   # (PIL RGBA after bg removal, error)
    progress = pyqtSignal(int, str)

    def __init__(self, processor, image_path, settings):
        super().__init__()
        self.processor  = processor
        self.image_path = image_path
        self.settings   = settings

    def run(self):
        try:
            self.progress.emit(10, "Loading image…")
            img = Image.open(self.image_path).convert("RGBA")

            # Step 1: remove background on FULL image
            self.progress.emit(25, "Removing background… (this takes ~10 sec)")
            img = self.processor.remove_background(img)

            # Step 2: auto-detect face and centre
            self.progress.emit(60, "Detecting face and centering…")
            tw = self.settings["target_w"]
            th = self.settings["target_h"]
            img, face_found = self.processor.detect_and_center_face(img, tw, th)
            if not face_found:
                # Still return the bg-removed image so user can reposition manually
                img = img.resize((tw, th), Image.LANCZOS)
                self.finished.emit(img, "face_not_found")
                return

            self.progress.emit(100, "Done — adjust position if needed")
            self.finished.emit(img, "")

        except Exception as e:
            self.finished.emit(None, f"error:{str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────

class PassportPhotoApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.processor           = PassportProcessor()
        self.original_image_path = None
        self.bg_removed_image    = None   # PIL RGBA after bg removal (pre-crop)
        self.result_image        = None   # final PIL after apply
        self.worker              = None

        self.setWindowTitle("QuickPhoto — Passport Photo Studio")
        self.setMinimumSize(1100, 720)
        self.resize(1200, 800)
        self._apply_stylesheet()
        self._build_ui()

    # ── Stylesheet ────────────────────────────────────────────────────────────

    def _apply_stylesheet(self):
        self.setStyleSheet("""
        * { font-family: 'Segoe UI', Arial, sans-serif; }
        QMainWindow, QWidget#root_widget { background: #EAECEF; }

        QGroupBox {
            background: #FFFFFF; border: 1px solid #D8DCE2; border-radius: 10px;
            margin-top: 14px; padding: 14px 12px 10px 12px;
            font-size: 12px; font-weight: 600; color: #1A3A5C;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; color: #1A3A5C; }

        QPushButton {
            font-size: 13px; padding: 9px 16px; border-radius: 8px;
            border: 1px solid #C8CDD5; background: #FFFFFF; color: #2C3E50;
        }
        QPushButton:hover  { background: #EBF4FD; border-color: #3498DB; color: #1A5276; }
        QPushButton:pressed { background: #D6EAF8; }
        QPushButton:disabled { color: #A0A8B4; background: #F4F5F7; border-color: #DDE1E8; }

        QPushButton#primary {
            background: #1A5276; color: #FFFFFF; border: none;
            font-size: 14px; font-weight: bold; padding: 12px 22px; border-radius: 9px;
        }
        QPushButton#primary:hover    { background: #1F6694; }
        QPushButton#primary:disabled { background: #B2BEC3; color: #ECF0F1; }

        QPushButton#apply_btn {
            background: #6C3483; color: #FFFFFF; border: none;
            font-size: 13px; font-weight: bold; border-radius: 8px; padding: 10px 18px;
        }
        QPushButton#apply_btn:hover    { background: #7D3C98; }
        QPushButton#apply_btn:disabled { background: #B2BEC3; color: #ECF0F1; }

        QPushButton#download {
            background: #1A7A45; color: #FFFFFF; border: none;
            font-size: 13px; font-weight: bold; border-radius: 8px;
        }
        QPushButton#download:hover    { background: #239B56; }
        QPushButton#download:disabled { background: #B2BEC3; color: #ECF0F1; }

        QLabel { color: #2C3E50; font-size: 13px; }
        QLabel#app_title { font-size: 20px; font-weight: bold; color: #1A3A5C; }
        QLabel#app_sub   { font-size: 12px; color: #7F8C8D; }
        QLabel#spec_pill {
            font-size: 11px; color: #1A5276; background: #D6EAF8;
            padding: 5px 11px; border-radius: 12px;
        }
        QLabel#tip {
            font-size: 11px; color: #6C3483; background: #F5EEF8;
            padding: 6px 10px; border-radius: 6px;
        }
        QLabel#slider_val { color: #1A5276; font-weight: bold; font-size: 13px; }

        QRadioButton, QCheckBox { font-size: 13px; color: #2C3E50; spacing: 9px; padding: 4px 2px; }
        QRadioButton:hover, QCheckBox:hover { color: #1A5276; }
        QRadioButton::indicator, QCheckBox::indicator {
            width: 17px; height: 17px; border: 2px solid #B0B8C4; border-radius: 9px; background: white;
        }
        QRadioButton::indicator:checked { background: #1A5276; border: 3px solid #D6EAF8; }
        QCheckBox::indicator { border-radius: 4px; }
        QCheckBox::indicator:checked { background: #1A5276; border: 3px solid #D6EAF8; }

        QSlider::groove:horizontal { height: 4px; background: #D8DCE2; border-radius: 2px; }
        QSlider::handle:horizontal {
            background: #1A5276; width: 17px; height: 17px; margin: -7px 0; border-radius: 9px;
        }
        QSlider::sub-page:horizontal { background: #3498DB; border-radius: 2px; }

        QProgressBar {
            border: 1px solid #D8DCE2; border-radius: 6px; text-align: center;
            font-size: 11px; background: #F4F5F7; height: 18px; color: #555;
        }
        QProgressBar::chunk { background: #1A5276; border-radius: 5px; }

        QScrollArea { background: transparent; border: none; }
        QScrollBar:vertical { width: 7px; background: transparent; }
        QScrollBar::handle:vertical { background: #C8CDD5; border-radius: 3px; min-height: 30px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

    # ── UI layout ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget(); root.setObjectName("root_widget")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        col = QVBoxLayout(); col.setSpacing(1)
        t = QLabel("QuickPhoto"); t.setObjectName("app_title")
        s = QLabel("Indian Passport  ·  Offline  ·  Studio Quality"); s.setObjectName("app_sub")
        col.addWidget(t); col.addWidget(s)
        hdr.addLayout(col); hdr.addStretch()
        pill = QLabel("📐  35×45 mm · 20×20 mm · 20×25 mm  ·  600 DPI  ·  ICAO")
        pill.setObjectName("spec_pill")
        hdr.addWidget(pill)
        outer.addLayout(hdr)

        div = QFrame(); div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("color:#D0D4DB;"); outer.addWidget(div)

        # Body: left panel | centre canvas | right final preview
        body = QHBoxLayout(); body.setSpacing(12)

        # Left scrollable settings panel
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(360)
        pw = QWidget(); pw.setLayout(self._build_left_panel())
        scroll.setWidget(pw)
        body.addWidget(scroll)

        # Centre: interactive crop canvas + zoom
        centre = QVBoxLayout(); centre.setSpacing(6)
        canvas_grp = QGroupBox("Reposition  —  drag to move, zoom to resize")
        cg_lay = QVBoxLayout(canvas_grp); cg_lay.setSpacing(8)

        self.crop_canvas = CropCanvas()
        self.crop_canvas.changed.connect(self._on_canvas_changed)
        cg_lay.addWidget(self.crop_canvas, 1)

        zoom_row = QHBoxLayout()
        zoom_lbl = QLabel("Zoom")
        zoom_lbl.setFixedWidth(38)
        self.zoom_slider = NoScrollSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 300)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.zoom_slider.valueChanged.connect(self._on_zoom)
        self.zoom_val_lbl = QLabel("100%")
        self.zoom_val_lbl.setObjectName("slider_val")
        self.zoom_val_lbl.setFixedWidth(40)
        zoom_row.addWidget(zoom_lbl); zoom_row.addWidget(self.zoom_slider)
        zoom_row.addWidget(self.zoom_val_lbl)
        cg_lay.addLayout(zoom_row)

        tip = QLabel("Center the face inside the frame, then click Apply.")
        tip.setObjectName("tip"); tip.setWordWrap(True)
        cg_lay.addWidget(tip)

        self.apply_btn = QPushButton("Apply Position & Enhance")
        self.apply_btn.setObjectName("apply_btn")
        self.apply_btn.setMinimumHeight(44)
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply_position)
        cg_lay.addWidget(self.apply_btn)

        centre.addWidget(canvas_grp, 1)
        body.addLayout(centre, 1)

        # Right: final result preview
        right = QVBoxLayout(); right.setSpacing(6)
        res_grp = QGroupBox("Final Passport Photo")
        rg_lay = QVBoxLayout(res_grp)
        self.result_label = QLabel("Result appears here")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setMinimumSize(220, 300)
        self.result_label.setStyleSheet(
            "background:#F0F2F5; border-radius:8px; color:#B0B8C4; font-size:13px;")
        self.result_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        rg_lay.addWidget(self.result_label)
        self.result_info = QLabel("")
        self.result_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_info.setStyleSheet("font-size:11px; color:#7F8C8D; padding:4px;")
        rg_lay.addWidget(self.result_info)
        right.addWidget(res_grp, 1)

        self.download_btn = QPushButton("💾   Save Single Photo")
        self.download_btn.setObjectName("download")
        self.download_btn.setMinimumHeight(42)
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self.save_image)
        right.addWidget(self.download_btn)

        self.print_sheet_btn = QPushButton("🖨   Save Print Sheet")
        self.print_sheet_btn.setMinimumHeight(38)
        self.print_sheet_btn.setEnabled(False)
        self.print_sheet_btn.clicked.connect(self.save_print_sheet)
        right.addWidget(self.print_sheet_btn)

        body.addLayout(right)
        outer.addLayout(body, 1)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("font-size:11px; color:#7F8C8D;")
        outer.addWidget(self.progress_bar)
        outer.addWidget(self.progress_label)

    # ── Left settings panel ───────────────────────────────────────────────────

    def _build_left_panel(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(2, 2, 6, 8)

        # Step 1
        g1 = QGroupBox("Step 1 — Load Photo")
        v1 = QVBoxLayout(g1); v1.setSpacing(7)
        self.upload_btn = QPushButton("📂   Open Photo")
        self.upload_btn.setMinimumHeight(44)
        self.upload_btn.clicked.connect(self.open_image)
        self.file_label = QLabel("No photo selected")
        self.file_label.setStyleSheet("color:#95A5A6; font-size:11px;")
        self.file_label.setWordWrap(True)
        v1.addWidget(self.upload_btn); v1.addWidget(self.file_label)
        layout.addWidget(g1)

        # Step 2 size
        g2 = QGroupBox("Step 2 — Photo Size")
        v2 = QVBoxLayout(g2); v2.setSpacing(4)
        self.size_group    = QButtonGroup()
        self.size_passport = QRadioButton("35 × 45 — Indian Passport  ·  6 per sheet")
        self.size_20x20    = QRadioButton("20 × 20 — Visa / ID  ·  9 per sheet")
        self.size_20x25    = QRadioButton("20 × 25 — Specialty  ·  9 per sheet")
        for rb in [self.size_passport, self.size_20x20, self.size_20x25]:
            self.size_group.addButton(rb); v2.addWidget(rb)
        layout.addWidget(g2)

        # Step 3 background
        g3 = QGroupBox("Step 3 — Background")
        v3 = QVBoxLayout(g3); v3.setSpacing(4)
        self.bg_group = QButtonGroup()
        self.bg_white = QRadioButton("⬜  White  (most common)")
        self.bg_white.setChecked(True)
        self.bg_blue  = QRadioButton("🟦  Light Blue  (official Indian)")
        for rb in [self.bg_white, self.bg_blue]:
            self.bg_group.addButton(rb); v3.addWidget(rb)
        # Update canvas when bg changes
        self.bg_white.toggled.connect(self._on_bg_changed)
        layout.addWidget(g3)

        # Step 4 border
        g4 = QGroupBox("Step 4 — Border")
        v4 = QVBoxLayout(g4); v4.setSpacing(4)
        self.border_grp  = QButtonGroup()
        self.border_none = QRadioButton("Borderless")
        self.border_none.setChecked(True)
        self.border_thin = QRadioButton("Thin border  (0.5 mm)")
        for rb in [self.border_none, self.border_thin]:
            self.border_grp.addButton(rb); v4.addWidget(rb)
        layout.addWidget(g4)

        # Step 5 enhancements
        g5 = QGroupBox("Step 5 — Enhancements")
        v5 = QVBoxLayout(g5); v5.setSpacing(10)
        self.auto_enhance = QCheckBox("Auto studio enhancement")
        self.auto_enhance.setChecked(True)
        v5.addWidget(self.auto_enhance)
        self.brightness_slider = self._make_slider(v5, "Brightness", 70, 130, 105)
        self.contrast_slider   = self._make_slider(v5, "Contrast",   70, 130, 108)
        self.sharpness_slider  = self._make_slider(v5, "Sharpness",   0, 100,  60)
        layout.addWidget(g5)

        # Generate button
        self.process_btn = QPushButton("✨   Generate Passport Photo")
        self.process_btn.setObjectName("primary")
        self.process_btn.setMinimumHeight(50)
        self.process_btn.setEnabled(False)
        self.process_btn.clicked.connect(self.process_image)
        layout.addWidget(self.process_btn)

        layout.addStretch()
        return layout

    def _make_slider(self, parent_layout, label_text, lo, hi, default):
        row_w = QWidget()
        grid  = QGridLayout(row_w)
        grid.setContentsMargins(0,0,0,0); grid.setSpacing(4)
        lbl = QLabel(label_text); lbl.setMinimumWidth(72)
        s   = NoScrollSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi); s.setValue(default)
        s.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        val = QLabel(str(default)); val.setObjectName("slider_val")
        val.setFixedWidth(32)
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        s.valueChanged.connect(lambda v, l=val: l.setText(str(v)))
        grid.addWidget(lbl, 0, 0); grid.addWidget(s, 0, 1); grid.addWidget(val, 0, 2)
        parent_layout.addWidget(row_w)
        return s

    # ── Canvas events ─────────────────────────────────────────────────────────

    def _on_zoom(self, value):
        self.zoom_val_lbl.setText(f"{value}%")
        self.crop_canvas.set_zoom(value)

    def _on_canvas_changed(self):
        pass   # live preview already rendered by paintEvent

    def _on_bg_changed(self):
        bg = "white" if self.bg_white.isChecked() else "blue"
        self.crop_canvas._bg_color = bg
        self.crop_canvas.update()

    # ── Actions ───────────────────────────────────────────────────────────────

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Photo", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff *.webp)")
        if not path:
            return
        self.original_image_path = path
        self.file_label.setText(os.path.basename(path))
        self.file_label.setStyleSheet("color:#1A5276; font-size:11px; font-weight:bold;")
        self.process_btn.setEnabled(True)
        self.result_label.setText("Press Generate")
        self.result_image = None
        self.bg_removed_image = None
        self.download_btn.setEnabled(False)
        self.print_sheet_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)

    def _gather_settings(self):
        if self.size_passport.isChecked():
            mode, w, h = "passport", 827, 1063
        elif self.size_20x20.isChecked():
            mode, w, h = "20x20", 472, 472
        else:
            mode, w, h = "20x25", 472, 591
        return {
            "size_mode": mode, "target_w": w, "target_h": h,
            "bg_color":     "white" if self.bg_white.isChecked() else "blue",
            "border":       self.border_thin.isChecked(),
            "auto_enhance": self.auto_enhance.isChecked(),
            "brightness":   self.brightness_slider.value() / 100.0,
            "contrast":     self.contrast_slider.value()   / 100.0,
            "sharpness":    self.sharpness_slider.value()  / 100.0,
        }

    def process_image(self):
        if not self.original_image_path:
            return
        self.process_btn.setEnabled(False)
        self.apply_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.print_sheet_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.worker = WorkerThread(self.processor, self.original_image_path,
                                   self._gather_settings())
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_processed)
        self.worker.start()

    def _on_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.progress_label.setText(message)

    def _on_processed(self, image, error):
        self.process_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")

        if error.startswith("error:") or image is None:
            QMessageBox.warning(self, "Error", error.replace("error:", ""))
            return

        s = self._gather_settings()
        self.bg_removed_image = image   # RGBA bg-removed, auto-centred

        if error == "face_not_found":
            QMessageBox.information(self, "Face not found",
                "Face could not be detected automatically.\n"
                "The image has been loaded — please drag to position manually.")

        # Load into canvas for manual adjustment
        self.crop_canvas.load(image, s["target_w"], s["target_h"], s["bg_color"], s["size_mode"])
        self.zoom_slider.setValue(self.crop_canvas.get_zoom_pct())
        self.apply_btn.setEnabled(True)
        self.progress_label.setText("✅  Drag to reposition · zoom to adjust · then click Apply")

    def apply_position(self):
        """Grab the current canvas crop, apply enhancements, show result."""
        cropped = self.crop_canvas.get_cropped()
        if cropped is None:
            return

        s = self._gather_settings()

        # Enhance
        enhanced = self.processor.enhance_quality(cropped, s)

        # Border
        if s["border"]:
            enhanced = self.processor.add_border(enhanced)

        self.result_image = enhanced

        # Show in result panel
        buf = io.BytesIO()
        enhanced.save(buf, format="PNG")
        buf.seek(0)
        qpix = QPixmap(); qpix.loadFromData(buf.read())
        self.result_label.setPixmap(
            qpix.scaled(220, 300, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))

        size_str = {"passport":"35×45 mm","20x20":"20×20 mm","20x25":"20×25 mm"}.get(s["size_mode"],"")
        cols, rows = (6, 1) if s["size_mode"] == "passport" else (9, 1)
        n = cols * rows
        self.result_info.setText(f"{size_str}  ·  {enhanced.width}×{enhanced.height} px  ·  600 DPI")
        self.print_sheet_btn.setText(f"🖨   Save Print Sheet  ({n} photos on A4)")
        self._pending_cols = cols
        self._pending_rows = rows
        self.download_btn.setEnabled(True)
        self.print_sheet_btn.setEnabled(True)
        self.progress_label.setText("✅  Photo ready — save single or print sheet")

    def save_image(self):
        if not self.result_image:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Passport Photo", "passport_photo.jpg",
            "JPEG (*.jpg);;PNG (*.png)")
        if not path:
            return
        fmt = "JPEG" if path.lower().endswith(".jpg") else "PNG"
        out = self.result_image.convert("RGB") if fmt == "JPEG" else self.result_image
        out.save(path, format=fmt, dpi=(600, 600), quality=95)
        QMessageBox.information(self, "Saved", f"Photo saved:\n{path}")

    def save_print_sheet(self):
        if not self.result_image:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Print Sheet", "passport_print_sheet.jpg",
            "JPEG (*.jpg);;PNG (*.png)")
        if not path:
            return
        sheet = self.processor.make_print_sheet(
            self.result_image,
            cols=self._pending_cols,
            rows=self._pending_rows)
        fmt = "JPEG" if path.lower().endswith(".jpg") else "PNG"
        sheet.convert("RGB").save(path, format=fmt, dpi=(600, 600), quality=95)
        QMessageBox.information(self, "Saved", f"Print sheet saved:\n{path}")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("QuickPhoto")
    win = PassportPhotoApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
