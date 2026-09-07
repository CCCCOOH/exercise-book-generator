#!/bin/bash
# ============================================================
# 做题本 PDF 生成工具 —— macOS 双击启动器
# 自动挑选一个“Tk 可用”的 Python 来运行 pdf_maker_gui.py
# ============================================================
cd "$(dirname "$0")" || exit 1

CANDIDATES=(
  "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
  "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
  "/opt/homebrew/bin/python3.13"
  "/opt/homebrew/bin/python3.12"
  "python3"
)

PY=""
for p in "${CANDIDATES[@]}"; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c "import tkinter" >/dev/null 2>&1; then
    PY="$p"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "❌ 找不到带 tkinter 的 Python。"
  echo ""
  echo "   解决办法（任选其一）："
  echo "     1) 安装 python.org 官方版 Python 3.13："
  echo "        https://www.python.org/downloads/macos/"
  echo "     2) Homebrew 用户执行：brew install python-tk@3.13"
  echo ""
  read -n 1 -s -r -p "按任意键退出…"
  exit 1
fi

echo "使用 Python：$PY"
exec "$PY" "pdf_maker_gui.py"
