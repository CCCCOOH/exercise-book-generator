#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
pdf_maker_gui.py — “做题本 PDF 生成工具”图形界面封装
=====================================================

把 pdf_maker.py 的命令行流程封装成一个 tkinter 图形界面：

    * 选择输入PDF文件（每页=一张卡片）与输出文件夹；旧方式（直接用JPG文件夹）也可用
    * 勾选要执行的步骤（PDF转图片 → 排版A4 → 合并PDF）
    * 可勾选「只生成 PDF 文件」：脚本结束后自动删除 pages/ 与 layout/ 中间文件夹
    * 修改全部参数（纸张预设 A4/B5/A5…、每张纸题目数、PDF文件名…；DPI/间距/压缩质量保留在 config.ini 默认值，可按需微调）
    * 「开始生成」前自动把界面参数写回 config.ini，再后台运行 pdf_maker.py
    * 日志实时显示，运行中可随时「停止」

运行方式（项目目录内，macOS）：
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 pdf_maker_gui.py
  或双击项目里的  start_gui.command

注意：需要“Tk 可用的 Python”。uv 自带的 Python 不含 Tcl/Tk，
python.org 官方版自带；brew 用户需先 brew install python-tk@3.13。

仅依赖 Python 标准库（tkinter / ttk），无需额外安装。
"""

import configparser
import os
import queue
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
except ImportError:  # pragma: no cover - 提示用户用对的解释器
    print("❌ 当前 Python 没有 tkinter 支持。")
    print("请改用 Tk 可用的 Python，例如 python.org 官方版：")
    print("   /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 pdf_maker_gui.py")
    print("或执行：brew install python-tk@3.13")
    sys.exit(1)


# ============================================================
# 常量：与 pdf_maker.py / config.ini 保持一致
# ============================================================

APP_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = APP_DIR / "config.ini"
DEFAULT_PDF_MAKER = APP_DIR / "pdf_maker.py"
APP_DATA_NAME = "ZuotiBenPdfTool"   # 打包后的用户数据目录名


# ============================================================
# 运行环境工具（开发态 vs PyInstaller 冻结态）
# ============================================================

def is_frozen():
    """是否在 PyInstaller 打包后的程序里运行"""
    return bool(getattr(sys, "frozen", False))


def user_data_dir():
    """可写的用户数据目录：打包后放 config.ini 与 output/；开发态用项目目录"""
    if is_frozen():
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / APP_DATA_NAME
        return Path(os.environ.get("APPDATA", str(Path.home()))) / APP_DATA_NAME
    return APP_DIR


def engine_interpreter():
    """运行引擎的解释器：
    冻结态 = 当前程序本体（通过 --cli 分支执行引擎）；
    开发态 = 优先项目 .venv（已装 pymupdf/pillow），否则当前解释器。"""
    if is_frozen():
        return sys.executable
    venv_py = APP_DIR / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable

# 新增/缺失配置时的默认值（key 大小写无所谓，configparser 不区分大小写）
DEFAULTS = {
    "步骤控制": {
        "执行_pdf转图片": "true",
        "执行_排版页面": "true",
        "执行_合并pdf": "true",
    },
    "路径设置": {
        "输入pdf文件": "",
        "输入文件夹": "./images",
        "输出文件夹": "./output",
        "pdf文件名": "output.pdf",
    },
    "排版参数": {
        "页面宽度_mm": "210",
        "页面高度_mm": "297",
        "dpi": "300",
        "每页题目数": "2",
        "间距_mm": "3",
    },
    "PDF参数": {
        "pdf_质量": "80",
    },
    "输出设置": {
        "只生成pdf文件": "false",
    },
}

# (section, key, 标签, 类型)
# 类型: 'dir' = 目录选择框；'str' = 普通文本
# 输入PDF行与旧版JPG文件夹行在界面里按“PDF转图片”开关动态切换
PATH_FIELDS = [
    ("路径设置", "输出文件夹", "输出文件夹", "dir"),
    ("路径设置", "pdf文件名", "PDF 文件名", "str"),
]
# 常用标准纸张预设：(名称, 宽度mm, 高度mm)，顺序即下拉框顺序
PAPER_PRESETS = [
    ("A4", "210", "297"),
    ("B5", "176", "250"),
    ("A5", "148", "210"),
    ("B4", "250", "353"),
    ("A3", "297", "420"),
    ("A6", "105", "148"),
    ("Letter", "216", "279"),
    ("Legal", "216", "356"),
]
PAPER_NAMES = [name for name, _, _ in PAPER_PRESETS]

# GUI 中需要输入校验的整数项
INT_FIELDS = [
    ("排版参数", "每页题目数", "每张纸题目数"),
]

# 步骤开关（顺序与 pdf_maker.py 主流程一致）
STEPS = [
    ("执行_pdf转图片", "从 PDF 提取页面为图片（每页=一张卡片）"),
    ("执行_排版页面", "排版为所选纸张（每张 N 题、格内顶部对齐）"),
    ("执行_合并pdf", "合并为单个 PDF"),
]


# ============================================================
# 配置读写（与 GUI 解耦，便于测试/复用）
# ============================================================

def load_config_dict(config_path):
    """读取 config.ini -> {(section, key): value}，缺省值补 DEFAULT。"""
    cfg = configparser.ConfigParser()
    if Path(config_path).exists():
        cfg.read(Path(config_path), encoding="utf-8")
    result = {}
    for section, kv in DEFAULTS.items():
        for key, default in kv.items():
            try:
                result[(section, key)] = cfg.get(section, key)
            except (configparser.NoSectionError, configparser.NoOptionError):
                result[(section, key)] = default
    return result


def write_config(config_path, values):
    """把 {(section, key): value} 写回 config.ini（保留文件中已有其它键）。"""
    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    cfg = configparser.ConfigParser()
    if config_path.exists():
        cfg.read(config_path, encoding="utf-8")

    for section in DEFAULTS:
        if not cfg.has_section(section):
            cfg.add_section(section)
    for (section, key), value in values.items():
        cfg.set(section, key, str(value))

    with open(config_path, "w", encoding="utf-8") as f:
        cfg.write(f)
    return config_path


# ============================================================
# GUI 主程序
# ============================================================

class PdfMakerGUI:
    """做题本 PDF 生成工具 —— 图形界面"""

    def __init__(self, root, config_path=None, pdf_maker_path=None, base_dir=None):
        self.root = root
        if config_path is not None:
            self.config_path = Path(config_path)
        elif is_frozen():
            self.config_path = user_data_dir() / "config.ini"
        else:
            self.config_path = DEFAULT_CONFIG_PATH
        self.pdf_maker_path = Path(pdf_maker_path) if pdf_maker_path else DEFAULT_PDF_MAKER
        if base_dir is not None:
            self.base_dir = Path(base_dir)
        elif is_frozen():
            self.base_dir = user_data_dir()
        else:
            self.base_dir = APP_DIR

        # 打包后首次运行：在用户数据目录生成默认 config.ini
        if not self.config_path.exists():
            write_config(self.config_path, {
                (s, k): v for s, kv in DEFAULTS.items() for k, v in kv.items()
            })

        self.cfg_values = load_config_dict(self.config_path)
        self.vars = {}          # (section,key) -> tk var
        self.lock_widgets = []  # 运行期间禁用的控件
        self._proc = None       # 正在运行的 pdf_maker 子进程
        self._out_q = queue.Queue()
        self.running = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- 界面构建 ----------------

    def _build_ui(self):
        self.root.title("做题本 PDF 生成工具")
        self.root.geometry("960x800")
        self.root.minsize(880, 660)

        style = ttk.Style()
        try:  # 非 macOS 平台可用 clam 主题，观感更统一
            if style.theme_use() == "default":
                style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Helvetica", 16, "bold"))
        style.configure("Hint.TLabel", foreground="#666666")

        # ---- 顶部标题 ----
        header = ttk.Frame(self.root, padding=(14, 10, 14, 0))
        header.pack(fill="x")
        ttk.Label(header, text="📄 做题本 PDF 生成工具", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="pdf_maker.py 图形化封装 · 「开始生成」前会自动保存到 config.ini · 参数同步，命令行仍可用",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        # ---- 主体两栏 ----
        body = ttk.Frame(self.root, padding=(14, 8))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))

        self._build_path_frame(left).pack(fill="x")
        self._build_steps_frame(left).pack(fill="x", pady=(8, 0))
        self._build_output_frame(left).pack(fill="x", pady=(8, 0))
        self._build_paper_frame(right).pack(fill="x")
        self._build_layout_frame(right).pack(fill="x", pady=(8, 0))
        self._sync_input_rows()  # 按“从PDF提取页面”开关初始化输入行显隐

        # ---- 按钮区 ----
        btns = ttk.Frame(self.root, padding=(14, 0))
        btns.pack(fill="x")
        self.btn_start = ttk.Button(btns, text="▶  开始生成", command=self.start_run)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(btns, text="⏹  停止", command=self.stop_run, state="disabled")
        self.btn_stop.pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="💾  保存配置", command=self.save_config).pack(side="left", padx=(18, 0))
        ttk.Button(btns, text="📂  打开输出目录", command=self.open_output_dir).pack(side="left", padx=(8, 0))

        # ---- 状态区 ----
        status = ttk.Frame(self.root, padding=(14, 8, 14, 4))
        status.pack(fill="x")
        self.var_status = tk.StringVar(value="就绪：改完参数后点「开始生成」（会自动保存配置）")
        ttk.Label(status, textvariable=self.var_status).pack(side="left")
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=140)
        self.progress.pack(side="right")

        # ---- 日志区 ----
        log_frame = ttk.LabelFrame(self.root, text="运行日志", padding=(8, 4))
        log_frame.pack(fill="both", expand=True, padx=14, pady=(4, 12))
        self.log = scrolledtext.ScrolledText(
            log_frame, height=11, state="disabled", wrap="word", font=("Menlo", 11)
        )
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("ok", foreground="#1a7f37")
        self.log.tag_configure("err", foreground="#cf222e")
        self.log.tag_configure("warn", foreground="#bf8700")
        self.log.tag_configure("title", foreground="#0969da")
        self.log.tag_configure("dim", foreground="#999999")

    def _build_path_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="📁 输入 / 输出", padding=(10, 6))
        for i in range(4):
            frame.columnconfigure(1, weight=1)

        row = 0

        # ---- 输入PDF行（勾选“从PDF提取页面”时使用）----
        var_pdf = self._text_var("路径设置", "输入pdf文件")
        lbl_pdf = ttk.Label(frame, text="输入PDF文件\n（每页=一张卡片）")
        lbl_pdf.grid(row=row, column=0, sticky="w", pady=3)
        entry_pdf = ttk.Entry(frame, textvariable=var_pdf)
        entry_pdf.grid(row=row, column=1, sticky="ew", padx=(8, 4), pady=3)
        browse_pdf = ttk.Button(
            frame, text="选择PDF…", width=9,
            command=lambda v=var_pdf: self._pick_pdf(v),
        )
        browse_pdf.grid(row=row, column=2, pady=3)
        self.lock_widgets.extend([entry_pdf, browse_pdf])
        self._pdf_row_widgets = [lbl_pdf, entry_pdf, browse_pdf]
        row += 1

        # ---- 旧版：直接提供JPG的文件夹（关闭“PDF转图片”时使用）----
        var_legacy = self._text_var("路径设置", "输入文件夹")
        lbl_legacy = ttk.Label(frame, text="输入文件夹\n（现成JPG，仅关PDF转图时用）")
        lbl_legacy.grid(row=row, column=0, sticky="w", pady=3)
        entry_legacy = ttk.Entry(frame, textvariable=var_legacy)
        entry_legacy.grid(row=row, column=1, sticky="ew", padx=(8, 4), pady=3)
        browse_legacy = ttk.Button(
            frame, text="浏览…", width=6,
            command=lambda v=var_legacy: self._pick_dir(v),
        )
        browse_legacy.grid(row=row, column=2, pady=3)
        self.lock_widgets.extend([entry_legacy, browse_legacy])
        self._legacy_row_widgets = [lbl_legacy, entry_legacy, browse_legacy]
        row += 1

        # ---- 其余路径字段 ----
        for section, key, label, kind in PATH_FIELDS:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            var = self._text_var(section, key)
            entry = ttk.Entry(frame, textvariable=var)
            entry.grid(row=row, column=1, sticky="ew", padx=(8, 4), pady=3)
            self.lock_widgets.append(entry)
            if kind == "dir":
                browse = ttk.Button(
                    frame, text="浏览…", width=6,
                    command=lambda v=var: self._pick_dir(v),
                )
                browse.grid(row=row, column=2, pady=3)
                self.lock_widgets.append(browse)
            row += 1
        return frame

    def _sync_input_rows(self):
        """按“从PDF提取页面”开关显示输入PDF行 / 旧版JPG文件夹行。"""
        if not hasattr(self, "_step_vars"):
            return
        pdf_on = self._step_vars["执行_pdf转图片"].get()
        for w in self._pdf_row_widgets:
            if pdf_on:
                w.grid()
            else:
                w.grid_remove()
        for w in self._legacy_row_widgets:
            if pdf_on:
                w.grid_remove()
            else:
                w.grid()

    def _pick_pdf(self, var):
        initial = var.get() or str(APP_DIR)
        chosen = filedialog.askopenfilename(
            initialdir=str(Path(initial).parent) if var.get() else str(APP_DIR),
            title="选择输入PDF（每页一张卡片）",
            filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")],
        )
        if chosen:
            var.set(chosen)

    def _build_steps_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="⚙️  执行步骤（勾选 = 在 config.ini 中启用）", padding=(10, 6))
        self._step_vars = {}
        for i, (key, label) in enumerate(STEPS):
            section = "步骤控制"
            var = tk.BooleanVar(value=self._bool_default(section, key))
            self.vars[(section, key)] = var
            self._step_vars[key] = var
            cb = ttk.Checkbutton(
                frame, text=f"{i + 1}. {label}", variable=var,
                command=self._sync_input_rows,
            )
            cb.grid(row=i, column=0, sticky="w", pady=2)
            self.lock_widgets.append(cb)
        return frame

    def _build_output_frame(self, parent):
        """输出选项：只保留最终PDF（结束后删除 pages/ 与 layout/）"""
        frame = ttk.LabelFrame(parent, text="🗂  输出选项", padding=(10, 4))
        section, key = "输出设置", "只生成pdf文件"
        var = tk.BooleanVar(value=self._bool_default(section, key))
        self.vars[(section, key)] = var
        cb = ttk.Checkbutton(
            frame,
            text="只生成 PDF 文件（结束后删除 pages / layout 中间文件夹）",
            variable=var,
        )
        cb.grid(row=0, column=0, sticky="w", pady=1)
        self.lock_widgets.append(cb)
        ttk.Label(
            frame,
            text="勾选后输出目录只保留最终PDF；需同时勾选第 3 步「合并为单个 PDF」",
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky="w")
        return frame

    def _build_paper_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="📄  纸张大小（预设）", padding=(10, 6))
        frame.columnconfigure(1, weight=1)

        # 纸张宽/高（写入 config.ini：页面宽度_mm / 页面高度_mm）
        var_w = self._text_var("排版参数", "页面宽度_mm")
        var_h = self._text_var("排版参数", "页面高度_mm")
        # 不展示但保留的高级参数（写入config，默认即可，可在 config.ini 微调）
        self._hidden_text("排版参数", "dpi")
        self._hidden_text("排版参数", "间距_mm")
        self._hidden_text("PDF参数", "pdf_质量")

        def cur_dims():
            try:
                return int(var_w.get() or 0), int(var_h.get() or 0)
            except ValueError:
                return 0, 0

        cw, ch = cur_dims()
        matched = next(
            (n for n, w, h in PAPER_PRESETS if int(w) == cw and int(h) == ch),
            None,
        )
        options = list(PAPER_NAMES)
        if matched is None:
            options.append("自定义…")

        self.var_paper = tk.StringVar(value=matched or "自定义…")
        self.var_paper_info = tk.StringVar()
        combo = ttk.Combobox(
            frame, textvariable=self.var_paper, values=options,
            state="readonly", width=12,
        )
        combo.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=3)
        self.lock_widgets.append(combo)
        ttk.Label(frame, text="输出纸张：").grid(row=0, column=0, sticky="w", pady=3)
        info = ttk.Label(frame, textvariable=self.var_paper_info, style="Hint.TLabel")
        info.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 2))

        def refresh_info():
            sel = self.var_paper.get()
            for n, w, h in PAPER_PRESETS:
                if n == sel:
                    self.var_paper_info.set(f"{n}：宽 {w} × 高 {h} mm（成页按此尺寸生成）")
                    return
            try:
                cw, ch = int(var_w.get()), int(var_h.get())
                self.var_paper_info.set(
                    f"当前自定义 {cw}×{ch}mm：请选标准纸张，或直接改 config.ini 微调"
                )
            except ValueError:
                self.var_paper_info.set("请选择标准纸张")

        def on_paper_change(_event=None):
            sel = self.var_paper.get()
            for n, w, h in PAPER_PRESETS:
                if n == sel:
                    var_w.set(w)
                    var_h.set(h)
                    break
            refresh_info()

        combo.bind("<<ComboboxSelected>>", on_paper_change)
        self._paper_apply = on_paper_change
        refresh_info()
        return frame

    def _build_layout_frame(self, parent):
        frame = ttk.LabelFrame(parent, text="🧮  每张纸排布", padding=(10, 6))
        frame.columnconfigure(1, weight=1)
        row = 0
        for section, key, label in INT_FIELDS:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
            var = self._text_var(section, key)
            entry = ttk.Entry(frame, textvariable=var, width=6)
            entry.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=3)
            self.lock_widgets.append(entry)
            row += 1
        ttk.Label(
            frame,
            text="纸张按 N 等分（竖版单列 N 行），每道题缩放适配并在格内顶部对齐，\n下方留白用于书写；最后一张不足 N 道时按剩余数量自动排布。",
            style="Hint.TLabel",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        return frame

    # ---------------- 变量读写辅助 ----------------

    def _text_var(self, section, key):
        value = self.cfg_values.get((section, key), DEFAULTS[section][key])
        var = tk.StringVar(value=value)
        self.vars[(section, key)] = var
        return var

    def _hidden_text(self, section, key):
        """注册一个不出现在界面、但会随配置一起保存的变量。"""
        value = self.cfg_values.get((section, key), DEFAULTS[section][key])
        var = tk.StringVar(value=value)
        self.vars[(section, key)] = var
        return var

    def _bool_default(self, section, key):
        try:
            return self.cfg_values.get((section, key), "").strip().lower() in (
                "true", "yes", "on", "1",
            )
        except AttributeError:
            return False

    def _pick_dir(self, var):
        chosen = filedialog.askdirectory(initialdir=var.get() or str(APP_DIR))
        if chosen:
            var.set(chosen)

    # ---------------- 配置读写 ----------------

    def collect_values(self):
        values = {}
        for (section, key), var in self.vars.items():
            if isinstance(var, tk.BooleanVar):
                values[(section, key)] = "true" if var.get() else "false"
            else:
                values[(section, key)] = str(var.get()).strip()
        return values

    def save_config(self, show_msg=True):
        """把界面上的参数写回 config.ini。"""
        write_config(self.config_path, self.collect_values())
        if show_msg:
            self.var_status.set(f"✅ 配置已保存：{self.config_path}")
        return self.config_path

    # ---------------- 校验 ----------------

    def _validate(self):
        def get_int_var(section, key, label):
            try:
                return int(self.vars[(section, key)].get())
            except (TypeError, ValueError):
                messagebox.showerror(
                    "参数错误", f"「{label}」必须是整数，当前值为：{self.vars[(section, key)].get()!r}"
                )
                return None

        n = get_int_var("排版参数", "每页题目数", "每张纸题目数")
        if n is None:
            return False
        if not 1 <= n <= 12:
            messagebox.showerror("参数错误", "「每张纸题目数」应为 1~12。")
            return False

        w = get_int_var("排版参数", "页面宽度_mm", "纸张宽度")
        h = get_int_var("排版参数", "页面高度_mm", "纸张高度")
        gap = get_int_var("排版参数", "间距_mm", "间距")
        if None in (w, h, gap):
            return False
        if w <= 0 or h <= 0:
            messagebox.showerror("参数错误", "纸张尺寸不合法（请重新选择纸张预设）。")
            return False
        if gap < 0 or gap * 2 >= min(w, h):
            messagebox.showerror("参数错误", "「间距」过大（不得大于页面尺寸一半）。")
            return False

        # 勾选了“从PDF提取页面”就必须给出一个存在的PDF文件
        if self._step_vars["执行_pdf转图片"].get():
            pdf = self.vars[("路径设置", "输入pdf文件")].get().strip()
            if not pdf:
                messagebox.showerror(
                    "缺少输入",
                    "已勾选“从 PDF 提取页面为图片”，但还没选择 PDF 文件。\n"
                    "请把卡片PDF放到 input/ 目录后，点“选择PDF…”选择它；\n"
                    "或者取消该勾选（旧方式：直接使用输入文件夹里的JPG）。",
                )
                return False
            if not Path(pdf).exists():
                messagebox.showerror("找不到文件", f"输入PDF不存在：\n{pdf}")
                return False

        # 「只生成 PDF 文件」依赖合并步骤产出最终PDF，否则没有可保留的结果
        if self.vars[("输出设置", "只生成pdf文件")].get() and not self._step_vars["执行_合并pdf"].get():
            messagebox.showerror(
                "选项冲突",
                "已勾选「只生成 PDF 文件」，但没有勾选第 3 步「合并为单个 PDF」。\n"
                "请勾上该步骤（否则不会生成PDF，也没有中间文件可清理）。",
            )
            return False
        return True

    # ---------------- 运行控制 ----------------

    def start_run(self):
        if self.running:
            return
        if not is_frozen() and not Path(self.pdf_maker_path).exists():
            messagebox.showerror("缺少脚本", f"找不到 {self.pdf_maker_path}")
            return
        if not self._validate():
            return

        self.save_config(show_msg=False)  # 运行前自动保存

        # 当前输入输出目录（相对路径以 base_dir 为准），便于结束后提示
        out_var = self.vars[("路径设置", "输出文件夹")].get().strip()
        out_path = Path(out_var)
        if not out_path.is_absolute():
            out_path = Path(self.base_dir) / out_path
        self._last_out_dir = out_path

        self._set_running(True)
        self.log_clear()
        self._log("▶ 开始生成（参数已保存到 config.ini）……", "title")
        self._out_q = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()
        self.root.after(80, self._poll_queue)

    def _engine_command(self):
        """运行引擎的命令：
        冻结态 → 当前程序本体走 --cli 分支；开发态 → .venv python 运行 pdf_maker.py"""
        cfg = ["--config", str(self.config_path)]
        if is_frozen():
            return [sys.executable, "--cli"] + cfg
        cmd = [engine_interpreter(), "-u", str(self.pdf_maker_path)]
        return cmd + cfg

    def _worker(self):
        """后台线程：以子进程方式运行引擎，逐行转发输出。"""
        try:
            proc = subprocess.Popen(
                self._engine_command(),
                cwd=str(self.base_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,  # 独立进程组，便于连同子任务一起停止
            )
        except Exception as e:  # pragma: no cover
            self._out_q.put(None)
            return
        self._proc = proc
        try:
            for line in proc.stdout:
                self._out_q.put(line)
        finally:
            proc.stdout.close()
            self._out_q.put(None)

    def _poll_queue(self):
        """主线程定时把日志队列内容刷到界面。"""
        finished = False
        while True:
            try:
                item = self._out_q.get_nowait()
            except queue.Empty:
                break
            if item is None:
                finished = True
                break
            self._log(item)
        if finished:
            # 把剩余内容也刷完
            while True:
                try:
                    self._log(self._out_q.get_nowait())
                except queue.Empty:
                    break
            self._on_finished()
            return
        if self.running:
            self.root.after(80, self._poll_queue)

    def _on_finished(self):
        proc, self._proc = self._proc, None
        code = proc.poll() if proc else -1
        self._set_running(False)
        if code == 0:
            self._log("🎉 运行完成！", "ok")
            self.var_status.set("✅ 全部步骤完成，输出文件已生成（可点「打开输出目录」查看）")
        else:
            self._log(f"❌ 运行结束，退出码 = {code}（详见上方日志）", "err")
            self.var_status.set("❌ 运行失败或已停止，请查看日志")

    def stop_run(self):
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        if messagebox.askyesno("停止任务", "确定要停止当前任务吗？"):
            self._log("⏹ 正在停止……", "warn")
            self._kill_process(proc)
            self.var_status.set("⏹ 已请求停止，正在结束进程…")

    def _kill_process(self, proc):
        """先 SIGTERM 整个进程组（含多进程子任务），3 秒后仍未退出则 SIGKILL。"""
        def term():
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

        def force():
            try:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        threading.Thread(target=term, daemon=True).start()
        threading.Timer(3.0, force).start()

    def _set_running(self, flag):
        self.running = flag
        self.btn_start.config(state="disabled" if flag else "normal")
        self.btn_stop.config(state="normal" if flag else "disabled")
        for w in self.lock_widgets:
            w.config(state="disabled" if flag else "normal")
        if flag:
            self.progress.start(12)
        else:
            self.progress.stop()

    # ---------------- 日志 ----------------

    _STEP_RE = re.compile(r"步骤([0-6])\s*[:：]")

    def log_clear(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def _log(self, text, tag=None):
        line = str(text).rstrip("\n").rstrip("\r")
        if not line.strip():
            return
        # 跳过纯分隔线
        if set(line.strip()) == {"="}:
            return

        tag = None
        if "🎉" in line or "✅" in line:
            tag = "ok"
        elif "❌" in line or "失败" in line or "错误" in line:
            tag = "err"
        elif "⚠" in line or "⏭" in line or "跳过" in line:
            tag = "warn"
        elif self._STEP_RE.search(line):
            tag = "title"

        m = self._STEP_RE.search(line)
        if m:
            self.var_status.set(f"▶ 运行中… 步骤 {m.group(1)}：{line.split(':', 1)[-1].strip()}")
        elif self.running and self.var_status.get().startswith("▶"):
            self.var_status.set(self.var_status.get())

        self.log.config(state="normal")
        self.log.insert("end", line + "\n", tag)
        # 日志太长时截断，避免卡顿
        if int(self.log.index("end-1c").split(".")[0]) > 3000:
            self.log.delete("1.0", "500.0")
        self.log.see("end")
        self.log.config(state="disabled")

    # ---------------- 其它 ----------------

    def open_output_dir(self):
        folder = getattr(self, "_last_out_dir", None)
        if folder is None:
            raw = self.vars[("路径设置", "输出文件夹")].get().strip()
            folder = Path(raw)
            if not folder.is_absolute():
                folder = Path(self.base_dir) / folder
        if not folder.exists():
            messagebox.showinfo("提示", f"输出目录尚不存在：{folder}")
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:  # pragma: no cover
            subprocess.Popen(["xdg-open", str(folder)])

    def _on_close(self):
        if self.running:
            if not messagebox.askyesno("退出", "任务正在运行，停止并退出吗？"):
                return
            if self._proc is not None:
                self._kill_process(self._proc)
        self.root.destroy()


def main():
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print("❌ 无法创建图形窗口：当前 Python 缺少完整的 Tcl/Tk 运行时。")
        print("   （uv 自带的 Python 不含 Tk；请换用 python.org 官方版，")
        print("     或先执行 brew install python-tk@3.13）")
        print("   推荐运行：")
        print("   /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 pdf_maker_gui.py")
        print(f"   详细信息：{e}")
        sys.exit(1)
    PdfMakerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
