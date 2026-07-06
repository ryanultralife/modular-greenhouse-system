@echo off
cd /d "%~dp0"
py scripts\download_site_images.py 2>nul || python scripts\download_site_images.py
pause
