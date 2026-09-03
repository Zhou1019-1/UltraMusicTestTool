# -*- coding: utf-8 -*-
"""生成 README 用的主界面截图 (离屏渲染)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer           # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import engine                 # noqa: E402
from app.ui.main_window import MainWindow   # noqa: E402

SAMPLES = os.path.join(os.path.dirname(__file__), "samples")
OUT = os.path.join(os.path.dirname(__file__), os.pardir,
                   "docs", "screenshot-main.png")


def main():
    app = QApplication([])
    win = MainWindow()
    win.resize(1360, 860)

    files = [os.path.join(SAMPLES, f) for f in sorted(os.listdir(SAMPLES))
             if f.endswith((".flac", ".wav", ".mp3"))][:8]
    win._add_paths(files)

    # 同步分析并填充结果
    reports, _ = engine.run_batch(files, parallel=False)
    win.on_finished(reports, 0.0)
    win.file_list.setCurrentRow(0)
    if win._spec_worker:
        win._spec_worker.wait(30000)
    app.processEvents()

    win.show()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    def grab_and_quit():
        win.grab().save(OUT, "PNG")
        print("截图已保存:", OUT)
        app.quit()

    QTimer.singleShot(2500, grab_and_quit)  # 等界面完整绘制
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
