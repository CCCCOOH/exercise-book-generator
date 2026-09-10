#!/bin/bash
# ============================================================
# 做题本 PDF 生成工具 —— 一键重新打包 macOS 版 dist
# ============================================================
# 双击本文件即可运行；也可在终端执行：
#
#   ./build_mac.command                 # 找Python → 建独立打包环境 → 清理 → 打包 → 自检 → 打开 dist
#   ./build_mac.command --no-verify     # 打包后跳过自检
#   ./build_mac.command --no-open       # 结束后不自动打开 Finder
#   ./build_mac.command --python /path/to/python3   # 指定基础 Python（须带 tkinter）
#   ./build_mac.command --rebuild-venv  # 强制重建打包环境 .venv-build
#   ./build_mac.command --system-python # 直接用当前 Python 打包（不建 .venv-build，不推荐）
#   ./build_mac.command --no-install    # 缺少依赖时不自动安装，直接报错
#   ./build_mac.command --help
#
# 产物：dist/ZuotiBenPdfTool.app
#   dist/ 里的其它文件（如 ReadMe_macOS.txt）不会被删除。
#
# 为什么要独立打包环境（.venv-build）：
#   1) 必须用“带 tkinter 的 Python”打包（推荐 python.org 官方版 3.13），
#      否则打出来的 .app 打不开窗口（Tcl/Tk 不会被一起打包）；
#   2) 系统里通常装了 matplotlib / pandas / PyQt6 / PySide6 等一大堆包，
#      直接打包会把它们一起塞进 App（体积暴涨），甚至因同时存在 PyQt6 与
#      PySide6 直接报错中止。独立环境只装 PyInstaller + PyMuPDF + Pillow。
# ============================================================

set -u
cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"

APP_NAME="ZuotiBenPdfTool"
SPEC="$ROOT/$APP_NAME.spec"
DIST="$ROOT/dist"
APP="$DIST/$APP_NAME.app"
BIN="$APP/Contents/MacOS/$APP_NAME"
BUILD_VENV="$ROOT/.venv-build"

DO_VERIFY=1
DO_OPEN=1
DO_INSTALL=1
USE_SYSTEM_PY=0
REBUILD_VENV=0
BASE_PY="${BUILD_PYTHON:-}"

# ---------- 输出样式 ----------
step() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✅ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠️  %s\033[0m\n' "$*"; }
err()  { printf '\033[1;31m❌ %s\033[0m\n' "$*"; }

# 双击运行时窗口会一闪而过，出错时停住等用户看一眼
pause() {
  if [ -t 0 ]; then
    printf '\n按回车键退出…'
    read -r _ || true
  fi
}
die() { err "$*"; pause; exit 1; }

# ---------- 参数 ----------
while [ $# -gt 0 ]; do
  case "$1" in
    --python)        BASE_PY="${2:-}"; [ -n "$BASE_PY" ] || die "--python 后面要跟解释器路径"; shift 2 ;;
    --rebuild-venv)  REBUILD_VENV=1; shift ;;
    --system-python) USE_SYSTEM_PY=1; shift ;;
    --no-verify)     DO_VERIFY=0; shift ;;
    --no-open)       DO_OPEN=0; shift ;;
    --no-install)    DO_INSTALL=0; shift ;;
    -h|--help)       awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *)               die "未知参数：$1（用 --help 查看用法）" ;;
  esac
done

printf '\033[1m📦 做题本 PDF 生成工具 —— 重新打包 macOS 版\033[0m\n'
echo   "   项目目录：$ROOT"

# ============================================================
# 1/6 找一个“带 tkinter”的 Python
# ============================================================
step "1/6 查找带 tkinter 的 Python"

CANDIDATES=(
  "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
  "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
  "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
  "/opt/homebrew/bin/python3.13"
  "/opt/homebrew/bin/python3.12"
  "python3"
)

PY=""
if [ -n "$BASE_PY" ]; then
  if [ -x "$BASE_PY" ] || command -v "$BASE_PY" >/dev/null 2>&1; then
    "$BASE_PY" -c "import tkinter" >/dev/null 2>&1 \
      || die "指定的 Python 缺少 tkinter，无法打包图形界面：$BASE_PY"
    PY="$BASE_PY"
  else
    die "指定的 Python 不存在：$BASE_PY"
  fi
else
  for p in "${CANDIDATES[@]}"; do
    if command -v "$p" >/dev/null 2>&1 && "$p" -c "import tkinter" >/dev/null 2>&1; then
      PY="$p"
      break
    fi
  done
fi

if [ -z "$PY" ]; then
  err "找不到带 tkinter 的 Python，无法打包。"
  echo "   请任选其一后重试："
  echo "     1) 安装 python.org 官方版 Python 3.13：https://www.python.org/downloads/macos/"
  echo "     2) Homebrew 用户：brew install python-tk@3.13"
  echo "     3) 手动指定：./build_mac.command --python /path/to/python3"
  pause; exit 1
fi
ok "基础 Python：$PY（$("$PY" -c 'import sys; print(sys.version.split()[0])')，tkinter 可用）"

# ============================================================
# 2/6 准备独立的打包环境（只装 PyInstaller + PyMuPDF + Pillow）
# ============================================================
step "2/6 准备打包环境"

if [ "$USE_SYSTEM_PY" = 1 ]; then
  warn "已指定 --system-python：直接用基础 Python 打包，全局包可能被一起打进 App"
  BUILD_PY="$PY"
else
  base_prefix="$("$PY" -c 'import sys; print(sys.prefix)')"
  venv_base=""
  [ -x "$BUILD_VENV/bin/python" ] && venv_base="$(cat "$BUILD_VENV/.base-prefix" 2>/dev/null || true)"

  if [ "$REBUILD_VENV" = 1 ] || [ ! -x "$BUILD_VENV/bin/python" ] || [ "$venv_base" != "$base_prefix" ]; then
    [ "$REBUILD_VENV" = 1 ] && warn "按要求重建打包环境"
    [ -x "$BUILD_VENV/bin/python" ] && [ "$venv_base" != "$base_prefix" ] && \
      warn "基础 Python 已变化（$venv_base → $base_prefix），重建打包环境"
    rm -rf "$BUILD_VENV"
    echo "   正在创建独立环境：$BUILD_VENV"
    "$PY" -m venv "$BUILD_VENV" \
      || die "创建虚拟环境失败（请确认该 Python 自带 venv/ensurepip）"
    printf '%s' "$base_prefix" > "$BUILD_VENV/.base-prefix"
  fi
  BUILD_PY="$BUILD_VENV/bin/python"
  ok "打包环境：$BUILD_VENV"
fi

missing=""
for mod in PyInstaller pymupdf PIL; do
  "$BUILD_PY" -c "import $mod" >/dev/null 2>&1 || missing="$missing $mod"
done

# python.org 版 Python 的 etc/openssl/cert.pem 默认是空的，新建的虚拟环境里
# pip 会因“找不到本地颁发者证书”而装不了包；这里自动挑一个可用的证书包。
find_ca_bundle() {
  local p
  p="$("$PY" -c 'import certifi; print(certifi.where())' 2>/dev/null || true)"
  if [ -n "$p" ] && [ -f "$p" ]; then printf '%s' "$p"; return 0; fi
  for p in /etc/ssl/cert.pem \
           /opt/homebrew/etc/openssl@3/cert.pem \
           /usr/local/etc/openssl@3/cert.pem \
           "$("$PY" -c 'import ssl; print(ssl.get_default_verify_paths().openssl_cafile or "")' 2>/dev/null || true)"; do
    if [ -n "$p" ] && [ -f "$p" ]; then printf '%s' "$p"; return 0; fi
  done
  return 1
}

if [ -n "$missing" ]; then
  warn "打包环境缺少模块：$missing"
  [ "$DO_INSTALL" = 1 ] || die "缺少依赖且指定了 --no-install，请先手动安装。"
  if CA_BUNDLE="$(find_ca_bundle)"; then
    export PIP_CERT="$CA_BUNDLE"
    export SSL_CERT_FILE="$CA_BUNDLE"
    echo "   使用 CA 证书包：$CA_BUNDLE"
  fi
  echo "   正在安装：$BUILD_PY -m pip install pyinstaller pymupdf pillow"
  installed=0
  for attempt in 1 2 3; do
    [ "$attempt" -gt 1 ] && warn "第 $attempt 次尝试安装（网络不稳时会自动重试）…"
    if "$BUILD_PY" -m pip install --disable-pip-version-check \
         --retries 5 --timeout 30 pyinstaller pymupdf pillow; then
      installed=1
      break
    fi
  done
  [ "$installed" = 1 ] || die "依赖安装失败（需要联网访问 PyPI）。可手动执行：
     $BUILD_PY -m pip install pyinstaller pymupdf pillow"
  for mod in PyInstaller pymupdf PIL; do
    "$BUILD_PY" -c "import $mod" >/dev/null 2>&1 || die "安装后仍无法导入 $mod，请检查上面的 pip 输出。"
  done
fi
ok "依赖齐备（PyInstaller $("$BUILD_PY" -c 'import PyInstaller; print(PyInstaller.__version__)')、PyMuPDF $("$BUILD_PY" -c 'import pymupdf; print(pymupdf.__version__)')）"

# ============================================================
# 3/6 准备 .spec（缺失时自动生成，内容与仓库一致）
# ============================================================
step "3/6 准备打包配置 $APP_NAME.spec"

if [ -f "$SPEC" ]; then
  ok "使用已有 spec：$SPEC"
else
  warn "spec 不存在（.gitignore 忽略了 *.spec），自动生成一份"
  cat > "$SPEC" <<'SPEC_EOF'
# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['pdf_maker_app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ZuotiBenPdfTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ZuotiBenPdfTool',
)
app = BUNDLE(
    coll,
    name='ZuotiBenPdfTool.app',
    icon=None,
    bundle_identifier='com.sy.zuotibenpdf',
)
SPEC_EOF
  ok "已生成：$SPEC"
fi

# ============================================================
# 4/6 清理旧产物并打包
# ============================================================
step "4/6 清理旧产物"

if pgrep -f "$APP_NAME.app/Contents/MacOS/$APP_NAME" >/dev/null 2>&1; then
  warn "检测到 $APP_NAME 正在运行，建议先退出该 App（否则可能打包到一半失败）"
fi

rm -rf "$ROOT/build" "$DIST/$APP_NAME" "$APP"
ok "已清理 build/、dist/$APP_NAME、dist/$APP_NAME.app（dist 下其它文件保留）"

step "4/6 开始打包（约 1~3 分钟，请耐心等待）"
mkdir -p "$DIST"

# PyInstaller 默认把缓存放在 ~/Library/Application Support/pyinstaller，
# 这里改到项目内的隐藏目录：不污染全局缓存，--clean 也只清理本项目自己的缓存
export PYINSTALLER_CONFIG_DIR="$ROOT/.pyinstaller"
mkdir -p "$PYINSTALLER_CONFIG_DIR"

if ! "$BUILD_PY" -m PyInstaller --noconfirm --clean \
      --distpath "$DIST" --workpath "$ROOT/build" "$SPEC"; then
  err "打包失败，请查看上面的 PyInstaller 输出。"
  pause; exit 1
fi

[ -x "$BIN" ] || die "打包结束但没有找到可执行文件：$BIN"
ok "打包完成：$APP（$(du -sh "$APP" | cut -f1)）"

# 去掉隔离属性，避免本机打开时被 Gatekeeper 拦下
xattr -cr "$APP" 2>/dev/null || true
if codesign --verify --deep "$APP" 2>/dev/null; then
  ok "签名校验通过"
else
  warn "签名校验未通过（Ad-hoc 签名通常仍可本机双击打开）"
fi

# Tcl/Tk 没被打进去的话 .app 会打不开窗口，这里提前发现
if find "$APP" \( -name "*_tkinter*" -o -name "libtk8.6*" \) -print -quit 2>/dev/null | grep -q .; then
  ok "Tcl/Tk 运行库已随包打入（图形界面可正常启动）"
else
  warn "包内没找到 Tcl/Tk 运行库，.app 可能打不开窗口 —— 请换用 python.org 官方版 Python 重新打包"
fi

# ============================================================
# 5/6 用打包好的 App 跑一遍完整流程（自检）
# ============================================================
if [ "$DO_VERIFY" = 1 ]; then
  step "5/6 自检：用打包后的 App 实际生成一份 PDF"

  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT

  # 造一份 3 页的测试卡片PDF
  if ! "$BUILD_PY" - "$TMP/cards.pdf" <<'PY_EOF'
import sys
import pymupdf

doc = pymupdf.open()
for i in range(1, 4):
    page = doc.new_page(width=400, height=300)
    page.insert_text((40, 60), f"Question {i}", fontsize=20)
    page.insert_text((40, 100), "x^2 + 2x + 1 = 0", fontsize=14)
doc.save(sys.argv[1])
doc.close()
PY_EOF
  then
    die "无法生成测试用 PDF（请检查打包环境里的 pymupdf）"
  fi

  cat > "$TMP/config.ini" <<CFG_EOF
[步骤控制]
执行_pdf转图片 = true
执行_排版页面 = true
执行_合并pdf = true

[路径设置]
输入pdf文件 = $TMP/cards.pdf
输入文件夹 = ./images
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
只生成pdf文件 = true
CFG_EOF

  ( cd "$TMP" && "$BIN" --cli --config "$TMP/config.ini" ) \
    || die "自检失败：App 内置引擎运行出错（详见上方日志）"

  [ -s "$TMP/output/output.pdf" ] || die "自检失败：没有生成 output.pdf"
  if [ -d "$TMP/output/pages" ] || [ -d "$TMP/output/layout" ]; then
    die "自检失败：「只生成pdf文件」模式下 pages/ 或 layout/ 没有被清理"
  fi
  ok "自检通过：3 页卡片 → PDF 生成成功，中间文件夹已自动清理"
else
  step "5/6 已跳过自检（--no-verify）"
fi

# ============================================================
# 6/6 收尾
# ============================================================
step "6/6 完成"
echo "   App  ：$APP"
echo "   大小 ：$(du -sh "$APP" | cut -f1)"
echo "   说明 ：dist 下 ReadMe_macOS.txt 可随包一起发给用户"
echo "   提示 ：首次打开若提示“来自身份不明的开发者”，右键 →「打开」即可"

if [ "$DO_OPEN" = 1 ]; then
  open "$DIST"
fi
ok "全部完成 🎉"
if [ -t 0 ]; then
  printf '\n按回车键关闭窗口…'
  read -r _ || true
fi
