## SYNC 做题本生成器

根据pdf_maker.py一键生成做题本以供打印刷题。**输出纸张可在界面预设中选择**（A4、B5、A5、B4、
A3、A6、Letter、Legal，默认A4=210×297mm），每张纸可配 N 道题（`[排版参数] 每页题目数`，默认2），
题目按**单列 N 行等分、缩放适配、格内顶部对齐**（题目贴格子上沿，下方留白供书写）。
最后一张纸题目不足 N 道时，自动按剩余数量均匀排布填满。

### 步骤（PDF 直接当输入）
1. 用 marginnote 框选错题并导出卡片（分享 → 保存本地）得到一个 PDF，每一页就是一道题
2. 把 PDF 放到项目 `input/` 目录下
3. 运行工具：GUI 里点「选择PDF…」选中它（命令行则在 `config.ini` 把 `输入pdf文件` 指向该 PDF）
4. 工具自动：每页转成一张图片 → 排版成所选纸张（每页N题、顶部对齐）→ 合并成一个 PDF
5. 结果输出到 `output/output.pdf`

> 兼容旧用法：把 `config.ini` 的 `执行_pdf转图片 = false`，并直接把卡片 JPG 放进
> `输入文件夹`（默认 `./images/`），排版与合并步骤照常可用。

> 引擎为**纯 Python**（PyMuPDF + Pillow），从 v0.2 起不再依赖 ImageMagick / Ghostscript。

### 关键配置（config.ini）
```ini
[步骤控制]
执行_pdf转图片 = true    # PDF→页面图片（false 则直接读 输入文件夹 的JPG）
执行_排版页面  = true
执行_合并pdf    = true

[排版参数]
页面宽度_mm = 210        # A4 宽（GUI 用纸张预设直接改）
页面高度_mm = 297        # A4 高
dpi         = 300
每页题目数   = 2          # ← 每张纸几道题（界面里直接改）
间距_mm     = 3          # 题与题、页面四周留白
```

开发运行环境：
- Python ≥3.13；依赖 `pymupdf`、`pillow`（`uv sync` 或 `pip install pymupdf pillow`）
- GUI 需要 Tk 可用的 Python（python.org 官方版自带；uv 自带 Python 不含 Tcl/Tk）

## 图形界面（GUI）

`pdf_maker_gui.py` 是 `pdf_maker.py` 的 tkinter 图形界面封装（纯标准库）：

- 界面内选择输入PDF文件（每页=一张卡片）与输出文件夹、勾选执行步骤；纸张大小用**标准预设下拉**
  （A4 / B5 / A5 / B4 / A3 / A6 / Letter / Legal）选择，配「每张纸题目数」即可，无需手填毫米/DPI
- 点「开始生成」自动把界面参数写回 `config.ini`，再后台运行引擎并实时显示日志，可随时「停止」
- 命令行用法（`uv run pdf_maker.py`）不受影响，两边参数同步；DPI/题间距/PDF压缩质量等高级项
  保留在 config.ini 默认值中，可按需直接编辑微调

**开发态启动**：直接双击项目里的 `start_gui.command`（推荐），或在终端运行：

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 pdf_maker_gui.py
```

注意：GUI 需要 Tk 可用的 Python —— python.org 官方版自带；brew 用户可先执行
`brew install python-tk@3.13` 再用 `/opt/homebrew/bin/python3.13 pdf_maker_gui.py`。

## 打包发布（Windows / macOS）

引擎已改为纯 Python，打包产物自带全部依赖，**目标电脑无需安装任何系统工具**。

- **macOS 版（已构建）**：`dist/ZuotiBenPdfTool_macOS.zip`（内含 `ZuotiBenPdfTool.app`
  与应用说明）。Apple Silicon 直接解压双击即可；首次打开如提示不明开发者，
  右键→打开 或 系统设置→隐私与安全性→仍要打开。首次运行后在
  `~/Library/Application Support/ZuotiBenPdfTool/config.ini` 生成配置文件。
- **重新打包 macOS**：`bash packaging/build_mac.sh`（本机为 Apple Silicon，输出即 arm64 版；
  Intel 版请在 Intel Mac 上执行同一脚本）。
- **Windows 版（预留）**：PyInstaller 不能跨平台交叉编译，`.exe` 需在 Windows 上生成 ——
  把源码拷到 Windows，双击 `packaging/build_windows.bat`，产出 `dist\ZuotiBenPdfTool.exe`。
- 统一打包入口：`pdf_maker_app.py`（GUI 模式 / `--cli` 引擎模式，供打包后自调用）。
