#!/bin/bash
# 双击：重新打包最新应用，生成 dist/SYNC题本神器.pkg，并打开 dist。
# --skip-app-build  使用 dist 中现有应用（不重新打包）
# --no-open         不自动打开 Finder
# --version 1.0.0   指定安装包版本（默认读取 pyproject.toml）
# --sign "Developer ID Installer: ..."  使用已有安装包签名证书
# --help            查看帮助
set -uo pipefail
cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"
APP_NAME="SYNC题本神器"
APP="$ROOT/dist/$APP_NAME.app"
OUTPUT="$ROOT/dist/$APP_NAME.pkg"
REBUILD=1
DO_OPEN=1
VERSION=""
SIGN_ID=""
STAGE=""
pause() { if [ -t 0 ]; then printf '\n按回车键退出…'; read -r _ || true; fi; }
die() { printf '\n❌ %s\n' "$*"; pause; exit 1; }
step() { printf '\n▶ %s\n' "$*"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-app-build) REBUILD=0; shift ;;
    --no-open) DO_OPEN=0; shift ;;
    --version) VERSION="${2:-}"; [ -n "$VERSION" ] || die "--version 后需要版本号"; shift 2 ;;
    --sign) SIGN_ID="${2:-}"; [ -n "$SIGN_ID" ] || die "--sign 后需要证书名称"; shift 2 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) die "未知参数：$1，请用 --help 查看用法" ;;
  esac
done
[ "$(uname -s)" = "Darwin" ] || die "请在 macOS 上运行此脚本。"
for tool in pkgbuild productbuild pkgutil ditto; do
  command -v "$tool" >/dev/null 2>&1 || die "缺少 macOS 工具：$tool"
done
if [ -z "$VERSION" ]; then
  VERSION="$(sed -n 's/^version = "\([^"]*\)".*/\1/p' "$ROOT/pyproject.toml" | head -n 1)"
fi
[[ "$VERSION" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]] || die "版本号应为 1、1.0 或 1.0.0 这样的数字格式。"

step "1/4 准备应用（安装包版本：${VERSION}）"
if [ "$REBUILD" = 1 ]; then
  [ -f "$ROOT/build_mac.command" ] || die "找不到 build_mac.command"
  # 关闭子脚本的 stdin，避免双击运行时在子脚本末尾多等待一次回车。
  /bin/bash "$ROOT/build_mac.command" --no-open </dev/null || die "应用打包失败，未生成新安装包。"
fi
[ -x "$APP/Contents/MacOS/$APP_NAME" ] || die "找不到可用的应用，请先运行 build_mac.command。"
codesign --verify --deep "$APP" || die "应用签名校验失败，请重新打包应用。"
ARCHS="$(/usr/bin/lipo -archs "$APP/Contents/MacOS/$APP_NAME")" || die "无法读取应用架构"
HOST_ARCHS="${ARCHS// /,}"
case "$HOST_ARCHS" in arm64|x86_64|arm64,x86_64|x86_64,arm64) ;; *) die "不支持的应用架构：$ARCHS" ;; esac

mkdir -p "$ROOT/build" "$ROOT/dist" || die "无法创建输出目录"
STAGE="$(mktemp -d "$ROOT/build/pkg.XXXXXX")" || die "无法创建临时目录"
trap 'rm -rf "$STAGE"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
LOG="$ROOT/build/pkg-packaging.log"
step "2/4 创建应用安装组件"
mkdir -p "$STAGE/payload/Applications" || die "无法创建安装目录"
ditto "$APP" "$STAGE/payload/Applications/$APP_NAME.app" || die "无法复制应用"
pkgbuild --analyze --root "$STAGE/payload" "$STAGE/components.plist" || die "无法分析应用"
# 固定安装到 /Applications，避免安装器把更新重定向到项目 dist 中的副本。
index=0
while /usr/libexec/PlistBuddy -c "Print :$index" "$STAGE/components.plist" >/dev/null 2>&1; do
  /usr/libexec/PlistBuddy -c "Set :$index:BundleIsRelocatable false" "$STAGE/components.plist" || die "无法设置安装位置"
  /usr/libexec/PlistBuddy -c "Set :$index:BundleOverwriteAction upgrade" "$STAGE/components.plist" || die "无法设置更新行为"
  index=$((index + 1))
done
if ! pkgbuild --root "$STAGE/payload" --component-plist "$STAGE/components.plist" \
  --identifier com.sy.zuotibenpdf.pkg --version "$VERSION" --install-location / \
  --ownership recommended "$STAGE/application.pkg" 2>&1 | tee "$LOG"; then
  die "安装组件生成失败。日志：$LOG"
fi
cat > "$STAGE/distribution.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
  <title>SYNC题本神器</title>
  <options customize="never" require-scripts="false" hostArchitectures="$HOST_ARCHS" rootVolumeOnly="true"/>
  <domains enable_localSystem="true" enable_currentUserHome="false" enable_anywhere="false"/>
  <choices-outline><line choice="application"/></choices-outline>
  <choice id="application" visible="false" title="SYNC题本神器">
    <pkg-ref id="com.sy.zuotibenpdf.pkg"/>
  </choice>
  <pkg-ref id="com.sy.zuotibenpdf.pkg" version="$VERSION" onConclusion="none">application.pkg</pkg-ref>
</installer-gui-script>
XML

step "3/4 生成并检查 PKG 安装包"
BUILD_COMMAND=(productbuild --distribution "$STAGE/distribution.xml" --package-path "$STAGE")
if [ -n "$SIGN_ID" ]; then BUILD_COMMAND+=(--sign "$SIGN_ID"); fi
BUILD_COMMAND+=("$STAGE/$APP_NAME.pkg")
if ! "${BUILD_COMMAND[@]}" 2>&1 | tee -a "$LOG"; then
  die "PKG 生成失败，已有安装包保持不变。日志：$LOG"
fi
pkgutil --expand "$STAGE/$APP_NAME.pkg" "$STAGE/expanded" >>"$LOG" 2>&1 || die "安装包结构校验失败"
pkgutil --payload-files "$STAGE/application.pkg" > "$STAGE/payload-files.txt" || die "无法检查安装内容"
if ! /usr/bin/grep -F "Applications/$APP_NAME.app/Contents/MacOS/$APP_NAME" "$STAGE/payload-files.txt" >/dev/null; then
  die "安装包内缺少应用主程序"
fi
/usr/sbin/installer -pkg "$STAGE/$APP_NAME.pkg" -target / -showChoicesXML >>"$LOG" 2>&1 || die "macOS 安装器无法读取此安装包"
if [ -n "$SIGN_ID" ]; then
  pkgutil --check-signature "$STAGE/$APP_NAME.pkg" >>"$LOG" 2>&1 || die "安装包签名校验失败"
fi

step "4/4 保存到 dist"
# 同一文件系统内替换，生成失败时旧 PKG 不受影响。
mv -f "$STAGE/$APP_NAME.pkg" "$OUTPUT" || die "无法保存安装包"
printf '\n✅ 已生成：%s\n   版本：%s\n   架构：%s\n   安装位置：/Applications/%s.app\n   日志：%s\n' "$OUTPUT" "$VERSION" "$ARCHS" "$APP_NAME" "$LOG"
if [ -z "$SIGN_ID" ]; then
  printf '   当前为未签名安装包；面向其他用户分发可使用 --sign 配置安装包签名。\n'
fi
printf '   双击 PKG，按 macOS 安装器提示安装；生成脚本本身不会执行安装。\n'
if [ "$DO_OPEN" = 1 ]; then open "$ROOT/dist" || true; fi
pause
