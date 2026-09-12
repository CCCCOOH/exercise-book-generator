#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
core/pdf_engine.py —— 做题本 PDF 生成引擎（纯 Python，无系统工具依赖）
===============================================================

输入：卡片PDF（每页一道题）或 图片卡片文件夹
流程：
  步骤1(可选): 输入PDF的每一页 → 一张JPG（一张卡片=一道题）  [PyMuPDF 渲染]
  步骤2: 排版 —— 每张纸按“每页题目数”等分成 N 个横条，
        题目在各自格内缩放适配、顶部对齐（下方留白供书写）      [Pillow]
  步骤3: 把排版好的页面合并为最终PDF（物理尺寸 = 所选纸张）     [PyMuPDF]
  步骤4(可选): 「只生成pdf文件」模式下删除 pages/ 与 layout/ 中间文件夹

需要：pip install pymupdf pillow
用法：
  python core/pdf_engine.py                 # 使用脚本同目录的 config.ini
  python core/pdf_engine.py --config 路径    # 使用指定配置文件
"""

import sys
import shutil
import configparser
import re
import tempfile
import os
from pathlib import Path

# ============================================================
# 小工具
# ============================================================

def _import_pymupdf():
    """导入 PyMuPDF（兼容旧包名 fitz）"""
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
            return pymupdf
        except ImportError:
            print("❌ 缺少 PyMuPDF，请先安装：pip install pymupdf")
            return None

def _import_pil():
    """导入 Pillow"""
    try:
        from PIL import Image
        return Image
    except ImportError:
        print("❌ 缺少 Pillow，请先安装：pip install pillow")
        return None

def get_config(config_path):
    """读取配置文件；缺失时打印错误并返回 None"""
    config_file = Path(config_path)
    if not config_file.exists():
        print(f"❌ 错误: 配置文件不存在: {config_file}")
        return None
    config = configparser.ConfigParser(interpolation=None)
    config.read(config_file, encoding='utf-8')
    return config

def get_bool(config, section, key, default=False):
    try:
        return config.getboolean(section, key)
    except Exception:
        return default

def get_int(config, section, key, default=0):
    try:
        return config.getint(section, key)
    except Exception:
        return default

def get_str(config, section, key, default=""):
    try:
        return config.get(section, key)
    except Exception:
        return default

IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff',
}

def _natural_sort_key(path):
    """让 1.jpg、2.jpg、10.jpg 按数字顺序排列"""
    parts = re.split(r'(\d+)', path.name.casefold())
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in parts
    )

def collect_image_files(folder):
    """按自然文件名顺序取出文件夹下所有支持的图片。"""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    files = [
        path for path in folder.iterdir()
        if path.is_file() and path.suffix.casefold() in IMAGE_EXTENSIONS
    ]
    return sorted(files, key=_natural_sort_key)

def normalize_input_type(value):
    """把配置/界面里的输入类型统一为 pdf 或 folder。"""
    value = str(value or '').strip().casefold()
    if value in {'pdf', 'pdf文件', 'pdf文件（每页=一张卡片）', 'file'}:
        return 'pdf'
    if value in {'folder', 'dir', 'directory', 'images', 'image_folder',
                 '文件夹', '图片文件夹'}:
        return 'folder'
    return ''

def resolve_input_type(config):
    """读取输入类型；旧配置没有该项时，按原PDF转图片开关推断。"""
    input_type = normalize_input_type(
        get_str(config, '路径设置', '输入类型', '')
    )
    if input_type:
        return input_type
    return 'pdf' if get_bool(config, '步骤控制', '执行_pdf转图片', False) else 'folder'

def mm_to_px(mm, dpi):
    return int(round(mm * dpi / 25.4))

def mm_to_pt(mm):
    return mm * 72.0 / 25.4

def human_size(size):
    return f"{size/1024:.2f} KB" if size < 1024 * 1024 else f"{size/1024/1024:.2f} MB"


# ============================================================
# 可选封面
# ============================================================

def _cover_font(size, bold=False):
    """取系统中的中日韩字体；找不到时仍可生成英文封面。"""
    from PIL import ImageFont

    candidates = (
        ("/System/Library/Fonts/PingFang.ttc", 2 if bold else 0),
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", 6 if bold else 0),
        ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 0),
        ("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc", 0),
    )
    for path, index in candidates:
        try:
            return ImageFont.truetype(path, size=size, index=index)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_cover_text(draw, text, font, max_width):
    """按实际字形宽度换行，中文与英文都能自然排版。"""
    lines = []
    for paragraph in str(text or "").splitlines() or [""]:
        line = ""
        for char in paragraph:
            candidate = line + char
            if line and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
                lines.append(line)
                line = char
            else:
                line = candidate
        lines.append(line or " ")
    return lines


def _cover_image_as_rgb(image_path, background="#f4f1eb"):
    """读取用户封面图，不改变原文件，并处理透明背景和照片方向。"""
    from PIL import Image, ImageOps

    with Image.open(image_path) as original:
        oriented = ImageOps.exif_transpose(original)
        rgba = oriented.convert("RGBA")
        result = Image.new("RGB", rgba.size, background)
        result.paste(rgba, mask=rgba.getchannel("A"))
        return result


def _paste_cover_image(canvas, source, box, mode="自动适应"):
    """等比裁切填满封面视觉区。"""
    from PIL import Image

    left, top, right, bottom = box
    bw, bh = right - left, bottom - top
    source_ratio = source.width / max(1, source.height)
    target_ratio = bw / max(1, bh)
    fit = mode in {"完整显示", "fit"} or (mode in {"自动适应", "auto", ""} and abs(source_ratio / target_ratio - 1) > .18)
    scale = min(bw / source.width, bh / source.height) if fit else max(bw / source.width, bh / source.height)
    size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
    fitted = source.resize(size, Image.LANCZOS)
    if fit:
        canvas.paste(fitted, (left + (bw - fitted.width) // 2, top + (bh - fitted.height) // 2))
    else:
        x = (fitted.width - bw) // 2
        y = (fitted.height - bh) // 2
        canvas.paste(fitted.crop((x, y, x + bw, y + bh)), (left, top))


def make_cover_image(config, output_folder):
    """生成一张适配纸张的封面临时图，并返回其路径；未启用时返回 None。"""
    if not get_bool(config, "封面设置", "生成封面", False):
        return None

    Image = _import_pil()
    if Image is None:
        return None
    from PIL import ImageDraw

    width = mm_to_px(get_int(config, "排版参数", "页面宽度_mm", 210),
                     get_int(config, "排版参数", "dpi", 300))
    height = mm_to_px(get_int(config, "排版参数", "页面高度_mm", 297),
                      get_int(config, "排版参数", "dpi", 300))
    title = get_str(config, "封面设置", "标题", "").strip() or "我的做题本"
    description = get_str(config, "封面设置", "描述", "").strip()
    cover_image = get_str(config, "封面设置", "封面图片", "").strip()
    image_mode = get_str(config, "封面设置", "图片适应方式", "自动适应").strip()
    paper_background = "#ffffff" if get_bool(config, "封面设置", "纯白色封面纸", False) else "#f7f6f2"
    quality = get_int(config, "PDF参数", "pdf_质量", 85)

    canvas = Image.new("RGB", (width, height), paper_background)
    draw = ImageDraw.Draw(canvas)
    accent = "#2e7964"
    soft_accent = "#dcebe5"
    margin = max(36, round(width * .09))
    visual_top = margin
    visual_h = round(height * .36)
    visual_box = (margin, visual_top, width - margin, visual_top + visual_h)

    if cover_image:
        source = _cover_image_as_rgb(cover_image, paper_background)
        _paste_cover_image(canvas, source, visual_box, image_mode)
        # 底部浅色渐变，让长标题始终清楚易读。
        for offset in range(round(visual_h * .45)):
            y = visual_box[3] - offset - 1
            alpha = 1 - offset / max(1, visual_h * .45)
            shade = int(247 * alpha + 35 * (1 - alpha))
            draw.line((visual_box[0], y, visual_box[2], y), fill=(shade, shade, shade))
    else:
        draw.rounded_rectangle(visual_box, radius=round(width * .025), fill=soft_accent)
        draw.ellipse((width - margin - round(width * .22), visual_top - round(width * .07),
                      width - margin + round(width * .04), visual_top + round(width * .19)),
                     fill="#b8d8cb")
        draw.rounded_rectangle((margin + round(width * .08), visual_top + round(visual_h * .26),
                                margin + round(width * .54), visual_top + round(visual_h * .52)),
                               radius=round(width * .018), fill="#f7f6f2")

    line_y = visual_box[3] + round(height * .085)
    draw.rectangle((margin, line_y, margin + round(width * .13), line_y + max(5, round(width * .009))), fill=accent)
    title_y = line_y + round(height * .045)
    footer_font = _cover_font(max(15, round(width * .025)))
    footer = "SYNC题本神器  ·  专注练习，自由书写"
    footer_box = draw.textbbox((0, 0), footer, font=footer_font)
    available_height = height - margin - (footer_box[3] - footer_box[1]) - title_y
    title_size = max(26, round(width * .085))
    description_size = max(16, round(width * .036))
    max_text_width = width - 2 * margin
    # 短标题保持醒目；长标题/描述自动缩小到适合封面正文区。
    while True:
        title_font = _cover_font(title_size, bold=True)
        description_font = _cover_font(description_size)
        title_lines = _wrap_cover_text(draw, title, title_font, max_text_width)
        description_lines = _wrap_cover_text(draw, description, description_font, max_text_width) if description else []
        text_height = (len(title_lines) * round(title_font.size * 1.22) +
                       (round(height * .035) if description_lines else 0) +
                       len(description_lines) * round(description_font.size * 1.55))
        if text_height <= available_height or (title_size <= 26 and description_size <= 16):
            break
        if title_size > 26:
            title_size -= 2
        elif description_size > 16:
            description_size -= 1

    for line in title_lines:
        draw.text((margin, title_y), line, font=title_font, fill="#202522")
        title_y += round(title_font.size * 1.22)

    if description_lines:
        title_y += round(height * .018)
        line_height = round(description_font.size * 1.55)
        available_lines = max(1, (height - margin - (footer_box[3] - footer_box[1]) - title_y) // line_height)
        visible_lines = description_lines[:available_lines]
        if len(visible_lines) < len(description_lines):
            visible_lines[-1] = visible_lines[-1].rstrip() + "…"
        for line in visible_lines:
            draw.text((margin, title_y), line, font=description_font, fill="#5b625e")
            title_y += line_height

    draw.text((margin, height - margin - (footer_box[3] - footer_box[1])), footer,
              font=footer_font, fill=accent)

    temporary = tempfile.NamedTemporaryFile(suffix=".jpg", dir=output_folder, delete=False)
    temporary.close()
    path = Path(temporary.name)
    try:
        canvas.save(path, "JPEG", quality=quality, dpi=(get_int(config, "排版参数", "dpi", 300),) * 2)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def validate_cover_settings(config, output_folder):
    """验证可选封面设置，避免生成期间覆盖用户封面图。"""
    if not get_bool(config, "封面设置", "生成封面", False):
        return True
    title = get_str(config, "封面设置", "标题", "").strip()
    description = get_str(config, "封面设置", "描述", "").strip()
    image = get_str(config, "封面设置", "封面图片", "").strip()
    if not title or len(title) > 64 or len(description) > 240:
        print("❌ 封面标题不能为空且不超过 64 个字符；描述不超过 240 个字符")
        return False
    if not image:
        return True
    path = Path(image)
    if not path.is_file() or path.suffix.casefold() not in IMAGE_EXTENSIONS:
        print("❌ 封面图片不存在或格式不支持（支持 JPG、PNG、WebP、BMP、TIFF）")
        return False
    for protected_dir in (Path(output_folder) / "pages", Path(output_folder) / "layout"):
        if _is_inside(path, protected_dir):
            print("❌ 封面图片位于输出 pages/layout 中，请选择其他图片以保护原文件")
            return False
    try:
        _cover_image_as_rgb(path)
    except Exception as exc:
        print(f"❌ 无法读取封面图片: {exc}")
        return False
    return True

# ============================================================
# 步骤1: PDF → 每页卡片图
# ============================================================

def step_pdf_to_pages(config, pdf_file, output_dir):
    """把输入PDF的每一页渲染成一张JPG卡片"""
    print("\n" + "=" * 60)
    print("步骤1: 从PDF提取页面为图片（每页一张卡片）")
    print("=" * 60)

    pdf_path = Path(pdf_file) if pdf_file else None
    if pdf_path is None or not pdf_path.exists():
        print(f"❌ 找不到输入PDF文件: {pdf_file or '(未配置)'}")
        print("   请在 config.ini 的 [路径设置] 中设置 输入pdf文件，例如: ./input/卡片.pdf")
        return False

    import_pymupdf = _import_pymupdf()
    Image = _import_pil()
    if import_pymupdf is None or Image is None:
        return False

    dpi = get_int(config, '排版参数', 'dpi', 300)
    pages_dir = Path(output_dir) / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for old in pages_dir.glob("*.jpg"):
        old.unlink()

    print(f"PDF: {pdf_path}")
    print(f"渲染 DPI: {dpi}")
    print(f"输出目录: {pages_dir}")

    try:
        doc = import_pymupdf.open(str(pdf_path))
    except Exception as e:
        print(f"❌ 无法打开PDF: {e}")
        return False

    n_pages = len(doc)
    if n_pages == 0 or doc.needs_pass:
        print("❌ PDF没有页面或受密码保护，请先解锁 PDF")
        doc.close()
        return False

    try:
        for i, page in enumerate(doc, start=1):
            pm = page.get_pixmap(dpi=dpi, alpha=False)
            img = Image.frombytes('RGB', (pm.width, pm.height), pm.samples)
            img.save(str(pages_dir / f"page-{i:03d}.jpg"), 'JPEG',
                     quality=95, dpi=(dpi, dpi))
    except Exception as e:
        print(f"❌ 渲染页面失败: {e}")
        return False
    finally:
        doc.close()

    print(f"✅ 共 {n_pages} 页 → page-001.jpg ~ page-{n_pages:03d}.jpg")
    return True


# ============================================================
# 步骤2: 排版（每张纸 N 题，格内顶部对齐）
# ============================================================

def step_layout_pages(config, src_folder, output_dir):
    print("\n" + "=" * 60)
    print("步骤2: 排版页面（单列等分，题目顶部对齐、下方留白书写）")
    print("=" * 60)

    Image = _import_pil()
    if Image is None:
        return False

    page_w_mm = get_int(config, '排版参数', '页面宽度_mm', 210)
    page_h_mm = get_int(config, '排版参数', '页面高度_mm', 297)
    dpi = get_int(config, '排版参数', 'dpi', 300)
    n_per_page = get_int(config, '排版参数', '每页题目数', 2)
    margin_mm = get_int(config, '排版参数', '间距_mm', 3)
    page_quality = get_int(config, 'PDF参数', 'pdf_质量', 85)

    layout_dir = Path(output_dir) / "layout"
    if _is_inside(src_folder, layout_dir):
        print("❌ 图片来源位于排版输出目录 layout 内，请选择其他输出文件夹以保护原图")
        return False
    cards = collect_image_files(src_folder)
    if not cards:
        print(f"❌ 没有找到卡片图片: {src_folder}")
        return False
    if n_per_page < 1:
        print(f"❌ 每页题目数必须 ≥ 1，当前: {n_per_page}")
        return False

    W = mm_to_px(page_w_mm, dpi)
    H = mm_to_px(page_h_mm, dpi)
    G = mm_to_px(margin_mm, dpi)
    inner_w = W - 2 * G
    if inner_w <= 0 or H <= 2 * G:
        print("❌ 页面尺寸或留白设置不合理（内容区为空）")
        return False

    layout_dir.mkdir(parents=True, exist_ok=True)
    for old in layout_dir.glob("*.jpg"):
        old.unlink()

    n_pages = (len(cards) + n_per_page - 1) // n_per_page
    print(f"卡片数: {len(cards)}，每张 {n_per_page} 题 → 共 {n_pages} 张")
    print(f"纸张: {page_w_mm}×{page_h_mm}mm @ {dpi}dpi → {W}×{H}px，留白 {margin_mm}mm")

    groups = [cards[i:i + n_per_page] for i in range(0, len(cards), n_per_page)]

    for pi, group in enumerate(groups, start=1):
        k = len(group)
        band_h = (H - (k + 1) * G) // k
        if band_h <= 0:
            print(f"❌ 第{pi}张题目数过多，横条高度≤0，请调大纸张或减小每页题目数")
            return False

        canvas = Image.new('RGB', (W, H), 'white')
        for r, card_path in enumerate(group):
            try:
                from PIL import ImageOps
                with Image.open(card_path) as original:
                    # Each file is one card, including multi-frame TIFF/WebP.
                    oriented = ImageOps.exif_transpose(original)
                    rgba = oriented.convert('RGBA')
                    card = Image.new('RGB', rgba.size, 'white')
                    card.paste(rgba, mask=rgba.getchannel('A'))
            except Exception as e:
                print(f"  ❌ 无法读取 {card_path.name}: {e}")
                return False
            w0, h0 = card.size
            if w0 <= 0 or h0 <= 0:
                print(f"  ❌ 图片尺寸异常: {card_path.name}")
                return False
            scale = min(inner_w / w0, band_h / h0)
            nw = max(1, int(round(w0 * scale)))
            nh = max(1, int(round(h0 * scale)))
            if (nw, nh) != (w0, h0):
                card = card.resize((nw, nh), Image.LANCZOS)
            x = G + (inner_w - nw) // 2          # 水平居中
            y = G + r * (band_h + G)             # 格内顶部对齐（下方留白书写）
            canvas.paste(card, (x, y))

        out_page = layout_dir / f"page-{pi:03d}.jpg"
        try:
            canvas.save(str(out_page), 'JPEG', quality=page_quality, dpi=(dpi, dpi))
        except Exception as e:
            print(f"  ❌ 保存第{pi}张失败: {e}")
            return False
        print(f"  ✅ 第{pi}张：{k}题", flush=True)

    print(f"✅ 页面排版完成，输出到: {layout_dir}")
    return True


# ============================================================
# 步骤3: 合并为 PDF（物理尺寸=所选纸张）
# ============================================================

def step_merge_to_pdf(config, input_folder, output_folder):
    print("\n" + "=" * 60)
    print("步骤3: 合并为PDF")
    print("=" * 60)

    import_pymupdf = _import_pymupdf()
    if import_pymupdf is None:
        return False

    page_w_mm = get_int(config, '排版参数', '页面宽度_mm', 210)
    page_h_mm = get_int(config, '排版参数', '页面高度_mm', 297)
    pdf_name = get_str(config, '路径设置', 'pdf文件名', 'output.pdf')
    pdf_file = Path(output_folder) / pdf_name

    jpg_files = collect_image_files(input_folder)
    if not jpg_files:
        print("❌ 没有找到JPG文件")
        return False

    pt_w = mm_to_pt(page_w_mm)
    pt_h = mm_to_pt(page_h_mm)
    cover_path = None
    try:
        cover_path = make_cover_image(config, output_folder)
    except Exception as exc:
        print(f"❌ 生成封面失败: {exc}")
        return False

    page_count = len(jpg_files) + (1 if cover_path else 0)
    print(f"找到 {len(jpg_files)} 张题目页面图" + ("，另加 1 张封面" if cover_path else ""))
    print(f"纸张: {page_w_mm}×{page_h_mm}mm → PDF页 {pt_w:.1f}×{pt_h:.1f}pt")
    print(f"输出: {pdf_file}")

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', dir=output_folder, delete=False) as tmp:
            temporary = Path(tmp.name)
        with import_pymupdf.open() as doc:
            if cover_path:
                cover = doc.new_page(width=pt_w, height=pt_h)
                cover.insert_image(cover.rect, filename=str(cover_path))
            for f in jpg_files:
                page = doc.new_page(width=pt_w, height=pt_h)
                page.insert_image(page.rect, filename=str(f))
            doc.save(str(temporary), garbage=3, deflate=True)
        os.replace(temporary, pdf_file)
    except Exception as e:
        print(f"❌ 生成PDF失败: {e}")
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if cover_path is not None:
            cover_path.unlink(missing_ok=True)

    size = pdf_file.stat().st_size
    print(f"✅ PDF生成成功! 大小: {human_size(size)}, 页数: {page_count}")
    return True


# ============================================================
# 步骤4(可选): 只生成PDF —— 清理 pages/ 与 layout/ 中间文件夹
# ============================================================

def dir_size(folder):
    """统计文件夹内所有文件的总字节数（用于显示释放的空间）"""
    total = 0
    for p in Path(folder).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def _is_inside(path, folder):
    """path 是否就是 folder 本身，或位于 folder 之内"""
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except ValueError:
        return False


def _same_path(a, b):
    """两个路径是否指向同一位置"""
    return Path(a).resolve() == Path(b).resolve()


def _protect_reason(target, protected_paths):
    """target 若会波及用户自己的输入（源文件夹/输入PDF），返回原因；否则 None"""
    for p in protected_paths:
        if p is None:
            continue
        if _is_inside(p, target) or (Path(p).is_dir() and _is_inside(target, p)):
            return f"其中包含用户输入 {p}"
    return None


def step_cleanup_intermediate(output_folder, protected_paths=()):
    """删除输出目录下的 pages/ 与 layout/ 中间文件夹，只保留最终PDF。

    protected_paths 中的路径（用户提供的输入文件夹 / 输入PDF）若位于待删除
    目录之内，则跳过该目录，避免误删用户自己的文件。"""
    print("\n" + "=" * 60)
    print("步骤4: 清理中间文件（只保留最终PDF）")
    print("=" * 60)

    targets = [Path(output_folder) / "pages", Path(output_folder) / "layout"]
    freed = 0
    failed = 0
    skipped = 0

    for target in targets:
        if not target.exists():
            print(f"  ⏭  跳过（不存在）: {target}")
            continue
        reason = _protect_reason(target, protected_paths)
        if reason:
            print(f"  ⚠️  跳过（{reason}）: {target}")
            skipped += 1
            continue
        size = dir_size(target)
        try:
            shutil.rmtree(target)
        except Exception as e:
            failed += 1
            print(f"  ❌ 删除失败 {target}: {e}")
            continue
        freed += size
        print(f"  🗑  已删除: {target}（释放 {human_size(size)}）")

    if failed:
        print(f"⚠️  有 {failed} 个中间文件夹未能删除，请手动清理")
        return False
    print(f"✅ 中间文件已清理，共释放 {human_size(freed)}" +
          (f"；已保留 {skipped} 个涉及用户输入的目录" if skipped else ""))
    return True


# ============================================================
# 主流程
# ============================================================

def engine_main(config_path):
    """按 config_path 指向的 config.ini 执行完整流程"""
    try:  # 被GUI以子进程方式运行时逐行输出日志
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    print("=" * 60)
    print("📄 做题本生成工具")
    print("=" * 60)
    print("输入: 卡片PDF(每页一题) 或 图片卡片文件夹")
    print("输出: PDF做题本，纸张与每页N题见 config.ini")
    print("=" * 60)

    config = get_config(config_path)
    if config is None:
        return False

    input_folder = get_str(config, '路径设置', '输入文件夹', './images')
    output_folder = get_str(config, '路径设置', '输出文件夹', './output')
    input_type = resolve_input_type(config)
    pdf_file = get_str(config, '路径设置', '输入pdf文件', '')
    only_pdf = get_bool(config, '输出设置', '只生成pdf文件', False)

    pdf_name = get_str(config, '路径设置', 'pdf文件名', 'output.pdf').strip()
    if not output_folder.strip() or not pdf_name or any(c in pdf_name for c in '/\\:*?"<>|') or pdf_name in {'.', '..'}:
        print("❌ 输出文件夹与 PDF 文件名不能为空，文件名不能包含路径或特殊字符")
        return False
    if not pdf_name.lower().endswith('.pdf'):
        pdf_name += '.pdf'
    config.set('路径设置', 'pdf文件名', pdf_name)
    if input_type == 'pdf' and pdf_file and _same_path(Path(output_folder) / pdf_name, pdf_file):
        print("❌ 输出 PDF 与输入 PDF 路径相同，请修改输出文件名")
        return False
    dpi = get_int(config, '排版参数', 'dpi', 300)
    quality = get_int(config, 'PDF参数', 'pdf_质量', 85)
    w = get_int(config, '排版参数', '页面宽度_mm', 210)
    h = get_int(config, '排版参数', '页面高度_mm', 297)
    gap = get_int(config, '排版参数', '间距_mm', 3)
    n = get_int(config, '排版参数', '每页题目数', 2)
    if not (36 <= dpi <= 600 and 1 <= quality <= 100 and n >= 1 and gap >= 0 and w > 2 * gap and h > (n + 1) * gap):
        print("❌ 排版参数无效，请检查纸张、每页题目数、间距、DPI（36–600）与质量（1–100）")
        return False
    if not validate_cover_settings(config, output_folder):
        return False

    Path(output_folder).mkdir(parents=True, exist_ok=True)
    print(f"📁 输出文件夹: {output_folder}")
    if input_type == 'pdf':
        print(f"📥 输入形式: PDF 文件（每页=一张卡片）: {pdf_file or '(未配置)'}")
    else:
        print(f"📥 输入形式: 图片文件夹: {input_folder}")
    if only_pdf:
        print("🗑  只生成PDF: 是（合并完成后删除 pages/ 与 layout/ 中间文件夹）")
    if get_bool(config, "封面设置", "生成封面", False):
        print(f"📕 封面: {get_str(config, '封面设置', '标题', '').strip()}")
    print("-" * 60)

    src_folder = input_folder
    if input_type == 'pdf':
        if not step_pdf_to_pages(config, pdf_file, output_folder):
            print("\n❌ 步骤失败: 执行_pdf转图片")
            return False
        src_folder = str(Path(output_folder) / "pages")
    else:
        print(f"📁 直接使用图片文件夹: {src_folder}")
    print("-" * 60)

    if get_bool(config, '步骤控制', '执行_排版页面', True):
        if not step_layout_pages(config, src_folder, output_folder):
            print("\n❌ 步骤失败: 执行_排版页面")
            return False
    else:
        print("\n⏭️  跳过: 执行_排版页面")

    layout_dir = str(Path(output_folder) / "layout")
    merged = False
    if get_bool(config, '步骤控制', '执行_合并pdf', True):
        if not step_merge_to_pdf(config, layout_dir, output_folder):
            print("\n❌ 步骤失败: 执行_合并pdf")
            return False
        merged = True
    else:
        print("\n⏭️  跳过: 执行_合并pdf")

    # 只有真正拿到最终PDF后才清理中间文件，避免把生成失败的中间结果删掉
    if only_pdf:
        if not merged:
            print("\n⚠️  已勾选「只生成pdf文件」，但「执行_合并pdf」未执行，跳过清理中间文件")
        else:
            if input_type == 'pdf':
                protected = [Path(pdf_file)] if pdf_file else []
            else:
                protected = [Path(input_folder)]
            cover_image = get_str(config, "封面设置", "封面图片", "").strip()
            if cover_image:
                protected.append(Path(cover_image))
            step_cleanup_intermediate(output_folder, protected)

    print("\n" + "=" * 60)
    print("🎉 所有步骤完成！")
    pdf_name = get_str(config, '路径设置', 'pdf文件名', 'output.pdf')
    print(f"📄 PDF文件: {Path(output_folder) / pdf_name}")
    if only_pdf and merged:
        print("🗑  只生成PDF模式：清理结果见上方记录，涉及用户输入的目录会保留")
    print("=" * 60)
    return True


def main():
    """命令行入口：python core/pdf_engine.py [--config 配置文件]"""
    args = sys.argv[1:]
    config_path = None
    if '--config' in args:
        i = args.index('--config')
        if i + 1 < len(args):
            config_path = args[i + 1]
    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent / "config.ini")
    ok = engine_main(config_path)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
