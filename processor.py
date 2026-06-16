"""
PassportProcessor — all image processing logic.
Handles face detection, background removal, cropping, enhancement, and sheet layout.
"""

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw
import mediapipe as mp
import os

# ── Constants ─────────────────────────────────────────────────────────────────

# Indian Passport: 35×45 mm at 600 DPI
PASSPORT_W = 827    # pixels
PASSPORT_H = 1063   # pixels

# Face should occupy 70–80% of height, centered horizontally
FACE_HEIGHT_RATIO  = 0.73   # target face height as fraction of photo height
FACE_TOP_MARGIN    = 0.08   # gap from top of photo to top of head

# Official Indian passport light blue background
INDIA_BLUE = (165, 200, 230)   # soft sky blue (RGB)
WHITE      = (255, 255, 255)

# Border: ~0.5 mm at 600 DPI = ~12 px
BORDER_PX = 12
BORDER_COLOR = (0, 0, 0)


class PassportProcessor:
    def __init__(self):
        self._init_face_detector()
        self._rembg_session = None   # lazy-load

    # ── Face Detection (MediaPipe) ────────────────────────────────────────────

    def _init_face_detector(self):
        """Initialize MediaPipe face detection. Falls back to OpenCV Haar cascade."""
        try:
            self.mp_face = mp.solutions.face_detection
            self.face_detector = self.mp_face.FaceDetection(
                model_selection=1,      # full-range model
                min_detection_confidence=0.5
            )
            self._use_mediapipe = True
        except Exception:
            self._use_mediapipe = False
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self.haar_cascade = cv2.CascadeClassifier(cascade_path)

    def detect_and_center_face(self, pil_img: Image.Image):
        """
        Detects face bounding box, then returns a new image cropped and
        padded so the face is properly positioned for a passport photo.
        Returns (image, face_found: bool).
        """
        rgb = np.array(pil_img.convert("RGB"))
        h, w = rgb.shape[:2]
        face_box = None

        if self._use_mediapipe:
            results = self.face_detector.process(rgb)
            if results.detections:
                det = results.detections[0]
                bb = det.location_data.relative_bounding_box
                x = int(bb.xmin * w)
                y = int(bb.ymin * h)
                fw = int(bb.width * w)
                fh = int(bb.height * h)
                # Add 20% padding above to include full head/hair
                y_adj = max(0, y - int(fh * 0.20))
                fh_adj = fh + int(fh * 0.20)
                face_box = (x, y_adj, fw, fh_adj)
        else:
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            faces = self.haar_cascade.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
            if len(faces) > 0:
                x, y, fw, fh = faces[0]
                y_adj = max(0, y - int(fh * 0.20))
                fh_adj = fh + int(fh * 0.20)
                face_box = (x, y_adj, fw, fh_adj)

        if face_box is None:
            return pil_img, False

        fx, fy, fw, fh = face_box

        # ── Compute target crop ───────────────────────────────────────────────
        # Face height should be FACE_HEIGHT_RATIO of passport height
        target_face_h = PASSPORT_H * FACE_HEIGHT_RATIO
        scale = target_face_h / fh if fh > 0 else 1.0

        # Scale image so face height matches target
        new_w = int(w * scale)
        new_h = int(h * scale)
        scaled = pil_img.resize((new_w, new_h), Image.LANCZOS)

        # Face position in scaled image
        sfx = int(fx * scale)
        sfy = int(fy * scale)
        sfw = int(fw * scale)
        sfh = int(fh * scale)

        # Desired top of photo: FACE_TOP_MARGIN above the top of the face
        top_margin_px = int(PASSPORT_H * FACE_TOP_MARGIN)
        crop_y = sfy - top_margin_px

        # Horizontal center
        face_cx = sfx + sfw // 2
        crop_x = face_cx - PASSPORT_W // 2

        # Pad if needed
        pad_left  = max(0, -crop_x)
        pad_top   = max(0, -crop_y)
        pad_right  = max(0, crop_x + PASSPORT_W - new_w)
        pad_bottom = max(0, crop_y + PASSPORT_H - new_h)

        if any([pad_left, pad_top, pad_right, pad_bottom]):
            padded_w = new_w + pad_left + pad_right
            padded_h = new_h + pad_top + pad_bottom
            padded = Image.new("RGBA", (padded_w, padded_h), (255, 255, 255, 0))
            padded.paste(scaled, (pad_left, pad_top))
            scaled = padded
            crop_x += pad_left
            crop_y += pad_top

        crop_x = max(0, crop_x)
        crop_y = max(0, crop_y)

        cropped = scaled.crop((
            crop_x,
            crop_y,
            crop_x + PASSPORT_W,
            crop_y + PASSPORT_H
        ))

        # Ensure exact size
        if cropped.size != (PASSPORT_W, PASSPORT_H):
            cropped = cropped.resize((PASSPORT_W, PASSPORT_H), Image.LANCZOS)

        return cropped, True

    # ── Background Removal (rembg) ────────────────────────────────────────────

    def _get_rembg_session(self):
        if self._rembg_session is None:
            from rembg import new_session
            self._rembg_session = new_session("u2net_human_seg")
        return self._rembg_session

    def remove_background(self, pil_img: Image.Image) -> Image.Image:
        """Remove background using rembg's u2net_human_seg model (offline)."""
        try:
            from rembg import remove
            session = self._get_rembg_session()
            result = remove(pil_img, session=session, alpha_matting=True,
                            alpha_matting_foreground_threshold=240,
                            alpha_matting_background_threshold=10,
                            alpha_matting_erode_size=10)
            return result.convert("RGBA")
        except Exception as e:
            # Graceful fallback: rough green-screen-style removal not possible offline
            # Return original with full alpha (no removal)
            return pil_img.convert("RGBA")

    # ── Background Application ────────────────────────────────────────────────

    def apply_background(self, pil_img: Image.Image, color: str) -> Image.Image:
        """Composite RGBA image onto a solid background."""
        bg_color = WHITE if color == "white" else INDIA_BLUE
        bg = Image.new("RGBA", pil_img.size, bg_color + (255,))
        # Paste subject (with alpha mask) onto background
        if pil_img.mode == "RGBA":
            bg.paste(pil_img, mask=pil_img.split()[3])
        else:
            bg.paste(pil_img)
        return bg.convert("RGBA")

    # ── Crop to Passport Size ─────────────────────────────────────────────────

    def crop_to_passport(self, pil_img: Image.Image) -> Image.Image:
        """Ensure image is exactly PASSPORT_W × PASSPORT_H."""
        if pil_img.size == (PASSPORT_W, PASSPORT_H):
            return pil_img
        return pil_img.resize((PASSPORT_W, PASSPORT_H), Image.LANCZOS)

    # ── Quality Enhancement ───────────────────────────────────────────────────

    def enhance_quality(self, pil_img: Image.Image, settings: dict) -> Image.Image:
        """Apply brightness, contrast, and sharpness enhancements."""
        img = pil_img.convert("RGB")

        brightness = settings.get("brightness", 1.05)
        contrast   = settings.get("contrast",   1.08)
        sharpness  = settings.get("sharpness",  0.60)

        if settings.get("auto_enhance", True):
            # Auto white-balance: gently push image toward neutral
            img = self._auto_white_balance(img)

        img = ImageEnhance.Brightness(img).enhance(brightness)
        img = ImageEnhance.Contrast(img).enhance(contrast)

        # Sharpness: blend between smooth (0) and sharp (2.0)
        sharp_factor = 1.0 + sharpness * 1.5
        img = ImageEnhance.Sharpness(img).enhance(sharp_factor)

        # Gentle skin-smoothing (noise reduction)
        if settings.get("auto_enhance", True):
            cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            cv_img = cv2.bilateralFilter(cv_img, d=5, sigmaColor=25, sigmaSpace=25)
            img = Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))

        return img.convert("RGBA")

    def _auto_white_balance(self, img: Image.Image) -> Image.Image:
        """Simple grey-world white balance."""
        cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2LAB).astype(np.float32)
        avg_a = np.mean(cv_img[:, :, 1])
        avg_b = np.mean(cv_img[:, :, 2])
        cv_img[:, :, 1] = cv_img[:, :, 1] - (avg_a - 128) * 0.3
        cv_img[:, :, 2] = cv_img[:, :, 2] - (avg_b - 128) * 0.3
        cv_img = np.clip(cv_img, 0, 255).astype(np.uint8)
        return Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_LAB2RGB))

    # ── Border ────────────────────────────────────────────────────────────────

    def add_border(self, pil_img: Image.Image) -> Image.Image:
        """Add a thin black border around the photo."""
        img = pil_img.convert("RGBA")
        draw = ImageDraw.Draw(img)
        w, h = img.size
        draw.rectangle(
            [0, 0, w - 1, h - 1],
            outline=BORDER_COLOR + (255,),
            width=BORDER_PX
        )
        return img

    # ── Print Sheet ───────────────────────────────────────────────────────────

    def make_print_sheet(self, photo: Image.Image, cols=3, rows=2) -> Image.Image:
        """
        Create an A4 print sheet at 600 DPI with 6 passport photos
        arranged in a 3×2 grid with margins.
        A4 at 600 DPI = 4961 × 7016 px
        """
        A4_W = 4961
        A4_H = 7016
        MARGIN = 200   # ~8.5 mm margin

        sheet = Image.new("RGB", (A4_W, A4_H), (255, 255, 255))
        photo_rgb = photo.convert("RGB")

        gap_x = (A4_W - 2 * MARGIN - cols * PASSPORT_W) // (cols - 1) if cols > 1 else 0
        gap_y = (A4_H - 2 * MARGIN - rows * PASSPORT_H) // (rows - 1) if rows > 1 else 0

        for row in range(rows):
            for col in range(cols):
                x = MARGIN + col * (PASSPORT_W + gap_x)
                y = MARGIN + row * (PASSPORT_H + gap_y)
                sheet.paste(photo_rgb, (x, y))

        return sheet
