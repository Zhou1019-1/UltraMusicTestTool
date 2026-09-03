# -*- coding: utf-8 -*-
"""
主窗口 (无损鉴别-章鱼出品V1)
============================
布局:
  工具栏: 添加文件/文件夹 | 移除 | 清空 | 开始分析 | 并行开关 | 性能基准 | 导出报告
  左侧: 文件列表 (状态/判定着色)
  右侧 QTabWidget 三大功能页签:
    1. 鉴别分析  - Spek 风格频谱图 + 判定 + 检测方法明细 + 音质维度卡
    2. 音乐信息  - 封面/元数据/歌词/技术参数/原始标签
    3. 标签编辑  - MP3Tag 风格批量编辑
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextBrowser, QVBoxLayout, QWidget, QHeaderView,
)

from .. import APP_NAME, AUTHOR, __version__
from ..core import engine
from ..core.audio_loader import SUPPORTED_EXTS, is_supported, load_audio
from ..core.spectrogram import compute_spectrogram
from .metadata_panel import MetadataPanel
from .spectrogram_widget import SpectrogramWidget
from .tag_editor import TagEditor

DARK_STYLE = """
QMainWindow, QWidget { background: #121214; color: #e0e0e0;
    font-family: "Microsoft YaHei", "Segoe UI"; font-size: 13px; }
QPushButton { background: #2a2d34; border: 1px solid #3a3d46;
    border-radius: 6px; padding: 6px 14px; }
QPushButton:hover { background: #353945; }
QPushButton:disabled { color: #666; background: #1d1f24; }
QPushButton#primary { background: #5b3fa8; border-color: #7a5cc9; font-weight: bold; }
QPushButton#primary:hover { background: #6d4fc0; }
QListWidget, QTableWidget, QTextBrowser, QTextEdit, QLineEdit, QComboBox {
    background: #181a1e; border: 1px solid #2c2f36; border-radius: 6px; }
QComboBox QAbstractItemView { background: #181a1e; color: #e0e0e0; }
QGroupBox { border: 1px solid #2c2f36; border-radius: 6px;
    margin-top: 10px; padding-top: 8px; }
QGroupBox::title { color: #9a86d8; }
QTabWidget::pane { border: 1px solid #2c2f36; border-radius: 6px; }
QTabBar::tab { background: #1d1f24; padding: 8px 20px;
    border-top-left-radius: 6px; border-top-right-radius: 6px; }
QTabBar::tab:selected { background: #5b3fa8; color: white; font-weight: bold; }
QProgressBar { background: #1d1f24; border: 1px solid #2c2f36;
    border-radius: 6px; text-align: center; height: 18px; }
QProgressBar::chunk { background: #5b3fa8; border-radius: 5px; }
QHeaderView::section { background: #22252b; border: none; padding: 4px; }
QLabel#verdict { font-size: 20px; font-weight: bold; padding: 6px; }
QLineEdit, QComboBox { padding: 5px; }
"""

GRADE_COLORS = {"pass": "#44FF44", "info": "#66ccff",
                "warn": "#FFCC00", "fail": "#FF4444"}


class AnalysisWorker(QThread):
    """后台分析线程 (内部再调度多进程)"""
    progress = Signal(int, int, str)
    finished_ok = Signal(list, float)
    failed = Signal(str)

    def __init__(self, paths, parallel=True, parent=None):
        super().__init__(parent)
        self._paths = list(paths)
        self._parallel = parallel

    def run(self):
        try:
            cb = lambda d, t, p: self.progress.emit(d, t, p)
            reports, elapsed = engine.run_batch(
                self._paths, parallel=self._parallel, progress_cb=cb)
            self.finished_ok.emit(reports, elapsed)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class SpectrogramWorker(QThread):
    """后台频谱计算线程"""
    ready = Signal(str, object, object, float)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = path

    def run(self):
        try:
            audio = load_audio(self._path)
            freqs, times, s_db = compute_spectrogram(
                audio.samples, audio.samplerate)
            self.ready.emit(self._path, freqs, s_db, audio.duration)
        except Exception as e:  # noqa: BLE001
            import sys
            print(f"频谱计算失败: {e}", file=sys.stderr)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{__version__} - {AUTHOR}")
        self.resize(1360, 860)
        self.setStyleSheet(DARK_STYLE)
        self.setAcceptDrops(True)

        self.reports: dict[str, engine.FileReport] = {}
        self._spec_cache: dict[str, tuple] = {}
        self._worker: AnalysisWorker | None = None
        self._spec_worker: SpectrogramWorker | None = None

        self._build_ui()

    # ═════════════════════════ UI ═════════════════════════
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)

        # ── 工具栏 ──
        bar = QHBoxLayout()
        self.btn_add = QPushButton("添加文件")
        self.btn_dir = QPushButton("添加文件夹")
        self.btn_rm = QPushButton("移除选中")
        self.btn_clear = QPushButton("清空")
        self.btn_run = QPushButton("开始分析")
        self.btn_run.setObjectName("primary")
        self.chk_parallel = QCheckBox("多进程并行")
        self.chk_parallel.setChecked(True)
        self.btn_bench = QPushButton("性能基准")
        self.btn_export = QPushButton("导出报告")
        for b in (self.btn_add, self.btn_dir, self.btn_rm, self.btn_clear,
                  self.btn_run, self.btn_bench, self.btn_export):
            bar.addWidget(b)
        bar.addWidget(self.chk_parallel)
        bar.addStretch(1)
        lay.addLayout(bar)

        # ── 主区分割 ──
        split = QSplitter(Qt.Horizontal)
        self.file_list = QListWidget()
        self.file_list.setMaximumWidth(360)
        split.addWidget(self.file_list)

        # ── 右侧: 三大功能页签 ──
        self.tabs = QTabWidget()

        # 页签1: 鉴别分析
        tab_detect = QWidget()
        dl = QVBoxLayout(tab_detect)
        detect_split = QSplitter(Qt.Vertical)
        self.spec = SpectrogramWidget()
        detect_split.addWidget(self.spec)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 4, 0, 0)
        self.lbl_verdict = QLabel("尚未分析")
        self.lbl_verdict.setObjectName("verdict")
        bl.addWidget(self.lbl_verdict)

        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["检测方法", "得分", "结论", "关键指标"])
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setMaximumHeight(150)
        bl.addWidget(self.tbl)

        # 音质维度卡 (SoniqTools 风格三态评级)
        self.tbl_quality = QTableWidget(0, 3)
        self.tbl_quality.setHorizontalHeaderLabels(["音质维度", "评级", "说明"])
        self.tbl_quality.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self.tbl_quality.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        self.tbl_quality.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.tbl_quality.verticalHeader().setVisible(False)
        self.tbl_quality.setMaximumHeight(140)
        bl.addWidget(self.tbl_quality)

        self.detail = QTextBrowser()
        bl.addWidget(self.detail)
        detect_split.addWidget(bottom)
        detect_split.setSizes([400, 400])
        dl.addWidget(detect_split)
        self.tabs.addTab(tab_detect, "鉴别分析")

        # 页签2: 音乐信息
        self.meta_panel = MetadataPanel()
        self.tabs.addTab(self.meta_panel, "音乐信息")

        # 页签3: 标签编辑
        self.tag_editor = TagEditor()
        self.tabs.addTab(self.tag_editor, "标签编辑")

        split.addWidget(self.tabs)
        split.setSizes([340, 1020])
        lay.addWidget(split, 1)

        # ── 进度条 + 状态栏 ──
        self.progress = QProgressBar()
        self.progress.setValue(0)
        lay.addWidget(self.progress)
        self.statusBar().showMessage(
            f"就绪 | {APP_NAME} v{__version__} | {AUTHOR}")

        # ── 信号 ──
        self.btn_add.clicked.connect(self.add_files)
        self.btn_dir.clicked.connect(self.add_folder)
        self.btn_rm.clicked.connect(self.remove_selected)
        self.btn_clear.clicked.connect(self.clear_all)
        self.btn_run.clicked.connect(self.start_analysis)
        self.btn_bench.clicked.connect(self.run_benchmark)
        self.btn_export.clicked.connect(self.export_report)
        self.file_list.currentItemChanged.connect(self.on_select)
        self.meta_panel.tags_changed.connect(self._on_tags_changed)
        self.tag_editor.tags_saved.connect(self._on_tags_changed)

    # ═════════════════════ 文件管理 ═════════════════════
    def _add_paths(self, paths):
        added = 0
        existing = {self.file_list.item(i).data(Qt.UserRole)
                    for i in range(self.file_list.count())}
        for p in paths:
            if not is_supported(p) or p in existing:
                continue
            item = QListWidgetItem(os.path.basename(p))
            item.setData(Qt.UserRole, p)
            item.setToolTip(p)
            self.file_list.addItem(item)
            added += 1
        if added:
            self.statusBar().showMessage(f"已添加 {added} 个文件")
            self.tag_editor.load_paths(self._all_paths())

    def add_files(self):
        filt = "音频文件 (" + " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTS)) + ")"
        paths, _ = QFileDialog.getOpenFileNames(self, "选择音频文件", "", filt)
        if paths:
            self._add_paths(paths)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if not d:
            return
        paths = []
        for root, _, files in os.walk(d):
            for f in files:
                p = os.path.join(root, f)
                if is_supported(p):
                    paths.append(p)
        self._add_paths(sorted(paths))

    def remove_selected(self):
        for item in self.file_list.selectedItems():
            p = item.data(Qt.UserRole)
            self.reports.pop(p, None)
            self._spec_cache.pop(p, None)
            self.file_list.takeItem(self.file_list.row(item))
        self.tag_editor.load_paths(self._all_paths())

    def clear_all(self):
        self.file_list.clear()
        self.reports.clear()
        self._spec_cache.clear()
        self.tbl.setRowCount(0)
        self.tbl_quality.setRowCount(0)
        self.detail.clear()
        self.lbl_verdict.setText("尚未分析")
        self.spec.clear()
        self.progress.setValue(0)
        self.meta_panel.show_path(None)
        self.tag_editor.load_paths([])

    # 拖拽支持
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls()]
        files = []
        for p in paths:
            if os.path.isdir(p):
                for root, _, fs in os.walk(p):
                    files += [os.path.join(root, f) for f in fs]
            else:
                files.append(p)
        self._add_paths(files)

    def _all_paths(self):
        return [self.file_list.item(i).data(Qt.UserRole)
                for i in range(self.file_list.count())]

    # ═════════════════════ 分析 ═════════════════════
    def start_analysis(self):
        paths = self._all_paths()
        if not paths:
            QMessageBox.information(self, APP_NAME, "请先添加音频文件")
            return
        self._set_busy(True)
        self.progress.setValue(0)
        self._worker = AnalysisWorker(paths, self.chk_parallel.isChecked())
        self._worker.progress.connect(self.on_progress)
        self._worker.finished_ok.connect(self.on_finished)
        self._worker.failed.connect(self.on_failed)
        self._worker.start()

    def run_benchmark(self):
        paths = self._all_paths()
        if len(paths) < 2:
            QMessageBox.information(self, APP_NAME,
                                    "性能基准需要至少 2 个文件")
            return
        self._set_busy(True)
        self.statusBar().showMessage("正在运行 顺序 vs 并行 性能基准...")

        class BenchWorker(QThread):
            done = Signal(dict)
            fail = Signal(str)

            def run(self2):
                try:
                    self2.done.emit(engine.benchmark(paths))
                except Exception as e:  # noqa: BLE001
                    self2.fail.emit(str(e))

        self._bench = BenchWorker()

        def show(res):
            self._set_busy(False)
            QMessageBox.information(
                self, "性能基准结果",
                f"文件数: {res['files']}\n"
                f"顺序执行: {res['seq_time']}s\n"
                f"并行执行 ({res['workers']} 进程): {res['par_time']}s\n"
                f"加速比: {res['speedup']}x")
            self.statusBar().showMessage(
                f"基准完成: 加速比 {res['speedup']}x")

        self._bench.done.connect(show)
        self._bench.fail.connect(self.on_failed)
        self._bench.start()

    def on_progress(self, done, total, path):
        self.progress.setValue(int(done / total * 100))
        self.statusBar().showMessage(
            f"分析中 {done}/{total}: {os.path.basename(path)}")

    def on_finished(self, reports, elapsed):
        self._set_busy(False)
        for rep in reports:
            self.reports[rep.path] = rep
            self._update_list_item(rep)
        ok = sum(1 for r in reports if r.ok)
        fail = len(reports) - ok
        self.statusBar().showMessage(
            f"分析完成: {ok} 成功, {fail} 失败, 用时 {elapsed:.1f}s")
        if fail:
            errs = "\n".join(f"{os.path.basename(r.path)}: {r.error}"
                             for r in reports if not r.ok)
            QMessageBox.warning(self, "部分文件分析失败", errs)
        cur = self.file_list.currentItem()
        if cur:
            self.on_select(cur, None)
        elif self.file_list.count():
            self.file_list.setCurrentRow(0)

    def on_failed(self, msg):
        self._set_busy(False)
        QMessageBox.critical(self, "分析出错", msg)

    def _set_busy(self, busy):
        for b in (self.btn_add, self.btn_dir, self.btn_rm, self.btn_clear,
                  self.btn_run, self.btn_bench, self.btn_export):
            b.setEnabled(not busy)

    def _update_list_item(self, rep):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.UserRole) != rep.path:
                continue
            name = os.path.basename(rep.path)
            if not rep.ok:
                item.setText(f"{name}  [失败]")
                item.setForeground(QColor("#FF6666"))
            else:
                v = rep.verdict
                suffix = " [⚠扩展名不符]" if rep.warning else ""
                item.setText(f"{name}  [{v.grade} {v.score}分]{suffix}")
                item.setForeground(QColor(v.color))

    # ═══════════════════ 选中文件 → 展示 ═══════════════════
    def on_select(self, item, _prev):
        if item is None:
            return
        path = item.data(Qt.UserRole)

        # 频谱图 (缓存优先, 否则后台计算)
        if path in self._spec_cache:
            freqs, s_db, dur = self._spec_cache[path]
            self._show_spec(path, freqs, s_db, dur)
        else:
            self.spec.clear("正在计算频谱图...")
            self._spec_worker = SpectrogramWorker(path)
            self._spec_worker.ready.connect(self._on_spec_ready)
            self._spec_worker.start()

        # 鉴别结果 + 音乐信息
        self._show_report(self.reports.get(path))
        self.meta_panel.show_path(path)

    def _on_spec_ready(self, path, freqs, s_db, duration):
        self._spec_cache[path] = (freqs, s_db, duration)
        cur = self.file_list.currentItem()
        if cur and cur.data(Qt.UserRole) == path:
            self._show_spec(path, freqs, s_db, duration)

    def _show_spec(self, path, freqs, s_db, duration):
        cutoff = None
        rep = self.reports.get(path)
        if rep and rep.ok:
            if rep.verdict.is_lossy_container:
                cutoff = rep.verdict.lossy_profile.get("cutoff_khz")
            else:
                for r in rep.method_results:
                    if r.method == "cutoff" and r.applicable:
                        c = r.metrics.get("cutoff_khz")
                        if c and r.score < 90:
                            cutoff = c
        self.spec.set_spectrogram(s_db, freqs, duration, cutoff)

    def _show_report(self, rep):
        self.tbl.setRowCount(0)
        self.tbl_quality.setRowCount(0)
        self.detail.clear()
        if rep is None:
            self.lbl_verdict.setText("未分析 (点击“开始分析”)")
            self.lbl_verdict.setStyleSheet("color:#999;")
            return
        if not rep.ok:
            self.lbl_verdict.setText("分析失败")
            self.lbl_verdict.setStyleSheet("color:#FF6666;")
            self.detail.setPlainText(rep.error)
            return

        v = rep.verdict
        info = (f"{rep.container}/{rep.subtype}  {rep.samplerate}Hz "
                f"{rep.channels}ch  {rep.bit_depth}bit  {rep.duration}s")
        self.lbl_verdict.setText(f"【{v.grade}】 {v.score} 分   {info}")
        self.lbl_verdict.setStyleSheet(f"color:{v.color};")

        rows = []
        if v.is_lossy_container:
            lp = v.lossy_profile
            rows.append(("有损画像", "0",
                         "; ".join(lp.get("losses", [])) or "有损格式",
                         f"码率≈{lp.get('estimated_bitrate_kbps', '?')}kbps "
                         f"cutoff={lp.get('cutoff_khz', '?')}kHz"))
        for r in rep.method_results:
            kv = "  ".join(f"{k}={val}" for k, val in r.metrics.items())
            rows.append((r.name,
                         "—" if not r.applicable else f"{r.score:.0f}",
                         r.summary, kv))
        self.tbl.setRowCount(len(rows))
        for i, (name, score, summary, kv) in enumerate(rows):
            for j, text in enumerate((name, score, summary, kv)):
                cell = QTableWidgetItem(str(text))
                if j == 1 and score not in ("—",):
                    s = float(score)
                    color = ("#44FF44" if s >= 85 else "#88FF88" if s >= 65
                             else "#FFCC00" if s >= 45 else "#FF8844" if s >= 25
                             else "#FF4444")
                    cell.setForeground(QColor(color))
                self.tbl.setItem(i, j, cell)

        # 音质维度三态卡
        checks = rep.quality.get("checks", [])
        self.tbl_quality.setRowCount(len(checks))
        for i, (name, grade, desc) in enumerate(checks):
            self.tbl_quality.setItem(i, 0, QTableWidgetItem(name))
            g = QTableWidgetItem(grade.upper())
            g.setForeground(QColor(GRADE_COLORS.get(grade, "#e0e0e0")))
            self.tbl_quality.setItem(i, 1, g)
            self.tbl_quality.setItem(i, 2, QTableWidgetItem(desc))

        self.detail.setPlainText(rep.to_text())

    def _on_tags_changed(self, *_args):
        """标签被修改后: 清元数据缓存并重载当前文件信息页"""
        cur = self.file_list.currentItem()
        if cur:
            self.meta_panel.show_path(cur.data(Qt.UserRole))

    # ═════════════════════ 导出 ═════════════════════
    def export_report(self):
        if not self.reports:
            QMessageBox.information(self, APP_NAME, "没有可导出的分析结果")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出分析报告", "无损鉴别报告.txt", "文本文件 (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"{APP_NAME} v{__version__} 分析报告\n")
                f.write(f"开发者: {AUTHOR}\n")
                f.write("=" * 60 + "\n\n")
                for rep in self.reports.values():
                    f.write(rep.to_text())
                    f.write("\n\n" + "-" * 60 + "\n\n")
            self.statusBar().showMessage(f"报告已导出: {path}")
        except OSError as e:
            QMessageBox.critical(self, "导出失败", str(e))
