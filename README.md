# QuickPhoto
Creating Passport Photo

===============================================================
  PASSPORT PHOTO STUDIO — INDIA
  Offline Desktop Application
  Indian Passport Standard (35×45 mm, 600 DPI, ICAO compliant)
===============================================================

WHAT THIS APP DOES
------------------
1. Loads any photo (JPG, PNG, WEBP, BMP)
2. Detects the person's face automatically
3. Removes the original background (works offline using AI)
4. Applies white or official Indian light-blue background
5. Centers and crops to exact passport dimensions
6. Applies studio-quality enhancements (brightness, contrast, sharpness)
7. Adds an optional thin border
8. Exports a single photo OR a print sheet with 6 photos on A4
9. Supports multiple sizes: 35×45 mm, 20×20 mm, 20×25 mm
10. Manual reposition with drag-and-zoom after processing
11. Instant preview of selected image before generation


REQUIREMENTS
------------
- Windows 10/11, macOS 12+, or Ubuntu 20.04+
- Python 3.10 or newer  (free from https://www.python.org)
- Internet only needed once to download the AI background removal model
  (~170 MB). After that, fully offline.
- At least 4 GB RAM (8 GB recommended)


HOW TO RUN — WINDOWS
--------------------
1. Install Python from https://www.python.org/downloads/
   *** Tick "Add Python to PATH" during installation ***
2. Double-click:  setup_and_run.bat
   (First run installs all libraries — takes 3–5 minutes)
3. App will open automatically.


HOW TO RUN — MAC / LINUX
------------------------
1. Open Terminal in this folder
2. Run:   chmod +x setup_and_run.sh && ./setup_and_run.sh
3. App will open automatically.


HOW TO USE THE APP
------------------
Step 1 — Click "Open Photo" and choose your photo
        (preview appears on the right immediately)
Step 2 — Choose photo size: 35×45 mm, 20×20 mm, or 20×25 mm
Step 3 — Choose background: White or Light Blue
Step 4 — Choose border: Borderless or Thin border (0.5 mm)
Step 5 — Adjust brightness / contrast / sharpness, or leave Auto on
Step 6 — Click "Generate Passport Photo"
Step 7 — Drag inside the frame to fine-tune position, zoom if needed
Step 8 — Click "Apply Position & Enhance"
Step 9 — Save the single photo or the print sheet


PHOTO TIPS FOR BEST RESULTS
----------------------------
- Use a photo taken indoors or in good natural light
- Face should be clearly visible, looking straight at the camera
- Neutral expression, both eyes open
- Original background can be anything — the app removes it
- Higher resolution original = better final quality


OUTPUT SPECIFICATIONS
---------------------
Single photo:
  Size:     35 mm × 45 mm  |  20 mm × 20 mm  |  20 mm × 25 mm
  DPI:      600
  Pixels:   827 × 1063  |  472 × 472  |  472 × 591
  Format:   JPG (quality 95) or PNG

Print sheet (A4):
  Layout:   6 photos in one row  (35×45 mm)
            9 photos in one row  (20×20 mm or 20×25 mm)
  DPI:      600
  Pixels:   4961 × 7016 (full A4)
  Format:   JPG or PNG


BUILD A STANDALONE .EXE (WINDOWS)
----------------------------------
After running setup_and_run.bat at least once:
1. Double-click:  build_exe.bat
2. Find your app at:  dist\PassportPhotoStudio.exe
3. Copy that .exe to any Windows computer — no Python needed!


TROUBLESHOOTING
---------------
"No face detected" — Try a clearer photo with the face more visible
"Processing error"  — Check that all libraries installed (re-run setup)
Slow processing     — Normal on first run; AI model loads once per session
Black result        — Re-run setup to reinstall libraries

For support, re-run setup_and_run.bat to fix most issues.


LIBRARIES USED
--------------
PyQt6        Desktop UI framework
OpenCV       Image processing
MediaPipe    Face detection (Google)
rembg        AI background removal (offline u2net model)
Pillow       Image export
NumPy        Pixel mathematics
===============================================================
