#!/bin/bash
# ============================================================
# 做题本 PDF 生成工具 —— 一键重新打包 macOS 版 dist
# ============================================================
# 双击本文件即可运行；也可在终端执行：
#
#   ./build_mac.command                 # 找Python → 建独立打包环境 → 图标 → spec → 临时打包 → 双来源自检 → 更新 dist
#   ./build_mac.command --no-verify     # 打包后跳过自检
#   ./build_mac.command --no-open       # 结束后不自动打开 Finder
#   ./build_mac.command --python /path/to/python3   # 指定基础 Python（须带 tkinter）
#   ./build_mac.command --rebuild-venv  # 强制重建打包环境 .venv-build
#   ./build_mac.command --system-python # 直接用当前 Python 打包（不建 .venv-build，不推荐）
#   ./build_mac.command --no-install    # 缺少依赖时不自动安装，直接报错
#   ./build_mac.command --help
#
# 产物：dist/SYNC题本神器.app
#   dist/ 里的其它文件（如 ReadMe_macOS.txt）不会被删除。
#
# 应用图标：自动把根目录的 icon.png 转成 macOS 的 icon.icns（缺 icon.png 时跳过，
#   已有且比 icon.png 新的 icon.icns 会被复用，不会重复转换）。
#
# 为什么要独立打包环境（.venv-build）：
#   1) 必须用“带 tkinter 的 Python”打包（推荐 python.org 官方版 3.13），
#      否则打出来的 .app 打不开窗口（Tcl/Tk 不会被一起打包）；
#   2) 系统里通常装了 matplotlib / pandas / PyQt6 / PySide6 等一大堆包，
#      直接打包会把它们一起塞进 App（体积暴涨），甚至因同时存在 PyQt6 与
#      PySide6 直接报错中止。独立环境只装 PyInstaller + PyMuPDF + Pillow。
# ============================================================

set -uo pipefail
cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"

APP_NAME="SYNC题本神器"
SPEC="$ROOT/$APP_NAME.spec"
DIST="$ROOT/dist"
APP="$DIST/$APP_NAME.app"
BIN="$APP/Contents/MacOS/$APP_NAME"
BUILD_VENV="$ROOT/.venv-build"
PNG="$ROOT/icon.png"
ICNS="$ROOT/icon.icns"

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

[ "$(uname -s)" = "Darwin" ] || die "此脚本用于 macOS，请在 Mac 上运行。"

printf '\033[1m📦 做题本 PDF 生成工具 —— 重新打包 macOS 版\033[0m\n'
echo   "   项目目录：$ROOT"

# ============================================================
# 1/7 找一个“带 tkinter”的 Python
# ============================================================
step "1/7 查找带 tkinter 的 Python"

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
    "$BASE_PY" -c "import sys, tkinter; assert sys.version_info >= (3, 13)" >/dev/null 2>&1 \
      || die "需要 Python 3.13 或更高版本，且必须带 tkinter：$BASE_PY"
    PY="$BASE_PY"
  else
    die "指定的 Python 不存在：$BASE_PY"
  fi
else
  for p in "${CANDIDATES[@]}"; do
    if command -v "$p" >/dev/null 2>&1 && "$p" -c "import sys, tkinter; assert sys.version_info >= (3, 13)" >/dev/null 2>&1; then
      PY="$p"
      break
    fi
  done
fi

if [ -z "$PY" ]; then
  err "找不到带 tkinter 的 Python 3.13+，无法打包。"
  echo "   请任选其一后重试："
  echo "     1) 安装 python.org 官方版 Python 3.13：https://www.python.org/downloads/macos/"
  echo "     2) Homebrew 用户：brew install python-tk@3.13"
  echo "     3) 手动指定：./build_mac.command --python /path/to/python3"
  pause; exit 1
fi
ok "基础 Python：${PY}（$("$PY" -c 'import sys; print(sys.version.split()[0])')，tkinter 可用）"

# ============================================================
# 2/7 准备独立的打包环境（只装 PyInstaller + PyMuPDF + Pillow）
# ============================================================
step "2/7 准备打包环境"

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
      warn "基础 Python 已变化（$venv_base → ${base_prefix}），重建打包环境"
    rm -rf "$BUILD_VENV" || die "无法重建打包环境"
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
    if "$BUILD_PY" -m pip install --disable-pip-version-check --no-cache-dir \
         --retries 5 --timeout 60 pyinstaller pymupdf pillow; then
      installed=1
      break
    fi
  done
  [ "$installed" = 1 ] || die "依赖安装失败（需要联网访问 PyPI）。可手动执行：
     $BUILD_PY -m pip install pyinstaller pymupdf pillow"
  for mod in PyInstaller pymupdf PIL; do
    "$BUILD_PY" -c "import $mod" >/dev/null 2>&1 || die "安装后仍无法导入 ${mod}，请检查上面的 pip 输出。"
  done
fi
ok "依赖齐备（PyInstaller $("$BUILD_PY" -c 'import PyInstaller; print(PyInstaller.__version__)')、PyMuPDF $("$BUILD_PY" -c 'import pymupdf; print(pymupdf.__version__)')）"

# ============================================================
# 3/7 应用图标：icon.png → icon.icns
# ============================================================
step "3/7 准备应用图标（icon.png → icon.icns）"

if [ -f "$PNG" ]; then
  if [ -f "$ICNS" ] && [ "$ICNS" -nt "$PNG" ]; then
    ok "复用已有图标：icon.icns（比 icon.png 更新，无需重转）"
  elif command -v iconutil >/dev/null 2>&1 && command -v sips >/dev/null 2>&1; then
    ICONSET_TMP="$(mktemp -d)/icon.iconset"
    mkdir -p "$ICONSET_TMP"
    all_ok=1
    while read -r name size; do
      [ -n "$name" ] || continue
      if ! sips -z "$size" "$size" "$PNG" --out "$ICONSET_TMP/$name" >/dev/null 2>&1; then
        all_ok=0; break
      fi
    done <<'ICONLIST'
icon_16x16.png 16
icon_16x16@2x.png 32
icon_32x32.png 32
icon_32x32@2x.png 64
icon_128x128.png 128
icon_128x128@2x.png 256
icon_256x256.png 256
icon_256x256@2x.png 512
icon_512x512.png 512
icon_512x512@2x.png 1024
ICONLIST
    if [ "$all_ok" = 1 ]; then
      iconutil -c icns "$ICONSET_TMP" -o "$ICNS" || die "图标转换失败（iconutil 报错）"
      ok "已生成应用图标：icon.icns"
    else
      warn "sips 缩放图标失败，跳过图标（App 将使用默认图标）"
    fi
    rm -rf "$(dirname "$ICONSET_TMP")"
  else
    warn "缺少 iconutil / sips，无法生成 .icns（App 将使用默认图标）"
  fi
elif [ -f "$ICNS" ]; then
  ok "未找到 icon.png，沿用现有 icon.icns"
else
  warn "未找到 icon.png / icon.icns，App 将使用默认图标"
fi

# ============================================================
# 4/7 准备 .spec（缺失时自动生成，内容与仓库一致）
# ============================================================
step "4/7 准备打包配置 $APP_NAME.spec"

if [ -f "$ICNS" ]; then
  ICON_SPEC="'icon.icns'"
else
  ICON_SPEC="None"
fi

if [ -f "$SPEC" ]; then
  "$BUILD_PY" - "$SPEC" <<'MIGRATE_SPEC'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text(encoding='utf-8')
if 'pdf_maker_app.py' in text:
    path.write_text(text.replace('pdf_maker_app.py', 'pdf_maker_gui.py'), encoding='utf-8')
MIGRATE_SPEC
  [ "$?" = 0 ] || die "无法更新打包入口"
  ok "使用已有 spec：$SPEC"
else
  warn "spec 不存在（.gitignore 忽略了 *.spec），自动生成一份"
  cat > "$SPEC" <<SPEC_EOF
# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['pdf_maker_gui.py'],
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
    name='$APP_NAME',
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
    name='$APP_NAME',
)
app = BUNDLE(
    coll,
    name='$APP_NAME.app',
    icon=$ICON_SPEC,
    bundle_identifier='com.sy.zuotibenpdf',
    info_plist={'CFBundleDisplayName': '$APP_NAME', 'CFBundleName': '$APP_NAME'},
)
SPEC_EOF
  ok "已生成：$SPEC"
fi

# ============================================================
# 5/7 临时目录打包：打包/自检失败时保留 dist 旧版
# ============================================================
step "5/7 开始打包（约 1~3 分钟，请耐心等待）"
mkdir -p "$DIST" "$ROOT/build" || die "无法创建输出目录"
STAGE="$(mktemp -d "$ROOT/build/package.XXXXXX")" || die "无法创建临时打包目录"
LOG="$ROOT/build/packaging.log"
PUBLISHING=0
PUBLISHED=0
cleanup_build() {
  # 发布中途失败时恢复旧应用；成功后删除临时产物及旧版备份。
  if [ "$PUBLISHING" = 1 ] && [ "$PUBLISHED" = 0 ]; then
    for item in "$APP_NAME" "$APP_NAME.app"; do
      if [ -f "$STAGE/installed-$item" ]; then
        rm -rf "$DIST/$item"
      fi
      if [ -e "$STAGE/previous/$item" ]; then
        mv "$STAGE/previous/$item" "$DIST/$item" || {
          err "恢复旧版失败，备份保留在：$STAGE/previous"
          return
        }
      fi
    done
  fi
  rm -rf "$STAGE"
}
trap cleanup_build EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

export PYINSTALLER_CONFIG_DIR="$ROOT/.pyinstaller"
mkdir -p "$PYINSTALLER_CONFIG_DIR" || die "无法创建打包缓存目录"
if ! "$BUILD_PY" -m PyInstaller --noconfirm --clean \
      --distpath "$STAGE/dist" --workpath "$STAGE/work" "$SPEC" 2>&1 | tee "$LOG"; then
  die "打包失败，旧版应用保持不变。日志：$LOG"
fi

APP="$STAGE/dist/$APP_NAME.app"
BIN="$APP/Contents/MacOS/$APP_NAME"
[ -x "$BIN" ] || die "打包结束但没有找到可执行文件：$BIN"
codesign --verify --deep "$APP" || die "应用签名校验失败，旧版应用保持不变。"
ok "打包与签名校验完成（$(du -sh "$APP" | cut -f1)）"

if ! "$BUILD_PY" - "$APP" <<'TK_CHECK'
import sys
from pathlib import Path
app = Path(sys.argv[1])
assert any(app.rglob('_tkinter*.so')), '缺少 tkinter 扩展，请使用带 Tk 的 Python 重新打包'
assert any(app.rglob('tk.tcl')), '缺少 Tk 运行库'
assert any(app.rglob('init.tcl')), '缺少 Tcl 运行库'
TK_CHECK
then
  die "图形界面运行库不完整，旧版应用保持不变。"
fi
ok "Tcl/Tk 运行库已打入应用"

# ============================================================
# 6/7 用冻结后的应用验证两种来源与可选封面
# ============================================================
if [ "$DO_VERIFY" = 1 ]; then
  step "6/7 自检：PDF、图片文件夹与可选封面 → 成品 PDF"
  if ! "$BUILD_PY" - "$BIN" <<'VERIFY_BUNDLE'
import configparser
import subprocess
import sys
import tempfile
from pathlib import Path
import pymupdf
from PIL import Image

binary = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix='zuotiben_verify_') as tmp:
    root = Path(tmp)
    source = root / '题目卡片.pdf'
    images = root / '题目图片 100%'
    images.mkdir()
    with pymupdf.open() as doc:
        for i in range(3):
            page = doc.new_page(width=400, height=100)
            page.insert_text((30, 50), f'Question {i + 1}', fontsize=20)
        doc.save(source)
    for name, color in [('1.png', 'red'), ('2.jpg', 'green'), ('10.webp', 'blue')]:
        Image.new('RGB', (400, 100), color).save(images / name)
    cover = root / '封面图.png'
    Image.new('RGB', (400, 200), 'red').save(cover)
    originals = {p: p.read_bytes() for p in [source, cover, *images.iterdir()]}
    for kind in ('pdf', 'folder'):
        output = root / f'output_{kind}'
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read_dict({
            '步骤控制': {'执行_pdf转图片': str(kind == 'pdf'), '执行_排版页面': 'true', '执行_合并pdf': 'true'},
            '路径设置': {'输入类型': kind, '输入pdf文件': str(source), '输入文件夹': str(images),
                         '输出文件夹': str(output), 'pdf文件名': '做题本.pdf'},
            '排版参数': {'页面宽度_mm': '210', '页面高度_mm': '297', 'dpi': '72', '每页题目数': '2', '间距_mm': '3'},
            'PDF参数': {'pdf_质量': '90'},
            '输出设置': {'只生成pdf文件': 'true'},
            '封面设置': {
                '生成封面': str(kind == 'folder'),
                '标题': '自检练习册',
                '描述': '封面应成为 PDF 第一页',
                '封面图片': str(cover) if kind == 'folder' else '',
            },
        })
        config_path = root / f'{kind}.ini'
        with config_path.open('w', encoding='utf-8') as f:
            cfg.write(f)
        subprocess.run([binary, '--cli', '--config', str(config_path)], cwd=root, check=True, timeout=120)
        result = output / '做题本.pdf'
        with pymupdf.open(result) as doc:
            expected_pages = 3 if kind == 'folder' else 2
            assert len(doc) == expected_pages, f'{kind}: 应生成 {expected_pages} 页'
            assert abs(doc[0].rect.width - 210 * 72 / 25.4) < 0.1, '纸张宽度错误'
            assert abs(doc[0].rect.height - 297 * 72 / 25.4) < 0.1, '纸张高度错误'
        assert list(output.iterdir()) == [result], f'{kind}: 中间文件未清理'
        assert all(p.read_bytes() == data for p, data in originals.items()), '原始题目文件发生变化'
        print(f'✅ {kind}: 3 张题目卡片 → {expected_pages} 页 A4 PDF，原文件完整，中间文件已清理', flush=True)
VERIFY_BUNDLE
  then
    die "成品自检失败，旧版应用保持不变。"
  fi
else
  step "6/7 已跳过成品自检（--no-verify）"
fi

# ============================================================
# 7/7 自检完成后发布，保留 dist 内的其它文件
# ============================================================
step "7/7 更新 dist"
if pgrep -f "$DIST/$APP_NAME.app/Contents/MacOS/$APP_NAME" >/dev/null 2>&1; then
  die "旧版应用仍在运行，请退出后重新打包。旧应用尚未替换。"
fi
mkdir -p "$STAGE/previous" || die "无法创建旧版备份目录"
PUBLISHING=1
for item in "$APP_NAME" "$APP_NAME.app"; do
  if [ -e "$DIST/$item" ]; then
    mv "$DIST/$item" "$STAGE/previous/$item" || die "无法备份旧版：$item"
  fi
  touch "$STAGE/installed-$item" || die "无法记录发布状态"
  mv "$STAGE/dist/$item" "$DIST/$item" || die "无法发布新版：${item}（退出时将恢复旧版）"
done
PUBLISHED=1
APP="$DIST/$APP_NAME.app"
ok "全部完成：$APP"
echo "   大小：$(du -sh "$APP" | cut -f1)"
echo "   打包日志：$LOG"
echo "   当前 Mac 架构：$(uname -m)"
echo "   双击 dist 中的 $APP_NAME.app 即可启动新版。"
if [ "$DO_OPEN" = 1 ]; then
  open "$DIST" || warn "无法自动打开 Finder，请手动打开 dist 文件夹。"
fi
pause
