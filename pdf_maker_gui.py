#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
pdf_maker_gui.py — “做题本 PDF 生成工具”图形界面封装
=====================================================

把 core/pdf_engine.py 的命令行流程封装成一个 tkinter 图形界面：

    * 选择输入形式：PDF 文件（每页=一张卡片）或图片文件夹
    * 自动完成导入、排版、合并，生成完整做题本 PDF
    * 可勾选「只生成 PDF 文件」：脚本结束后自动删除 pages/ 与 layout/ 中间文件夹
    * 修改全部参数（纸张预设 A4/B5/A5…、每张纸题目数、PDF文件名…；DPI/间距/压缩质量保留在 config.ini 默认值，可按需微调）
    * 「开始生成」前自动把界面参数写回 config.ini，再后台运行 core/pdf_engine.py
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

# 统一入口：CLI 在加载 Tk 之前分流，兼容没有 Tk 的引擎虚拟环境。
if __name__ == "__main__" and "--cli" in sys.argv[1:]:
    import argparse
    from core.pdf_engine import engine_main

    parser = argparse.ArgumentParser(description="做题本 PDF 生成工具")
    parser.add_argument("--cli", action="store_true")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    config_path = args.config
    if config_path is None:
        if getattr(sys, "frozen", False):
            data_root = (Path.home() / "Library" / "Application Support" if sys.platform == "darwin"
                         else Path(os.environ.get("APPDATA", str(Path.home()))))
            config_path = data_root / "ZuotiBenPdfTool" / "config.ini"
        else:
            config_path = Path(__file__).resolve().parent / "config.ini"
    sys.exit(0 if engine_main(str(config_path)) else 1)


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
# 常量：与 core/pdf_engine.py / config.ini 保持一致
# ============================================================

APP_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = APP_DIR / "config.ini"
DEFAULT_PDF_MAKER = APP_DIR / "core" / "pdf_engine.py"
APP_DATA_NAME = "ZuotiBenPdfTool"   # 保留历史数据目录，应用更名后继续读取原有设置


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
        "输入类型": "pdf",
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
    "封面设置": {
        "生成封面": "false",
        "标题": "我的做题本",
        "描述": "",
        "封面图片": "",
    },
}

# 输入形式（写入 config.ini 的 输入类型）
INPUT_TYPE_PDF = "pdf"
INPUT_TYPE_FOLDER = "folder"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

# (section, key, 标签, 类型)
# 类型: 'dir' = 目录选择框；'str' = 普通文本
# 输入PDF行与图片文件夹行在界面里按“输入形式”动态切换
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

# ============================================================
# 配置读写（与 GUI 解耦，便于测试/复用）
# ============================================================

def normalize_input_type(value):
    """把配置里的输入类型统一为 pdf 或 folder。"""
    value = str(value or "").strip().casefold()
    if value in {"pdf", "pdf文件", "file"}:
        return INPUT_TYPE_PDF
    if value in {"folder", "dir", "directory", "images", "image_folder",
                 "文件夹", "图片文件夹"}:
        return INPUT_TYPE_FOLDER
    return ""


def load_config_dict(config_path):
    """读取 config.ini -> {(section, key): value}，缺省值补 DEFAULT。"""
    cfg = configparser.ConfigParser(interpolation=None)
    if Path(config_path).exists():
        cfg.read(Path(config_path), encoding="utf-8")
    result = {}
    for section, kv in DEFAULTS.items():
        for key, default in kv.items():
            try:
                result[(section, key)] = cfg.get(section, key)
            except (configparser.NoSectionError, configparser.NoOptionError):
                value = default
                # 旧配置没有“输入类型”：按原来的 PDF 转图片开关推断。
                if (section, key) == ("路径设置", "输入类型"):
                    try:
                        pdf_enabled = cfg.getboolean("步骤控制", "执行_pdf转图片")
                    except (configparser.NoSectionError, configparser.NoOptionError,
                            ValueError):
                        pdf_enabled = True
                    value = INPUT_TYPE_PDF if pdf_enabled else INPUT_TYPE_FOLDER
                result[(section, key)] = value
    return result


def write_config(config_path, values):
    """把 {(section, key): value} 写回 config.ini（保留文件中已有其它键）。"""
    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    cfg = configparser.ConfigParser(interpolation=None)
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
        self.root.title("SYNC题本神器")
        self.root.geometry("1120x820")
        self.root.minsize(980, 740)
        self.root.configure(bg="#ffffff")
        self.font = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=(self.font, 12), background="#ffffff", foreground="#292929")
        style.configure("TFrame", background="#ffffff")
        style.configure("TLabel", background="#ffffff")
        style.configure("Hint.TLabel", foreground="#808080", font=(self.font, 11))
        style.configure("Section.TLabel", font=(self.font, 13, "bold"))
        style.configure("TEntry", padding=9, fieldbackground="#fafafa", bordercolor="#e5e5e5", lightcolor="#e5e5e5", darkcolor="#e5e5e5")
        style.configure("TCombobox", padding=8, fieldbackground="#fafafa", arrowsize=14)
        style.map("TCombobox", fieldbackground=[("readonly", "#fafafa")], selectbackground=[("readonly", "#fafafa")], selectforeground=[("readonly", "#292929")])
        style.configure("TButton", padding=(14, 9), background="#f3f3f3", borderwidth=0, focusthickness=0)
        style.map("TButton", background=[("active", "#e8e8e8")])
        style.configure("Primary.TButton", background="#252525", foreground="#ffffff", font=(self.font, 12, "bold"), padding=(22, 12))
        style.map("Primary.TButton", background=[("disabled", "#cccccc"), ("active", "#444444")], foreground=[("disabled", "#ffffff")])
        style.configure("Source.TRadiobutton", padding=(14, 12), background="#f5f5f5", indicatorrelief="flat")
        style.map("Source.TRadiobutton", background=[("selected", "#e5eee9"), ("active", "#eeeeee")])
        style.configure("TCheckbutton", background="#ffffff", padding=4)
        style.configure("TProgressbar", troughcolor="#f1f1f1", background="#33836c", borderwidth=0, thickness=4)
        self._init_cover_variables()

        sidebar = tk.Frame(self.root, bg="#f7f7f8", width=200)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="◈  SYNC", bg="#f7f7f8", fg="#222222", font=(self.font, 21, "bold")).pack(anchor="w", padx=22, pady=(28, 4))
        tk.Label(sidebar, text="你的专属做题空间", bg="#f7f7f8", fg="#888888", font=(self.font, 11)).pack(anchor="w", padx=22)
        tk.Label(sidebar, text="▤   制作做题本", bg="#e9e9eb", fg="#252525", font=(self.font, 12), anchor="w", padx=14, pady=12).pack(fill="x", padx=12, pady=(36, 8))
        ttk.Button(sidebar, text="打开输出文件夹", command=self.open_output_dir).pack(fill="x", padx=12, pady=4)
        save = ttk.Button(sidebar, text="保存当前设置", command=self.save_config)
        save.pack(fill="x", padx=12, pady=4)
        self.lock_widgets.append(save)
        cover = ttk.Button(sidebar, text="封面设置", command=self.open_cover_settings)
        cover.pack(fill="x", padx=12, pady=4)
        self.lock_widgets.append(cover)
        tk.Label(sidebar, text="本地处理 · 专注练习\n题目文件留在你的设备上", justify="left", bg="#f7f7f8", fg="#969696", font=(self.font, 10)).pack(side="bottom", anchor="w", padx=22, pady=24)

        main = ttk.Frame(self.root, padding=(32, 18, 32, 16))
        main.pack(side="left", fill="both", expand=True)
        ttk.Label(main, text="做题本工作台", style="Hint.TLabel").pack(anchor="w")
        ttk.Label(main, text="把题目，变成你的下一次进步。", font=(self.font, 24, "bold")).pack(anchor="w", pady=(16, 6))
        ttk.Label(main, text="导入题目卡片，设置纸张与留白，一键生成适合打印的 PDF。", style="Hint.TLabel").pack(anchor="w", pady=(0, 22))

        body = ttk.Frame(main)
        body.pack(fill="x")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, minsize=220)
        editor = ttk.Frame(body)
        editor.grid(row=0, column=0, sticky="nsew", padx=(0, 28))
        self._build_path_frame(editor).pack(fill="x")
        self._build_paper_frame(editor).pack(fill="x", pady=(16, 0))
        self._build_output_frame(editor).pack(fill="x", pady=(16, 0))

        preview = ttk.Frame(body)
        preview.grid(row=0, column=1, sticky="n")
        ttk.Label(preview, text="排版示意", style="Section.TLabel").pack(anchor="w")
        self.preview = tk.Canvas(preview, width=220, height=285, bg="#f7f7f8", highlightthickness=0)
        self.preview.pack(pady=(12, 8))
        self.var_summary = tk.StringVar()
        ttk.Label(preview, textvariable=self.var_summary, style="Hint.TLabel", justify="center").pack()
        ttk.Label(preview, text="题目顶部对齐\n下方留白，思路自由展开", style="Hint.TLabel", justify="center").pack(pady=(14, 0))
        self.var_paper.trace_add("write", self._refresh_preview)
        self.vars[("排版参数", "每页题目数")].trace_add("write", self._refresh_preview)
        self._sync_input_rows()
        self._refresh_preview()

        actions = ttk.Frame(main)
        actions.pack(fill="x", pady=(16, 10))
        self.btn_start = ttk.Button(actions, text="生成做题本  ↑", style="Primary.TButton", command=self.start_run)
        self.btn_start.pack(side="right")
        self.btn_stop = ttk.Button(actions, text="停止", command=self.stop_run, state="disabled")
        self.btn_stop.pack(side="right", padx=8)
        self.var_status = tk.StringVar(value="准备就绪，选择题目来源即可开始")
        ttk.Label(actions, textvariable=self.var_status, style="Hint.TLabel", wraplength=440).pack(side="left")
        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 12))
        ttk.Label(main, text="生成记录", style="Hint.TLabel").pack(anchor="w", pady=(0, 6))
        self.log = scrolledtext.ScrolledText(main, height=5, state="disabled", wrap="word", font=(self.font, 11), bg="#fafafa", fg="#606060", relief="flat", borderwidth=0, padx=12, pady=10, highlightthickness=1, highlightbackground="#eeeeee")
        self.log.pack(fill="both", expand=True)
        for tag, color in {"ok": "#28745b", "err": "#b43b3b", "warn": "#a16d21", "title": "#333333", "dim": "#999999"}.items():
            self.log.tag_configure(tag, foreground=color)
        self._log("选择一个 PDF 或图片文件夹，开始制作你的做题本。", "dim")

    def _build_path_frame(self, parent):
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="01  题目来源", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 12))
        self.var_input_type = self._text_var("路径设置", "输入类型")
        self.var_input_type.set(normalize_input_type(self.var_input_type.get()) or INPUT_TYPE_PDF)
        modes = ttk.Frame(frame)
        modes.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        for col, (value, label) in enumerate(((INPUT_TYPE_PDF, "PDF · 每页一题"), (INPUT_TYPE_FOLDER, "图片文件夹 · 每图一题"))):
            modes.columnconfigure(col, weight=1)
            button = ttk.Radiobutton(modes, text=label, variable=self.var_input_type, value=value, style="Source.TRadiobutton", command=self._sync_input_rows)
            button.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0))
            self.lock_widgets.append(button)
        self._input_rows = {}
        for value, key in ((INPUT_TYPE_PDF, "输入pdf文件"), (INPUT_TYPE_FOLDER, "输入文件夹")):
            row = ttk.Frame(frame)
            row.columnconfigure(0, weight=1)
            row.grid(row=2, column=0, columnspan=2, sticky="ew")
            var = self._text_var("路径设置", key)
            entry = ttk.Entry(row, textvariable=var)
            entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
            pick = self._pick_pdf if value == INPUT_TYPE_PDF else self._pick_dir
            button = ttk.Button(row, text="选择 PDF" if value == INPUT_TYPE_PDF else "选择文件夹", command=lambda v=var, p=pick: p(v))
            button.grid(row=0, column=1)
            self.lock_widgets.extend([entry, button])
            self._input_rows[value] = row
        self.var_source_hint = tk.StringVar()
        ttk.Label(frame, textvariable=self.var_source_hint, style="Hint.TLabel", wraplength=460).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        # GUI always generates a complete book; legacy step switches remain usable in CLI.
        self._step_vars = {}
        for key in DEFAULTS["步骤控制"]:
            var = tk.BooleanVar(value=True)
            self.vars[("步骤控制", key)] = var
            self._step_vars[key] = var
        return frame

    def _sync_input_rows(self):
        source = self.var_input_type.get()
        for value, row in self._input_rows.items():
            if value == source:
                row.grid()
            else:
                row.grid_remove()
        self._step_vars["执行_pdf转图片"].set(source == INPUT_TYPE_PDF)
        self.var_source_hint.set("按 PDF 页码顺序导入，每一页作为一张独立题目卡片。" if source == INPUT_TYPE_PDF else "支持 JPG、PNG、WebP、BMP、TIFF；按文件名自然排序（1、2、10），不包含子文件夹。")

    def _pick_pdf(self, var):
        raw = var.get().strip()
        initial = self._resolve_path(raw).parent if raw else self.base_dir
        chosen = filedialog.askopenfilename(parent=self.root, initialdir=str(initial), title="选择题目 PDF（每页一题）", filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")])
        if chosen:
            var.set(chosen)

    def _build_paper_frame(self, parent):
        frame = ttk.Frame(parent)
        ttk.Label(frame, text="02  排版设置", style="Section.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))
        var_w = self._text_var("排版参数", "页面宽度_mm")
        var_h = self._text_var("排版参数", "页面高度_mm")
        for section, key in (("排版参数", "dpi"), ("排版参数", "间距_mm"), ("PDF参数", "pdf_质量")):
            self._hidden_text(section, key)
        matched = next((name for name, w, h in PAPER_PRESETS if (w, h) == (var_w.get(), var_h.get())), "自定义")
        self.var_paper = tk.StringVar(value=matched)
        ttk.Label(frame, text="纸张", style="Hint.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8))
        combo = ttk.Combobox(frame, textvariable=self.var_paper, values=PAPER_NAMES + (["自定义"] if matched == "自定义" else []), state="readonly", width=9)
        combo.grid(row=1, column=1, sticky="w")
        ttk.Label(frame, text="每页题目", style="Hint.TLabel").grid(row=1, column=2, sticky="w", padx=(20, 8))
        count = ttk.Spinbox(frame, from_=1, to=12, textvariable=self._text_var("排版参数", "每页题目数"), width=4)
        count.grid(row=1, column=3, sticky="w")
        self.lock_widgets.extend([combo, count])
        def on_paper_change(_event=None):
            for name, w, h in PAPER_PRESETS:
                if name == self.var_paper.get():
                    var_w.set(w)
                    var_h.set(h)
                    break
            self._refresh_preview()
        combo.bind("<<ComboboxSelected>>", on_paper_change)
        return frame

    def _build_output_frame(self, parent):
        frame = ttk.Frame(parent)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="03  保存做题本", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        for row, (section, key, label, kind) in enumerate(PATH_FIELDS, 1):
            ttk.Label(frame, text=label, style="Hint.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 10))
            var = self._text_var(section, key)
            entry = ttk.Entry(frame, textvariable=var)
            entry.grid(row=row, column=1, columnspan=1 if kind == "dir" else 2, sticky="ew", pady=4)
            self.lock_widgets.append(entry)
            if kind == "dir":
                button = ttk.Button(frame, text="更改", command=lambda v=var: self._pick_dir(v))
                button.grid(row=row, column=2, padx=(6, 0))
                self.lock_widgets.append(button)
        var = tk.BooleanVar(value=self._bool_default("输出设置", "只生成pdf文件"))
        self.vars[("输出设置", "只生成pdf文件")] = var
        check = ttk.Checkbutton(frame, text="仅保留成品 PDF，完成后清理中间文件", variable=var)
        check.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.lock_widgets.append(check)
        return frame

    def _refresh_preview(self, *_):
        if not hasattr(self, "preview"):
            return
        c = self.preview
        c.delete("all")
        try:
            n = int(self.vars[("排版参数", "每页题目数")].get())
            w = int(self.vars[("排版参数", "页面宽度_mm")].get())
            h = int(self.vars[("排版参数", "页面高度_mm")].get())
            if not 1 <= n <= 12 or min(w, h) <= 0:
                raise ValueError
        except ValueError:
            self.var_summary.set("请输入 1–12 道题")
            return
        scale = min(170 / w, 249 / h)
        pw, ph = w * scale, h * scale
        x, y = (220 - pw) / 2, (285 - ph) / 2
        c.create_rectangle(x+3, y+4, x+pw+3, y+ph+4, fill="#e6e6e8", outline="")
        c.create_rectangle(x, y, x+pw, y+ph, fill="#ffffff", outline="#dedede")
        band = (ph - 16) / n
        for i in range(n):
            top = y + 8 + i * band
            c.create_rectangle(x+9, top, x+pw-9, top+max(3, min(19, band*0.3)), fill="#e4eee9", outline="")
            if band > 32:
                c.create_text(x+15, top+9, text=f"{i+1:02d}  题目卡片", anchor="w", font=(self.font, 8), fill="#517466")
            if i < n-1:
                c.create_line(x+9, top+band-4, x+pw-9, top+band-4, fill="#e9e9e9", dash=(3, 3))
        self.var_summary.set(f"{self.var_paper.get()} · {w} × {h} mm · 每页 {n} 题\n末页按剩余题目自动分配空间")

    def _resolve_path(self, raw):
        path = Path(raw).expanduser()
        return path if path.is_absolute() else self.base_dir / path

    # ---------------- 封面设置 ----------------

    def _init_cover_variables(self):
        self.var_cover_enabled = tk.BooleanVar(value=self._bool_default("封面设置", "生成封面"))
        self.var_cover_title = self._text_var("封面设置", "标题")
        self.var_cover_description = self._text_var("封面设置", "描述")
        self.var_cover_image = self._text_var("封面设置", "封面图片")
        self.var_cover_summary = tk.StringVar()
        self.vars[("封面设置", "生成封面")] = self.var_cover_enabled
        self._cover_dialog = None
        self._cover_fields = []
        for var in (self.var_cover_enabled, self.var_cover_title,
                    self.var_cover_description, self.var_cover_image):
            var.trace_add("write", self._refresh_cover_summary)
        self._refresh_cover_summary()

    def _refresh_cover_summary(self, *_):
        if hasattr(self, "var_cover_summary"):
            if self.var_cover_enabled.get():
                title = self.var_cover_title.get().strip() or "未命名封面"
                image = "已选图片" if self.var_cover_image.get().strip() else "纯文字设计"
                self.var_cover_summary.set(f"封面：{title} · {image}  › 编辑")
            else:
                self.var_cover_summary.set("添加封面（标题、描述与可选封面图片）  ›")
        self._set_cover_dialog_state()

    def _set_cover_dialog_state(self):
        if not self._cover_dialog or not self._cover_dialog.winfo_exists():
            return
        self._cover_enable_control.config(state="disabled" if self.running else "normal")
        state = "normal" if self.var_cover_enabled.get() and not self.running else "disabled"
        for field in self._cover_fields:
            if isinstance(field, ttk.Combobox):
                field.config(state="readonly" if state == "normal" else "disabled")
            else:
                field.config(state=state)
        self._refresh_cover_card()

    def _pick_cover_image(self):
        raw = self.var_cover_image.get().strip()
        initial = self._resolve_path(raw).parent if raw else self.base_dir
        chosen = filedialog.askopenfilename(
            parent=self._cover_dialog or self.root,
            initialdir=str(initial),
            title="选择封面图片",
            filetypes=[("支持的图片", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"),
                       ("所有文件", "*.*")],
        )
        if chosen:
            self.var_cover_image.set(chosen)

    def _refresh_cover_card(self, *_):
        if not hasattr(self, "cover_card"):
            return
        c = self.cover_card
        c.delete("all")
        c.create_rectangle(32, 8, 188, 224, fill="#f7f6f2", outline="#dedede")
        c.create_rectangle(44, 26, 176, 100, fill="#dcebe5" if not self.var_cover_image.get().strip() else "#bdd8cd", outline="")
        c.create_rectangle(44, 118, 76, 122, fill="#2e7964", outline="")
        title = self.var_cover_title.get().strip() or "我的做题本"
        c.create_text(44, 138, text=title[:18], width=124, anchor="nw", font=(self.font, 11, "bold"), fill="#202522")
        description = self.var_cover_description.get().strip()
        c.create_text(44, 180, text=description[:44] or "标题与描述会显示在这里", width=124, anchor="nw", font=(self.font, 8), fill="#5b625e")
        c.create_text(44, 212, text="SYNC题本神器", anchor="sw", font=(self.font, 7), fill="#2e7964")

    def open_cover_settings(self):
        if self._cover_dialog and self._cover_dialog.winfo_exists():
            self._cover_dialog.deiconify()
            self._cover_dialog.lift()
            return
        dialog = tk.Toplevel(self.root)
        self._cover_dialog = dialog
        dialog.title("设计题本封面")
        dialog.geometry("650x480")
        dialog.minsize(600, 440)
        dialog.configure(bg="#ffffff")
        dialog.transient(self.root)
        dialog.columnconfigure(0, weight=1)
        dialog.columnconfigure(1, minsize=220)
        dialog.rowconfigure(0, weight=1)
        form = ttk.Frame(dialog, padding=(26, 24, 18, 22))
        form.grid(row=0, column=0, sticky="nsew")
        ttk.Label(form, text="设计题本封面", font=(self.font, 19, "bold")).pack(anchor="w")
        ttk.Label(form, text="封面将作为 PDF 的第一页。图片可选，标题和描述会自动排版。", style="Hint.TLabel", wraplength=360).pack(anchor="w", pady=(5, 17))
        enabled = ttk.Checkbutton(form, text="生成题本封面", variable=self.var_cover_enabled)
        enabled.pack(anchor="w", pady=(0, 14))
        ttk.Label(form, text="标题", style="Hint.TLabel").pack(anchor="w")
        title = ttk.Entry(form, textvariable=self.var_cover_title)
        title.pack(fill="x", pady=(4, 12))
        ttk.Label(form, text="描述（可选）", style="Hint.TLabel").pack(anchor="w")
        description = tk.Text(form, height=4, wrap="word", font=(self.font, 11), bg="#fafafa", fg="#292929", relief="flat", borderwidth=0, padx=9, pady=8, highlightthickness=1, highlightbackground="#e5e5e5")
        description.insert("1.0", self.var_cover_description.get())
        description.pack(fill="x", pady=(4, 12))
        def sync_description(_event=None):
            self.var_cover_description.set(description.get("1.0", "end-1c"))
        description.bind("<KeyRelease>", sync_description)
        description.bind("<FocusOut>", sync_description)
        ttk.Label(form, text="封面图片（可选）", style="Hint.TLabel").pack(anchor="w")
        image_row = ttk.Frame(form)
        image_row.pack(fill="x", pady=(4, 0))
        image_row.columnconfigure(0, weight=1)
        image = ttk.Entry(image_row, textvariable=self.var_cover_image)
        image.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        choose = ttk.Button(image_row, text="选择图片", command=self._pick_cover_image)
        choose.grid(row=0, column=1)
        hint = ttk.Label(form, text="支持 JPG、PNG、WebP、BMP、TIFF。图片会铺满封面上方视觉区。", style="Hint.TLabel", wraplength=360)
        hint.pack(anchor="w", pady=(7, 0))
        preview = ttk.Frame(dialog, padding=(8, 24, 24, 22))
        preview.grid(row=0, column=1, sticky="nsew")
        ttk.Label(preview, text="封面预览", style="Section.TLabel").pack(anchor="w")
        self.cover_card = tk.Canvas(preview, width=220, height=235, bg="#ffffff", highlightthickness=0)
        self.cover_card.pack(pady=(12, 10))
        done = ttk.Button(preview, text="完成", style="Primary.TButton", command=dialog.withdraw)
        done.pack(fill="x")
        self._cover_enable_control = enabled
        self._cover_fields = [title, description, image, choose]
        self.lock_widgets.extend([enabled, *self._cover_fields])
        dialog.protocol("WM_DELETE_WINDOW", dialog.withdraw)
        self._set_cover_dialog_state()
        self._refresh_cover_card()

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
        chosen = filedialog.askdirectory(parent=self.root, initialdir=str(self._resolve_path(var.get().strip())) if var.get().strip() else str(self.base_dir))
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
        for key in ("输入pdf文件", "输入文件夹", "输出文件夹"):
            raw = values[("路径设置", key)]
            if raw:
                values[("路径设置", key)] = str(self._resolve_path(raw))
        cover_image = values[("封面设置", "封面图片")]
        if cover_image:
            values[("封面设置", "封面图片")] = str(self._resolve_path(cover_image))
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

        dpi = get_int_var("排版参数", "dpi", "DPI")
        quality = get_int_var("PDF参数", "pdf_质量", "PDF 质量")
        if dpi is None or quality is None:
            return False
        if not 36 <= dpi <= 600 or not 1 <= quality <= 100 or h <= (n + 1) * gap:
            messagebox.showerror("参数错误", "DPI 应为 36–600，质量应为 1–100，间距需为每道题留出有效空间。")
            return False
        source = self.var_input_type.get()
        key = "输入pdf文件" if source == INPUT_TYPE_PDF else "输入文件夹"
        raw = self.vars[("路径设置", key)].get().strip()
        path = self._resolve_path(raw)
        if not raw or (not path.is_file() if source == INPUT_TYPE_PDF else not path.is_dir()):
            messagebox.showerror("缺少输入", "请选择有效的 PDF 文件。" if source == INPUT_TYPE_PDF else "请选择有效的图片文件夹。")
            return False
        if source == INPUT_TYPE_PDF and path.suffix.lower() != ".pdf":
            messagebox.showerror("输入格式错误", "请选择 PDF 文件，或切换到图片文件夹。")
            return False
        if source == INPUT_TYPE_FOLDER:
            try:
                found = any(p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS for p in path.iterdir())
            except OSError as exc:
                messagebox.showerror("无法读取文件夹", str(exc))
                return False
            if not found:
                messagebox.showerror("没有题目图片", "文件夹中没有支持的图片。支持 JPG、PNG、WebP、BMP、TIFF，不搜索子文件夹。")
                return False
        out = self.vars[("路径设置", "输出文件夹")].get().strip()
        name_var = self.vars[("路径设置", "pdf文件名")]
        name = name_var.get().strip()
        if not out or not name or name in {".", ".."} or any(c in name for c in '/\\:*?"<>|'):
            messagebox.showerror("输出设置错误", "请选择输出文件夹，并填写不含路径或特殊字符的 PDF 文件名。")
            return False
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        name_var.set(name)
        output = self._resolve_path(out)
        if output.exists() and not output.is_dir():
            messagebox.showerror("输出设置错误", "输出位置必须是文件夹。")
            return False
        if source == INPUT_TYPE_PDF and (output / name).resolve() == path.resolve():
            messagebox.showerror("输出设置错误", "成品路径与输入 PDF 相同，请修改文件名或输出文件夹。")
            return False
        if self.var_cover_enabled.get():
            title = self.var_cover_title.get().strip()
            description = self.var_cover_description.get().strip()
            if not title or len(title) > 64 or len(description) > 240:
                messagebox.showerror("封面信息错误", "封面标题不能为空且不超过 64 个字符；描述不超过 240 个字符。")
                return False
            raw_cover_image = self.var_cover_image.get().strip()
            if raw_cover_image:
                cover_image = self._resolve_path(raw_cover_image)
                if not cover_image.is_file() or cover_image.suffix.casefold() not in IMAGE_EXTENSIONS:
                    messagebox.showerror("封面图片错误", "请选择有效的封面图片。支持 JPG、PNG、WebP、BMP、TIFF。")
                    return False
                for reserved in (output / "pages", output / "layout"):
                    try:
                        cover_image.resolve().relative_to(reserved.resolve())
                        messagebox.showerror("封面图片错误", "封面图片不能位于输出目录的 pages 或 layout 中。")
                        return False
                    except ValueError:
                        pass
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

        try:
            self.save_config(show_msg=False)
        except OSError as exc:
            messagebox.showerror("无法保存设置", str(exc))
            return

        # 当前输入输出目录（相对路径以 base_dir 为准），便于结束后提示
        out_var = self.vars[("路径设置", "输出文件夹")].get().strip()
        self._last_out_dir = self._resolve_path(out_var)

        self._set_running(True)
        self.log_clear()
        self._log("开始制作做题本…", "title")
        self._out_q = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()
        self.root.after(80, self._poll_queue)

    def _engine_command(self):
        """运行引擎的命令：
        冻结态 → 当前程序本体走 --cli 分支；开发态 → .venv python 运行 core/pdf_engine.py"""
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
            self._out_q.put(f"❌ 无法启动生成任务: {e}")
            self._out_q.put(None)
            return
        self._proc = proc
        try:
            for line in proc.stdout:
                self._out_q.put(line)
        finally:
            proc.stdout.close()
            proc.wait()
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
            self.var_status.set("已完成，做题本已保存到输出文件夹")
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
            w.config(state="disabled" if flag else ("readonly" if isinstance(w, ttk.Combobox) else "normal"))
        self._set_cover_dialog_state()
        if flag:
            self.var_status.set("正在准备题目卡片…")
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
            folder = self._resolve_path(raw)
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
