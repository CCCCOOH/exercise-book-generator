#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
tests/test_only_pdf.py —— 「只生成pdf文件」开关的回归测试
========================================================

覆盖 core/pdf_engine.py 的步骤4（清理 pages/ 与 layout/）：

    A. 勾选 + 三步全开        → 输出目录只剩最终PDF
    B. 不勾选（默认）          → pages/ 与 layout/ 保留
    C. 勾选但未执行合并        → 不清理，只告警
    D. 合并失败               → 不清理任何中间结果
    E. 输入文件夹=output/layout → 保护用户输入，不删 layout
    E2. 输入文件夹=派生 pages/  → 属于中间产物，正常清理
    F. 输入PDF位于 pages/ 内    → 保护用户输入，不删 pages
    G. 输出目录已有残留中间文件夹 → 一并清理
    H. 旧配置没有 [输出设置] 段  → 向后兼容，默认不清理

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
    # ---- A: 勾选 + 三步全开 → 只剩 output.pdf ----
    d = setup("A")
    code, out = engine(write_cfg(d, only_pdf="true"), d)
    st = state(d)
    report("A 勾选只生成pdf + 全步骤", code, out, st)
    check("A 退出码0", code == 0)
    check("A PDF存在", st["pdf"])
    check("A pages已删除", not st["pages"])
    check("A layout已删除", not st["layout"])
    check("A 日志含清理提示", "中间文件已清理" in out)

    # ---- B: 不勾选 → 中间文件保留（回归） ----
    d = setup("B")
    code, out = engine(write_cfg(d, only_pdf="false"), d)
    st = state(d)
    report("B 不勾选（默认）", code, out, st)
    check("B 退出码0", code == 0)
    check("B PDF存在", st["pdf"])
    check("B pages保留", st["pages"])
    check("B layout保留", st["layout"])
    check("B 无清理动作", "中间文件已清理" not in out)

    # ---- C: 勾选但关闭合并步骤 → 不清理，仅告警 ----
    d = setup("C")
    code, out = engine(write_cfg(d, only_pdf="true", merge="false"), d)
    st = state(d)
    report("C 勾选但未合并PDF", code, out, st)
    check("C 退出码0", code == 0)
    check("C pages保留", st["pages"])
    check("C layout保留", st["layout"])
    check("C 有告警", "跳过清理中间文件" in out)

    # ---- D: 合并失败 → 不清理任何中间结果 ----
    d = setup("D")
    code, out = engine(write_cfg(d, only_pdf="true", layout="false",
                                 input_folder="./output/layout"), d)
    st = state(d)
    report("D 合并失败（无 layout 可用）", code, out, st)
    check("D 退出码非0", code != 0)
    check("D pages保留（失败不清理）", st["pages"])
    check("D 无清理动作", "中间文件已清理" not in out)

    # ---- E: 输入文件夹就在 output/layout → 保护用户输入 ----
    d = setup("E")
    engine(write_cfg(d, only_pdf="false"), d)      # 先跑一遍得到真实 layout/*.jpg
    code, out = engine(write_cfg(d, only_pdf="true", pdf2img="false", layout="false",
                                 input_folder="./output/layout"), d)
    st = state(d)
    report("E 输入文件夹=./output/layout（保护用户输入）", code, out, st)
    check("E 退出码0", code == 0)
    check("E PDF存在", st["pdf"])
    check("E 用户layout未被删", st["layout"])
    check("E layout内JPG仍在", any((d / "output" / "layout").glob("*.jpg")))
    check("E pages已删除", not st["pages"])
    check("E 有保护告警", "包含用户输入" in out)

    # ---- E2: pdf转图片开启且输入文件夹=派生的 pages/ → 允许清理 ----
    d = setup("E2")
    code, out = engine(write_cfg(d, only_pdf="true", input_folder="./output/pages"), d)
    st = state(d)
    report("E2 输入文件夹=派生的 ./output/pages", code, out, st)
    check("E2 退出码0", code == 0)
    check("E2 PDF存在", st["pdf"])
    check("E2 pages已删除", not st["pages"])
    check("E2 layout已删除", not st["layout"])

    # ---- F: 输入PDF位于 pages/ 内 → 保护用户输入 ----
    d = setup("F")
    (d / "output" / "pages").mkdir(parents=True)
    shutil.copy(d / "input" / "cards.pdf", d / "output" / "pages" / "cards.pdf")
    code, out = engine(write_cfg(d, only_pdf="true",
                                 input_pdf="./output/pages/cards.pdf"), d)
    st = state(d)
    report("F 输入PDF在 pages/ 内（保护用户输入）", code, out, st)
    check("F 退出码0", code == 0)
    check("F PDF存在", st["pdf"])
    check("F pages未被删", st["pages"])
    check("F 输入PDF仍在", (d / "output" / "pages" / "cards.pdf").exists())
    check("F layout已删", not st["layout"])

    # ---- G: 输出目录已有残留中间文件夹 → 一并清理 ----
    d = setup("G")
    (d / "output" / "pages").mkdir(parents=True)
    (d / "output" / "layout").mkdir(parents=True)
    (d / "output" / "pages" / "stale.jpg").write_bytes(b"old")
    (d / "output" / "layout" / "stale.jpg").write_bytes(b"old")
    code, out = engine(write_cfg(d, only_pdf="true"), d)
    st = state(d)
    report("G 覆盖已有残留中间文件夹", code, out, st)
    check("G 退出码0", code == 0)
    check("G PDF存在", st["pdf"])
    check("G 残留pages已删", not st["pages"])
    check("G 残留layout已删", not st["layout"])

    # ---- H: 旧配置没有 [输出设置] 段 → 默认不清理 ----
    d = setup("H")
    cfg_path = write_cfg(d, only_pdf="true")
    cfg_path.write_text(cfg_path.read_text(encoding="utf-8").split("[输出设置]")[0],
                        encoding="utf-8")
    code, out = engine(cfg_path, d)
    st = state(d)
    report("H 旧配置无[输出设置]段", code, out, st)
    check("H 退出码0", code == 0)
    check("H PDF存在", st["pdf"])
    check("H 默认不清理（向后兼容）", st["pages"] and st["layout"])

    shutil.rmtree(WORK, ignore_errors=True)
    bad = [n for n, ok in RESULTS if not ok]
    print("\n" + "=" * 72)
    print(f"结果: {len(RESULTS) - len(bad)}/{len(RESULTS)} 通过")
    if bad:
        print("失败项:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
