# -*- coding: utf-8 -*-
"""应用入口"""
import multiprocessing
import os
import sys


def _resource_path(rel: str) -> str:
    """定位资源文件 (兼容 PyInstaller 冻结环境与源码运行)"""
    base = getattr(sys, "_MEIPASS", None)          # PyInstaller 解压目录
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def main():
    # Windows + PyInstaller 多进程必需
    multiprocessing.freeze_support()

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from . import APP_NAME
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    # 应用图标 (窗口/任务栏)
    icon_path = _resource_path(os.path.join("resources", "icon.png"))
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
