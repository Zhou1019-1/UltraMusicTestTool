# -*- coding: utf-8 -*-
"""
一键打包脚本: PyInstaller 生成 dist 目录版 EXE
用法: python build.py
"""
import subprocess
import sys

CMD = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--clean",
    "--windowed",                       # 无控制台窗口
    "--name", "OctopusLosslessV1",
    "--icon", "app/resources/app.ico",
    "--add-data", "app/resources;resources",
    "--collect-all", "soundfile",       # 带上 libsndfile DLL
    "--collect-all", "av",              # PyAV 兜底解码 (含 FFmpeg DLL)
    "--collect-all", "mutagen",
    "--collect-submodules", "scipy.signal",
    "--collect-submodules", "scipy.fft",
    "--exclude-module", "PyQt5", "--exclude-module", "PyQt6",
    "--exclude-module", "PySide2", "--exclude-module", "tkinter",
    "--exclude-module", "matplotlib",
    "run.py",
]

if __name__ == "__main__":
    print(" ".join(CMD))
    sys.exit(subprocess.call(CMD))
