@echo off
title Build Passport Photo Studio EXE
echo Building standalone .exe — this will take a few minutes...

call venv\Scripts\activate.bat
pip install pyinstaller --quiet

pyinstaller ^
  --onefile ^
  --windowed ^
  --name "PassportPhotoStudio" ^
  --add-data "venv\Lib\site-packages\rembg\sessions;rembg\sessions" ^
  --hidden-import mediapipe ^
  --hidden-import rembg ^
  --hidden-import onnxruntime ^
  main.py

echo.
echo Done! Your app is in the "dist" folder: dist\PassportPhotoStudio.exe
pause
