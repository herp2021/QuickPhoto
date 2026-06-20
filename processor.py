"""
PassportProcessor — all image processing logic.

FIXES IN THIS VERSION:
1. make_print_sheet: all photos in a SINGLE ROW at the TOP of the A4 page,
   with a small top margin (~15mm). Page is proper A4 at 600 DPI.
2. Processing order: remove_background FIRST on full image, then crop.
3. FACE_HEIGHT_RATIO reduced to 0.52 so shoulders are excluded.
4. alpha_matting re-enabled for clean hair/collar edges.
5. Transparent padding so background composites cleanly.
"""

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageDraw
import mediapipe as mp

# ── Crop geometry ─────────────────────────────────────────────────────────────
FACE_HEIGHT_RATIO = 0.52   # face bbox as fraction of photo height (was 0.73 → shoulders)
FACE_TOP_MARGIN   = 0.12   # fraction of photo height above face top

# ── Colours ───────────────────────────────────────────────────────────────────
INDIA_BLUE   = (165, 200, 230)
WHITE        = (255, 255, 255)
BORDER_PX    = 12
BORDER_COLOR = (0, 0, 0)

# ── A4 at 600 DPI ─────────────────────────────────────────────────────────────
A4_W = 4961   # px  (210 mm × 600 DPI / 25.4)
A4_H = 7016   # px  (297 mm × 600 DPI / 25.4)


class PassportProcessor:
    def __init__(self):
        self._init_face_detector()
        self._rembg_session = None

    # ── Face detection ────────────────────────────────────────────────────────

    def _init_face_detector(self):
        try:
            self.mp_face = mp.solutions.face_detection
            self.face_detector = self.mp_face.FaceDetection(
                model_selection=1, min_detection_confidence=0.5)
            self._use_mediapipe = True
        except Exception:
            self._use_mediapipe = False
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self.haar_cascade = cv2.CascadeClassifier(cascade_path)

    def detect_and_center_face(self, pil_img, target_w, target_h):
        rgb = np.array(pil_img.convert("RGB"))
        h, w = rgb.shape[:2]
        face_box = None

        if self._use_mediapipe:
            results = self.face_detector.process(rgb)
            if results.detections:
                det = results.detections[0]
                bb  = det.location_data.relative_bounding_box
                x   = int(bb.xmin * w);  y  = int(bb.ymin * h)
                fw  = int(bb.width * w); fh = int(bb.height * h)
                y_adj  = max(0, y - int(fh * 0.30))   # 30% upward for hair
                fh_adj = fh + int(fh * 0.30)
                face_box = (x, y_adj, fw, fh_adj)
        else:
            gray  = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            faces = self.haar_cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
            if len(faces) > 0:
                x, y, fw, fh = faces[0]
                y_adj  = max(0, y - int(fh * 0.30))
                fh_adj = fh + int(fh * 0.30)
                face_box = (x, y_adj, fw, fh_adj)

        if face_box is None:
            return pil_img, False

        fx, fy, fw, fh = face_box

        target_face_h = target_h * FACE_HEIGHT_RATIO
        scale = target_face_h / fh if fh > 0 else 1.0
        new_w = int(w * scale)
        new_h = int(h * scale)
        scaled = pil_img.convert("RGBA").resize((new_w, new_h), Image.LANCZOS)

        sfx = int(fx * scale); sfy = int(fy * scale)
        sfw = int(fw * scale)

        top_margin_px = int(target_h * FACE_TOP_MARGIN)
        crop_y  = sfy - top_margin_px
        face_cx = sfx + sfw // 2
        crop_x  = face_cx - target_w // 2

        pad_l = max(0, -crop_x);       pad_t = max(0, -crop_y)
        pad_r = max(0, crop_x + target_w - new_w)
        pad_b = max(0, crop_y + target_h - new_h)

        if any([pad_l, pad_t, pad_r, pad_b]):
            pw2 = new_w + pad_l + pad_r
            ph2 = new_h + pad_t + pad_b
            padded = Image.new("RGBA", (pw2, ph2), (0, 0, 0, 0))
            padded.paste(scaled, (pad_l, pad_t))
            scaled  = padded
            crop_x += pad_l
            crop_y += pad_t

        crop_x = max(0, crop_x); crop_y = max(0, crop_y)
        cropped = scaled.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))
        if cropped.size != (target_w, target_h):
            cropped = cropped.resize((target_w, target_h), Image.LANCZOS)
        return cropped, True

    # ── Background removal ────────────────────────────────────────────────────

    def _get_rembg_session(self):
        if self._rembg_session is None:
            from rembg import new_session
            self._rembg_session = new_session("u2net_human_seg")
        return self._rembg_session

    def remove_background(self, pil_img):
        """Run on FULL original image before any cropping."""
        try:
            from rembg import remove
            session = self._get_rembg_session()
            result  = remove(pil_img, session=session,
                             alpha_matting=True,
                             alpha_matting_foreground_threshold=230,
                             alpha_matting_background_threshold=20,
                             alpha_matting_erode_size=5)
            return result.convert("RGBA")
        except Exception:
            return pil_img.convert("RGBA")

    # ── Background fill ───────────────────────────────────────────────────────

    def apply_background(self, pil_img, color):
        bg_color = WHITE if color == "white" else INDIA_BLUE
        bg = Image.new("RGBA", pil_img.size, bg_color + (255,))
        if pil_img.mode == "RGBA":
            bg.paste(pil_img, mask=pil_img.split()[3])
        else:
            bg.paste(pil_img)
        return bg.convert("RGBA")

    # ── Size enforcement ──────────────────────────────────────────────────────

    def crop_to_passport(self, pil_img, target_w, target_h):
        if pil_img.size == (target_w, target_h):
            return pil_img
        return pil_img.resize((target_w, target_h), Image.LANCZOS)

    # ── Enhancements ──────────────────────────────────────────────────────────

    def enhance_quality(self, pil_img, settings):
        img = pil_img.convert("RGB")
        if settings.get("auto_enhance", True):
            img = self._auto_white_balance(img)
        img = ImageEnhance.Brightness(img).enhance(settings.get("brightness", 1.05))
        img = ImageEnhance.Contrast(img).enhance(settings.get("contrast", 1.08))
        img = ImageEnhance.Sharpness(img).enhance(1.0 + settings.get("sharpness", 0.6) * 1.5)
        if settings.get("auto_enhance", True):
            cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            cv_img = cv2.bilateralFilter(cv_img, d=5, sigmaColor=25, sigmaSpace=25)
            img    = Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))
        return img.convert("RGBA")

    def _auto_white_balance(self, img):
        cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2LAB).astype(np.float32)
        cv_img[:, :, 1] -= (np.mean(cv_img[:, :, 1]) - 128) * 0.3
        cv_img[:, :, 2] -= (np.mean(cv_img[:, :, 2]) - 128) * 0.3
        cv_img = np.clip(cv_img, 0, 255).astype(np.uint8)
        return Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_LAB2RGB))

    # ── Border ────────────────────────────────────────────────────────────────

    def add_border(self, pil_img):
        img  = pil_img.convert("RGBA")
        draw = ImageDraw.Draw(img)
        w, h = img.size
        draw.rectangle([0, 0, w - 1, h - 1],
                       outline=BORDER_COLOR + (255,), width=BORDER_PX)
        return img

    # ── Print sheet ───────────────────────────────────────────────────────────

    def make_print_sheet(self, photo, cols=3, rows=2):
        """
        Arrange photos in a cols×rows grid, packed tight at the TOP of an A4 page.

        Layout:
          • cols=3, rows=2 → 6 photos  (35×45 mm passport)
          • cols=3, rows=3 → 9 photos  (20×20 mm or 20×25 mm)
          • Top margin  : 118 px  (~5 mm) — minimal bleed at top
          • Side margin : photos centred horizontally
          • Gap between photos: 59 px (~2.5 mm)
          • Bottom: remaining A4 space is white (normal for print)
          • Photos scaled down only if they genuinely don't fit

        A4 @ 600 DPI = 4961 × 7016 px
        """
        TOP_MARGIN  = 118   # px ≈ 5 mm — tight top border
        GAP         = 59    # px ≈ 2.5 mm gap between photos
        MARGIN_SIDE = 118   # px ≈ 5 mm each side

        pw, ph    = photo.size
        photo_rgb = photo.convert("RGB")

        # Scale down only if needed to fit cols across available width
        available_w = A4_W - 2 * MARGIN_SIDE - GAP * (cols - 1)
        available_h = A4_H - TOP_MARGIN       - GAP * (rows - 1)
        max_pw = available_w // cols
        max_ph = available_h // rows

        if pw > max_pw or ph > max_ph:
            scale     = min(max_pw / pw, max_ph / ph)
            pw        = int(pw * scale)
            ph        = int(ph * scale)
            photo_rgb = photo_rgb.resize((pw, ph), Image.LANCZOS)

        # Centre the grid horizontally, start tight at top
        total_w = cols * pw + (cols - 1) * GAP
        start_x = (A4_W - total_w) // 2
        start_y = TOP_MARGIN

        sheet = Image.new("RGB", (A4_W, A4_H), (255, 255, 255))

        for row in range(rows):
            for col in range(cols):
                x = start_x + col * (pw + GAP)
                y = start_y + row * (ph + GAP)
                sheet.paste(photo_rgb, (x, y))

        return sheet
