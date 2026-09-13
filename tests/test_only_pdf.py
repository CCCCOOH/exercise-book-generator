#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tests/test_only_pdf.py —— 中间文件隔离的回归测试
==================================================

覆盖：新旧开关值都不向输出目录写中间文件；失败任务也不残留；
输出目录中原有用户文件不会被删除；旧配置仍向后兼容。

运行（需要 .venv 里的 pymupdf/pillow）：
    .venv/bin/python tests/test_only_pdf.py
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ENGINE = ROOT / "core" / "pdf_engine.py"

CONFIG = """[步骤控制]
执行_pdf转图片 = {pdf2img}
执行_排版页面 = {layout}
执行_合并pdf = {merge}

[路径设置]
输入pdf文件 = {input_pdf}
输入文件夹 = {input_folder}
输出文件夹 = ./output
pdf文件名 = output.pdf

[排版参数]
页面宽度_mm = 210
页面高度_mm = 297
dpi = 120
每页题目数 = 2
间距_mm = 3

[PDF参数]
pdf_质量 = 80

[输出设置]
只生成pdf文件 = {only_pdf}
"""

RESULTS = []
WORK = None


def check(name, cond, detail=""):
    RESULTS.append((name, cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")


def make_cards(pdf_path):
    """生成 3 页的测试卡片PDF"""
    import pymupdf

    doc = pymupdf.open()
    for i in range(1, 4):
        page = doc.new_page(width=400, height=300)
        page.insert_text((40, 60), f"Question {i}", fontsize=20)
        page.insert_text((40, 100), "x^2 + 2x + 1 = 0", fontsize=14)
        page.insert_text((40, 130), "A. 1   B. 2   C. 3   D. 4", fontsize=12)
    doc.save(str(pdf_path))
    doc.close()


def setup(case):
    """建一个干净的临时工作目录（含测试用卡片PDF）"""
    global WORK
    if WORK is not None:
        shutil.rmtree(WORK, ignore_errors=True)
    WORK = Path(tempfile.mkdtemp(prefix="onlypdf_", dir=str(HERE)))
    (WORK / "input").mkdir(parents=True)
    make_cards(WORK / "input" / "cards.pdf")
    return WORK


def write_cfg(d, **flags):
    cfg = {
        "pdf2img": "true", "layout": "true", "merge": "true",
        "only_pdf": "false", "input_pdf": "./input/cards.pdf",
        "input_folder": "./images",
    }
    cfg.update(flags)
    cfg_path = d / "config.ini"
    cfg_path.write_text(CONFIG.format(**cfg), encoding="utf-8")
    return cfg_path


def engine(cfg_path, d):
    proc = subprocess.run(
        [sys.executable, "-u", str(ENGINE), "--config", str(cfg_path)],
        cwd=str(d), capture_output=True, encoding="utf-8", errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def state(d):
    return {
        "pdf": (d / "output" / "output.pdf").exists(),
        "pages": (d / "output" / "pages").exists(),
        "layout": (d / "output" / "layout").exists(),
    }


def report(title, code, out, st):
    print(f"\n{'=' * 72}\n【{title}】exit={code} pdf={st['pdf']} "
          f"pages={st['pages']} layout={st['layout']}")
    for line in out.splitlines():
        if any(k in line for k in ("步骤", "🗑", "⚠", "❌")):
            print("   |", line.strip())


def main():
    # 不论旧开关的值如何，输出目录都只接收完成的 PDF。
    for label, only_pdf in (("A 新默认配置", "true"), ("B 兼容旧关闭值", "false")):
        d = setup(label)
        code, out = engine(write_cfg(d, only_pdf=only_pdf), d)
        st = state(d)
        report(label, code, out, st)
        check(f"{label} 退出码0", code == 0)
        check(f"{label} PDF存在", st["pdf"])
        check(f"{label} 无pages", not st["pages"])
        check(f"{label} 无layout", not st["layout"])
        check(f"{label} 专用工作区日志", "应用专用工作区" in out)

    # 失败也不应把任何工作产物留在输出目录。
    d = setup("C")
    code, out = engine(write_cfg(d, layout="false"), d)
    st = state(d)
    report("C 失败任务", code, out, st)
    check("C 退出码非0", code != 0)
    check("C 无PDF/pages/layout", not any(st.values()))

    # 应用不删除输出目录中本来就存在的用户文件。
    d = setup("D")
    (d / "output" / "pages").mkdir(parents=True)
    (d / "output" / "layout").mkdir(parents=True)
    page = d / "output" / "pages" / "user.jpg"
    layout = d / "output" / "layout" / "user.jpg"
    page.write_bytes(b"user-page")
    layout.write_bytes(b"user-layout")
    code, out = engine(write_cfg(d), d)
    check("D 退出码0", code == 0)
    check("D 保留用户pages", page.read_bytes() == b"user-page")
    check("D 保留用户layout", layout.read_bytes() == b"user-layout")

    # 旧配置没有 [输出设置] 也使用隔离工作区。
    d = setup("E")
    cfg_path = write_cfg(d)
    cfg_path.write_text(cfg_path.read_text(encoding="utf-8").split("[输出设置]")[0], encoding="utf-8")
    code, out = engine(cfg_path, d)
    st = state(d)
    check("E 旧配置退出码0", code == 0)
    check("E 旧配置仅成品", st["pdf"] and not st["pages"] and not st["layout"])

    shutil.rmtree(WORK, ignore_errors=True)
    bad = [n for n, ok in RESULTS if not ok]
    print("\n" + "=" * 72)
    print(f"结果: {len(RESULTS) - len(bad)}/{len(RESULTS)} 通过")
    if bad:
        print("失败项:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
