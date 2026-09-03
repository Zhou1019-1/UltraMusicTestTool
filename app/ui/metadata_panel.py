# -*- coding: utf-8 -*-
"""
音乐信息面板
============
展示选中音频的完整元数据:
  封面(可更换/导出/移除) | 常用标签字段 | 技术参数 | 标签标准
  歌词查看与保存 | 全部原始标签表
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QTextEdit,
                               QVBoxLayout, QWidget)

from ..core import metadata as meta_mod


class MetadataPanel(QWidget):
    """音乐信息页签"""
    tags_changed = Signal(str)  # 标签被修改 (path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path: str | None = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)

        split = QSplitter(Qt.Vertical)

        # ── 上半: 封面 + 字段 ──
        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)

        # 封面区
        cover_box = QVBoxLayout()
        self.lbl_cover = QLabel("无封面")
        self.lbl_cover.setFixedSize(220, 220)
        self.lbl_cover.setAlignment(Qt.AlignCenter)
        self.lbl_cover.setStyleSheet(
            "background:#181a1e; border:1px solid #2c2f36; border-radius:8px;"
            "color:#666;")
        btn_row = QHBoxLayout()
        self.btn_set_cover = QPushButton("更换封面")
        self.btn_save_cover = QPushButton("导出封面")
        self.btn_del_cover = QPushButton("移除封面")
        for b in (self.btn_set_cover, self.btn_save_cover, self.btn_del_cover):
            b.setEnabled(False)
            btn_row.addWidget(b)
        cover_box.addWidget(self.lbl_cover)
        cover_box.addLayout(btn_row)
        tl.addLayout(cover_box)

        # 字段区
        right = QVBoxLayout()
        self.form = QFormLayout()
        self.field_labels: dict[str, QLabel] = {}
        for key, name in meta_mod.FIELD_NAMES.items():
            lab = QLabel("—")
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.field_labels[key] = lab
            self.form.addRow(f"{name}:", lab)
        right.addLayout(self.form)

        self.lbl_standards = QLabel("标签标准: —")
        self.lbl_standards.setStyleSheet("color:#7fb3e0;")
        right.addWidget(self.lbl_standards)

        tech_box = QGroupBox("技术参数")
        self.tech_form = QFormLayout(tech_box)
        self.tech_labels: dict[str, QLabel] = {}
        for key, name in (("codec", "编码/容器"), ("sample_rate", "采样率"),
                          ("channels", "声道"), ("bit_depth", "位深"),
                          ("bitrate", "码率"), ("duration", "时长"),
                          ("file_size", "文件大小")):
            lab = QLabel("—")
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.tech_labels[key] = lab
            self.tech_form.addRow(f"{name}:", lab)
        right.addWidget(tech_box)
        right.addStretch(1)
        tl.addLayout(right, 1)
        split.addWidget(top)

        # ── 中部: 歌词 ──
        lyr_box = QGroupBox("歌词 (可直接编辑后保存)")
        ll = QVBoxLayout(lyr_box)
        self.lyrics = QTextEdit()
        self.lyrics.setPlaceholderText("该文件暂无内嵌歌词")
        self.btn_save_lyrics = QPushButton("保存歌词到文件")
        self.btn_save_lyrics.setEnabled(False)
        ll.addWidget(self.lyrics)
        ll.addWidget(self.btn_save_lyrics,
                     alignment=Qt.AlignRight)
        split.addWidget(lyr_box)

        # ── 底部: 原始标签 ──
        raw_box = QGroupBox("全部原始标签 (键 -> 值)")
        rl = QVBoxLayout(raw_box)
        self.raw_tbl = QTableWidget(0, 2)
        self.raw_tbl.setHorizontalHeaderLabels(["标签键", "值"])
        self.raw_tbl.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self.raw_tbl.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.raw_tbl.verticalHeader().setVisible(False)
        rl.addWidget(self.raw_tbl)
        split.addWidget(raw_box)

        split.setSizes([280, 220, 200])
        root.addWidget(split, 1)

        # ── 信号 ──
        self.btn_set_cover.clicked.connect(self._set_cover)
        self.btn_save_cover.clicked.connect(self._export_cover)
        self.btn_del_cover.clicked.connect(self._remove_cover)
        self.btn_save_lyrics.clicked.connect(self._save_lyrics)

    # ═══════════ 展示 ═══════════
    def show_path(self, path: str | None):
        self._path = path
        has = path is not None
        for b in (self.btn_set_cover, self.btn_save_cover,
                  self.btn_del_cover, self.btn_save_lyrics):
            b.setEnabled(has)
        if not has:
            return

        meta = meta_mod.read_metadata(path)
        if not meta.ok:
            QMessageBox.warning(self, "元数据读取失败", meta.error)
            return

        for key, lab in self.field_labels.items():
            lab.setText(meta.tags.get(key) or "—")
        self.lbl_standards.setText(
            "标签标准: " + " / ".join(meta.tag_standards))

        t = self.tech_labels
        t["codec"].setText(meta.codec or "—")
        t["sample_rate"].setText(
            f"{meta.sample_rate} Hz" if meta.sample_rate else "—")
        t["channels"].setText(f"{meta.channels} ch" if meta.channels else "—")
        t["bit_depth"].setText(
            f"{meta.bit_depth} bit" if meta.bit_depth else "—(有损)")
        t["bitrate"].setText(
            f"{meta.bitrate / 1000:.0f} kbps" if meta.bitrate else "—")
        m, s = divmod(int(meta.duration), 60)
        t["duration"].setText(f"{m:02d}:{s:02d}")
        t["file_size"].setText(f"{meta.file_size / 1024 / 1024:.2f} MB")

        self.lyrics.blockSignals(True)
        self.lyrics.setPlainText(meta.lyrics)
        self.lyrics.blockSignals(False)

        self.raw_tbl.setRowCount(len(meta.raw))
        for i, (k, v) in enumerate(meta.raw):
            self.raw_tbl.setItem(i, 0, QTableWidgetItem(str(k)))
            self.raw_tbl.setItem(i, 1, QTableWidgetItem(str(v)))

        self._load_cover()

    def _load_cover(self):
        if not self._path:
            return
        data, _mime = meta_mod.get_cover(self._path)
        if data:
            pm = QPixmap()
            pm.loadFromData(data)
            self.lbl_cover.setPixmap(pm.scaled(
                220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.lbl_cover.setPixmap(QPixmap())
            self.lbl_cover.setText("无封面")

    # ═══════════ 操作 ═══════════
    def _set_cover(self):
        if not self._path:
            return
        img, _ = QFileDialog.getOpenFileName(
            self, "选择封面图片", "", "图片 (*.jpg *.jpeg *.png)")
        if not img:
            return
        try:
            meta_mod.set_cover(self._path, img)
            self._load_cover()
            self.tags_changed.emit(self._path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "封面设置失败", str(e))

    def _export_cover(self):
        if not self._path:
            return
        data, mime = meta_mod.get_cover(self._path)
        if not data:
            QMessageBox.information(self, "提示", "该文件没有内嵌封面")
            return
        ext = ".png" if "png" in mime else ".jpg"
        out, _ = QFileDialog.getSaveFileName(
            self, "导出封面",
            os.path.splitext(os.path.basename(self._path))[0] + ext,
            f"图片 (*{ext})")
        if not out:
            return
        try:
            with open(out, "wb") as f:
                f.write(data)
        except OSError as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _remove_cover(self):
        if not self._path:
            return
        try:
            meta_mod.remove_cover(self._path)
            self._load_cover()
            self.tags_changed.emit(self._path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "移除失败", str(e))

    def _save_lyrics(self):
        if not self._path:
            return
        try:
            meta_mod.write_tags(self._path,
                                {"lyrics": self.lyrics.toPlainText()})
            self.tags_changed.emit(self._path)
            QMessageBox.information(self, "成功", "歌词已写入文件")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "歌词保存失败", str(e))
