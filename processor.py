"""
PassportProcessor — all image processing logic.
Handles face detection, background removal, cropping, enhancement, and sheet layout.

BUG FIXES (v2):
- Remove background FIRST on full original image, THEN detect face and crop
- Re-enabled alpha_matting with tuned parameters for clean hair/collar edges
- Fixed print sheet to handle multiple rows correctly (3×2 for 6 photos, 3×3 for 9)
- Fixed padding in detect_and_center_face to preserve RGBA transparency (not bake white)
"""

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw
import mediapipe as mp
import os

# ── Constants ─────────────────────────────────────────────────────────────────

FACE_HEIGHT_RATIO  = 0.73   # target face height as fraction of photo height
FACE_TOP_MARGIN    = 0.08   # gap from top of photo to top of head

INDIA_BLUE  = (165, 200, 230)
WHITE       = (255, 255, 255)

BORDER_PX    = 12
BORDER_COLOR = (0, 0, 0)


class PassportProcessor:
    def __init__(self):
        self._init_face_detector()
        self._rembg_session = None   # lazy-load

    # ── Face Detection ────────────────────────────────────────────────────────

    def _init_face_detector(self):
        try:
            self.mp_face = mp.solutions.face_detection
            self.face_detector = self.mp_face.FaceDetection(
                model_selection=1,
                min_detection_confidence=0.5
            )
            self._use_mediapipe = True
        except Exception:
            self._use_mediapipe = False
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self.haar_cascade = cv2.CascadeClassifier(cascade_path)

    def detect_and_center_face(self, pil_img: Image.Image, target_w: int, target_h: int):
        """
        Detects face, scales and crops so face is properly centred for passport spec.
        IMPORTANT: pil_img should already have background removed (RGBA).
        Padding uses TRANSPARENT fill (not white) so background colour is applied later.
        Returns (image, face_found: bool).
        """
        # Work on RGB copy for detection; keep RGBA original for compositing
        rgb = np.array(pil_img.convert("RGB"))
        h, w = rgb.shape[:2]
        face_box = None

        if self._use_mediapipe:
            results = self.face_detector.process(rgb)
            if results.detections:
                det = results.detections[0]
                bb = det.location_data.relative_bounding_box
                x  = int(bb.xmin * w)
                y  = int(bb.ymin * h)
                fw = int(bb.width * w)
                fh = int(bb.height * h)
                # Add 25% above to include full head/hair
                y_adj  = max(0, y - int(fh * 0.25))
                fh_adj = fh + int(fh * 0.25)
                face_box = (x, y_adj, fw, fh_adj)
        else:
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            faces = self.haar_cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
            if len(faces) > 0:
                x, y, fw, fh = faces[0]
                y_adj  = max(0, y - int(fh * 0.25))
                fh_adj = fh + int(fh * 0.25)
                face_box = (x, y_adj, fw, fh_adj)

        if face_box is None:
            return pil_img, False

        fx, fy, fw, fh = face_box

        target_face_h = target_h * FACE_HEIGHT_RATIO
        scale = target_face_h / fh if fh > 0 else 1.0

        new_w = int(w * scale)
        new_h = int(h * scale)

        # Scale the RGBA image (preserves transparency)
        scaled = pil_img.convert("RGBA").resize((new_w, new_h), Image.LANCZOS)

        sfx = int(fx * scale)
        sfy = int(fy * scale)
        sfw = int(fw * scale)
        sfh = int(fh * scale)

        top_margin_px = int(target_h * FACE_TOP_MARGIN)
        crop_y = sfy - top_margin_px
        face_cx = sfx + sfw // 2
        crop_x  = face_cx - target_w // 2

        pad_left   = max(0, -crop_x)
        pad_top    = max(0, -crop_y)
        pad_right  = max(0, crop_x + target_w  - new_w)
        pad_bottom = max(0, crop_y + target_h - new_h)

        if any([pad_left, pad_top, pad_right, pad_bottom]):
            padded_w = new_w + pad_left + pad_right
            padded_h = new_h + pad_top + pad_bottom
            # ✅ FIX: use fully transparent fill so background colour applied later is clean
            padded = Image.new("RGBA", (padded_w, padded_h), (0, 0, 0, 0))
            padded.paste(scaled, (pad_left, pad_top))
            scaled = padded
            crop_x += pad_left
            crop_y += pad_top

        crop_x = max(0, crop_x)
        crop_y = max(0, crop_y)

        cropped = scaled.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))

        if cropped.size != (target_w, target_h):
            cropped = cropped.resize((target_w, target_h), Image.LANCZOS)

        return cropped, True

    # ── Background Removal ────────────────────────────────────────────────────

    def _get_rembg_session(self):
        if self._rembg_session is None:
            from rembg import new_session
            # u2net_human_seg is the best model for portraits
            self._rembg_session = new_session("u2net_human_seg")
        return self._rembg_session

    def remove_background(self, pil_img: Image.Image) -> Image.Image:
        """
        Remove background from the FULL original image before any cropping.
        ✅ FIX: alpha_matting re-enabled with tuned thresholds for clean hair/collar edges.
        """
        try:
            from rembg import remove
            session = self._get_rembg_session()
            result = remove(
                pil_img,
                session=session,
                alpha_matting=True,
                alpha_matting_foreground_threshold=230,
                alpha_matting_background_threshold=20,
                alpha_matting_erode_size=5,
            )
            return result.convert("RGBA")
        except Exception:
            return pil_img.convert("RGBA")

    # ── Background Application ────────────────────────────────────────────────

    def apply_background(self, pil_img: Image.Image, color: str) -> Image.Image:
        bg_color = WHITE if color == "white" else INDIA_BLUE
        bg = Image.new("RGBA", pil_img.size, bg_color + (255,))
        if pil_img.mode == "RGBA":
            bg.paste(pil_img, mask=pil_img.split()[3])
        else:
            bg.paste(pil_img)
        return bg.convert("RGBA")

    # ── Crop to Target Size ───────────────────────────────────────────────────

    def crop_to_passport(self, pil_img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        if pil_img.size == (target_w, target_h):
            return pil_img
        return pil_img.resize((target_w, target_h), Image.LANCZOS)

    # ── Quality Enhancement ───────────────────────────────────────────────────

    def enhance_quality(self, pil_img: Image.Image, settings: dict) -> Image.Image:
        img = pil_img.convert("RGB")

        brightness = settings.get("brightness", 1.05)
        contrast   = settings.get("contrast",   1.08)
        sharpness  = settings.get("sharpness",  0.60)

        if settings.get("auto_enhance", True):
            img = self._auto_white_balance(img)

        img = ImageEnhance.Brightness(img).enhance(brightness)
        img = ImageEnhance.Contrast(img).enhance(contrast)
        img = ImageEnhance.Sharpness(img).enhance(1.0 + sharpness * 1.5)

        if settings.get("auto_enhance", True):
            cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            cv_img = cv2.bilateralFilter(cv_img, d=5, sigmaColor=25, sigmaSpace=25)
            img = Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))

        return img.convert("RGBA")

    def _auto_white_balance(self, img: Image.Image) -> Image.Image:
        cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2LAB).astype(np.float32)
        avg_a = np.mean(cv_img[:, :, 1])
        avg_b = np.mean(cv_img[:, :, 2])
        cv_img[:, :, 1] -= (avg_a - 128) * 0.3
        cv_img[:, :, 2] -= (avg_b - 128) * 0.3
        cv_img = np.clip(cv_img, 0, 255).astype(np.uint8)
        return Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_LAB2RGB))

    # ── Border ────────────────────────────────────────────────────────────────

    def add_border(self, pil_img: Image.Image) -> Image.Image:
        img = pil_img.convert("RGBA")
        draw = ImageDraw.Draw(img)
        w, h = img.size
        draw.rectangle([0, 0, w - 1, h - 1], outline=BORDER_COLOR + (255,), width=BORDER_PX)
        return img

    # ── Print Sheet ───────────────────────────────────────────────────────────

    def make_print_sheet(self, photo: Image.Image, cols: int = 3, rows: int = 2) -> Image.Image:
        """
        Create an A4 print sheet at 600 DPI.
        ✅ FIX: proper cols×rows grid (default 3×2 = 6 photos for passport size).
        All photos are centred on the page with equal margins.
        A4 at 600 DPI = 4961 × 7016 px
        """
        A4_W = 4961
        A4_H = 7016
        GAP  = 80   # ~3.4 mm gap between photos

        pw, ph = photo.size
        photo_rgb = photo.convert("RGB")

        # Scale down if photos don't fit
        max_photo_w = (A4_W - 400 - GAP * (cols - 1)) // cols
        max_photo_h = (A4_H - 400 - GAP * (rows - 1)) // rows
        if pw > max_photo_w or ph > max_photo_h:
            scale = min(max_photo_w / pw, max_photo_h / ph)
            pw = int(pw * scale)
            ph = int(ph * scale)
            photo_rgb = photo_rgb.resize((pw, ph), Image.LANCZOS)

        total_w = cols * pw + (cols - 1) * GAP
        total_h = rows * ph + (rows - 1) * GAP

        start_x = (A4_W - total_w) // 2
        start_y = (A4_H - total_h) // 2

        sheet = Image.new("RGB", (A4_W, A4_H), (255, 255, 255))

        for row in range(rows):
            for col in range(cols):
                x = start_x + col * (pw + GAP)
                y = start_y + row * (ph + GAP)
                sheet.paste(photo_rgb, (x, y))

        return sheet
