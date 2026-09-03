# -*- coding: utf-8 -*-
"""
GUI 冒烟测试 (无头模式): 验证主窗口/三大页签可正常构建与联动
用法: python tests/test_gui_smoke.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication              # noqa: E402

from app.ui.main_window import MainWindow               # noqa: E402

SAMPLES = os.path.join(os.path.dirname(__file__), "samples")


def main():
    app = QApplication([])
    win = MainWindow()

    # 1. 添加文件
    files = [os.path.join(SAMPLES, f) for f in os.listdir(SAMPLES)
             if f.endswith((".flac", ".mp3", ".wav"))]
    win._add_paths(files)
    assert win.file_list.count() == len(files), "文件列表添加失败"

    # 2. 标签编辑器同步加载 (QThread 信号需事件循环分发)
    assert win.tag_editor._paths == win._all_paths(), "标签编辑器未同步"
    win.tag_editor._lw.wait(15000)
    app.processEvents()
    assert win.tag_editor.tbl.rowCount() == len(files), "标签表行数错误"

    # 3. 选中文件 -> 三页签联动
    win.file_list.setCurrentRow(0)
    win._spec_worker.wait(20000)
    app.processEvents()
    assert win.meta_panel._path is not None, "信息面板未更新"

    # 4. 表格单元格编辑 -> 脏标记
    win.tag_editor.tbl.setCurrentCell(0, 1)
    item = win.tag_editor.tbl.item(0, 1)
    item.setText("冒烟测试标题")
    assert 0 in win.tag_editor._dirty, "编辑未标记为脏"

    print("GUI 冒烟测试全部通过: "
          f"{len(files)} 文件, 三页签联动正常, 编辑脏标记正常")
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
