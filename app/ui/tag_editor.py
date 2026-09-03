# -*- coding: utf-8 -*-
"""
MP3Tag 风格批量标签编辑器
=========================
- 表格: 每行一个文件, 每列一个标签字段, 直接编辑单元格 (改动标橙)
- 保存修改: 仅写回改动过的字段 (后台线程, 不卡界面)
- 批量赋值: 对选中行统一填充某字段
- 文件名 -> 标签: "%artist% - %title%" 模式解析
- 标签 -> 文件名: 按模式重命名文件 (带确认)
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..core import metadata as meta_mod

COLS = ["文件名"] + [meta_mod.FIELD_NAMES[k] for k in meta_mod.FIELDS]
DIRTY_COLOR = QColor("#e0a34a")


class _LoadWorker(QThread):
    loaded = Signal(list)  # list[(path, AudioMeta)]
    failed = Signal(str)

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self._paths = list(paths)

    def run(self):
        try:
            out = [(p, meta_mod.read_metadata(p)) for p in self._paths]
            self.loaded.emit(out)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class _SaveWorker(QThread):
    saved = Signal(int, list)   # 成功数, [(path, error)]
    failed = Signal(str)

    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self._jobs = jobs  # [(path, changes)]

    def run(self):
        ok, errs = 0, []
        try:
            for path, changes in self._jobs:
                try:
                    meta_mod.write_tags(path, changes)
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    errs.append((path, str(e)))
            self.saved.emit(ok, errs)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class TagEditor(QWidget):
    """标签编辑页签"""
    tags_saved = Signal()  # 保存完成 (主窗口可刷新)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths: list[str] = []
        self._dirty: dict[int, dict[str, str]] = {}  # row -> {field: value}
        self._loading = False
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)

        # ── 操作条 1: 保存/刷新 ──
        bar1 = QHBoxLayout()
        self.btn_save = QPushButton("保存修改")
        self.btn_save.setObjectName("primary")
        self.btn_save.setEnabled(False)
        self.btn_reload = QPushButton("重新读取")
        self.lbl_hint = QLabel("双击单元格直接编辑；橙色为未保存修改")
        self.lbl_hint.setStyleSheet("color:#888;")
        bar1.addWidget(self.btn_save)
        bar1.addWidget(self.btn_reload)
        bar1.addWidget(self.lbl_hint)
        bar1.addStretch(1)
        lay.addLayout(bar1)

        # ── 表格 ──
        self.tbl = QTableWidget(0, len(COLS))
        self.tbl.setHorizontalHeaderLabels(COLS)
        self.tbl.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        for c in range(1, len(COLS)):
            self.tbl.horizontalHeader().setSectionResizeMode(
                c, QHeaderView.Interactive)
            self.tbl.setColumnWidth(c, 110)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QTableWidget.SelectRows)
        lay.addWidget(self.tbl, 1)

        # ── 操作条 2: 批量赋值 ──
        bar2 = QHBoxLayout()
        bar2.addWidget(QLabel("批量赋值:"))
        self.cmb_field = QComboBox()
        for k in meta_mod.FIELDS:
            self.cmb_field.addItem(meta_mod.FIELD_NAMES[k], k)
        self.edt_value = QLineEdit()
        self.edt_value.setPlaceholderText("要写入的值 (留空 = 清除该字段)")
        self.btn_apply = QPushButton("应用到选中行")
        bar2.addWidget(self.cmb_field)
        bar2.addWidget(self.edt_value, 1)
        bar2.addWidget(self.btn_apply)
        lay.addLayout(bar2)

        # ── 操作条 3: 文件名 <-> 标签 ──
        bar3 = QHBoxLayout()
        bar3.addWidget(QLabel("模式:"))
        self.edt_pattern = QLineEdit("%artist% - %title%")
        self.btn_fn2tag = QPushButton("文件名 → 标签 (选中行)")
        self.btn_tag2fn = QPushButton("标签 → 重命名文件 (选中行)")
        self.btn_tag2fn.setToolTip(
            "按模式用标签值重命名文件, 可用 %title% %artist% %album% "
            "%tracknumber% 等")
        bar3.addWidget(self.edt_pattern, 1)
        bar3.addWidget(self.btn_fn2tag)
        bar3.addWidget(self.btn_tag2fn)
        lay.addLayout(bar3)

        # ── 信号 ──
        self.tbl.itemChanged.connect(self._on_edit)
        self.btn_save.clicked.connect(self.save_changes)
        self.btn_reload.clicked.connect(self.reload)
        self.btn_apply.clicked.connect(self._apply_batch)
        self.btn_fn2tag.clicked.connect(self._filename_to_tag)
        self.btn_tag2fn.clicked.connect(self._rename_files)

    # ═══════════ 加载 ═══════════
    def load_paths(self, paths: list[str]):
        """由主窗口调用: 文件列表变化时刷新"""
        self._paths = list(paths)
        self._dirty.clear()
        self.btn_save.setEnabled(False)
        if not paths:
            self.tbl.setRowCount(0)
            return
        self._loading = True
        self.lbl_hint.setText("正在读取标签...")
        self._lw = _LoadWorker(paths, self)
        self._lw.loaded.connect(self._on_loaded)
        self._lw.failed.connect(lambda m: self.lbl_hint.setText(f"读取失败: {m}"))
        self._lw.start()

    def _on_loaded(self, rows):
        self._loading = False
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(len(rows))
        for r, (path, meta) in enumerate(rows):
            name_it = QTableWidgetItem(os.path.basename(path))
            name_it.setFlags(name_it.flags() & ~Qt.ItemIsEditable)
            name_it.setToolTip(path)
            if not meta.ok:
                name_it.setForeground(QColor("#FF6666"))
                name_it.setToolTip(f"{path}\n{meta.error}")
            self.tbl.setItem(r, 0, name_it)
            for c, key in enumerate(meta_mod.FIELDS, start=1):
                self.tbl.setItem(r, c, QTableWidgetItem(meta.tags.get(key, "")))
        self.tbl.blockSignals(False)
        self.lbl_hint.setText("双击单元格直接编辑；橙色为未保存修改")

    def reload(self):
        if self._dirty:
            ret = QMessageBox.question(
                self, "放弃修改?", "存在未保存的修改，重新读取将丢弃，继续?")
            if ret != QMessageBox.Yes:
                return
        self.load_paths(self._paths)

    # ═══════════ 编辑 ═══════════
    def _on_edit(self, item: QTableWidgetItem):
        if self._loading or item.column() == 0:
            return
        row, col = item.row(), item.column()
        key = meta_mod.FIELDS[col - 1]
        self._dirty.setdefault(row, {})[key] = item.text()
        item.setForeground(DIRTY_COLOR)
        self.btn_save.setEnabled(True)

    def _apply_batch(self):
        rows = sorted({i.row() for i in self.tbl.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "提示", "请先选中要批量修改的行")
            return
        key = self.cmb_field.currentData()
        value = self.edt_value.text()
        col = meta_mod.FIELDS.index(key) + 1
        for r in rows:
            self.tbl.setItem(r, col, QTableWidgetItem(value))
        self.lbl_hint.setText(
            f"已将 {len(rows)} 行的「{meta_mod.FIELD_NAMES[key]}」标记为待保存")

    def _selected_rows(self):
        return sorted({i.row() for i in self.tbl.selectedIndexes()})

    def _filename_to_tag(self):
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "提示", "请先选中行")
            return
        pattern = self.edt_pattern.text()
        hit = 0
        for r in rows:
            path = self._paths[r]
            parsed = meta_mod.parse_filename_pattern(path, pattern)
            if not parsed:
                continue
            hit += 1
            for key, value in parsed.items():
                col = meta_mod.FIELDS.index(key) + 1
                self.tbl.setItem(r, col, QTableWidgetItem(value))
        self.lbl_hint.setText(
            f"已从文件名解析 {hit}/{len(rows)} 行（记得点“保存修改”）")

    def _rename_files(self):
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "提示", "请先选中行")
            return
        pattern = self.edt_pattern.text().strip()
        if not pattern or "%" not in pattern:
            QMessageBox.information(self, "提示",
                                    "模式需包含 %title% 这类字段占位符")
            return
        ret = QMessageBox.question(
            self, "确认重命名",
            f"将按模式「{pattern}」重命名 {len(rows)} 个文件，是否继续?")
        if ret != QMessageBox.Yes:
            return

        ok, errs, renames = 0, [], []
        for r in rows:
            path = self._paths[r]
            values = {}
            for c, key in enumerate(meta_mod.FIELDS, start=1):
                it = self.tbl.item(r, c)
                values[key] = (it.text() if it else "") or ""
            new_stem = pattern
            for key, value in values.items():
                safe = "".join(ch for ch in value
                               if ch not in '\\/:*?"<>|').strip()
                new_stem = new_stem.replace(f"%{key}%", safe)
            if new_stem == pattern or not new_stem.strip():
                errs.append((path, "模式字段为空，无法重命名"))
                continue
            new_path = os.path.join(
                os.path.dirname(path),
                new_stem.strip() + os.path.splitext(path)[1])
            if os.path.abspath(new_path) == os.path.abspath(path):
                ok += 1
                continue
            try:
                os.rename(path, new_path)
                renames.append((r, new_path))
                ok += 1
            except OSError as e:
                errs.append((path, str(e)))

        for r, new_path in renames:  # 同步路径表
            self._paths[r] = new_path
        if renames:
            self.load_paths(self._paths)
        msg = f"成功 {ok} 个"
        if errs:
            msg += "\n失败:\n" + "\n".join(
                f"{os.path.basename(p)}: {e}" for p, e in errs[:5])
        QMessageBox.information(self, "重命名结果", msg)
        if renames:
            self.tags_saved.emit()

    # ═══════════ 保存 ═══════════
    def save_changes(self):
        if not self._dirty:
            return
        jobs = []
        for row, changes in sorted(self._dirty.items()):
            if row < len(self._paths):
                jobs.append((self._paths[row], changes))
        if not jobs:
            return
        self.btn_save.setEnabled(False)
        self.lbl_hint.setText(f"正在保存 {len(jobs)} 个文件...")
        self._sw = _SaveWorker(jobs, self)
        self._sw.saved.connect(self._on_saved)
        self._sw.failed.connect(
            lambda m: QMessageBox.critical(self, "保存失败", m))
        self._sw.start()

    def _on_saved(self, ok: int, errs: list):
        self._dirty.clear()
        if errs:
            msg = f"成功 {ok} 个，失败 {len(errs)} 个:\n" + "\n".join(
                f"{os.path.basename(p)}: {e}" for p, e in errs[:5])
            QMessageBox.warning(self, "部分保存失败", msg)
        else:
            self.lbl_hint.setText(f"已保存 {ok} 个文件")
        self.load_paths(self._paths)  # 重新读取确认
        self.tags_saved.emit()
