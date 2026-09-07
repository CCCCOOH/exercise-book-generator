#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PDF制作工具 - 从JPG到PDF的一站式处理
读取 config.ini 配置文件，按步骤执行
"""

import os
import sys
import subprocess
import configparser
from pathlib import Path
from multiprocessing import Pool

# ============================================================
# 工具函数
# ============================================================

def find_imagemagick_command():
    """自动检测可用的 ImageMagick 命令"""
    candidates = ["magick", "convert"]
    for cmd in candidates:
        try:
            subprocess.run([cmd, "--version"], capture_output=True, check=True)
            return cmd
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return None

def get_config():
    """读取配置文件"""
    config_file = Path(__file__).parent / "config.ini"
    if not config_file.exists():
        print(f"❌ 错误: 配置文件不存在: {config_file}")
        print("请确保 config.ini 与脚本在同一目录")
        sys.exit(1)
    
    config = configparser.ConfigParser()
    config.read(config_file, encoding='utf-8')
    return config

def get_bool(config, section, key, default=False):
    """安全获取布尔值"""
    try:
        return config.getboolean(section, key)
    except:
        return default

def get_int(config, section, key, default=0):
    """安全获取整数"""
    try:
        return config.getint(section, key)
    except:
        return default

def get_str(config, section, key, default=""):
    """安全获取字符串"""
    try:
        return config.get(section, key)
    except:
        return default

# ============================================================
# 步骤函数
# ============================================================

def step_generate_background(magick_cmd, config, output_dir):
    """步骤1: 生成白色背景图"""
    print("\n" + "=" * 60)
    print("步骤1: 生成背景图")
    print("=" * 60)
    
    width_mm = get_int(config, '背景图参数', '宽度_mm', 210)
    height_mm = get_int(config, '背景图参数', '高度_mm', 297)
    dpi = get_int(config, '背景图参数', 'DPI', 300)
    bg_name = get_str(config, '路径设置', '背景图文件名', '背景.png')
    bg_file = Path(output_dir) / bg_name
    
    width_px = int(width_mm * dpi * 10 / 254)
    height_px = int(height_mm * dpi * 10 / 254)
    
    print(f"尺寸: {width_mm}mm × {height_mm}mm → {width_px} × {height_px} 像素")
    print(f"DPI: {dpi}")
    print(f"输出: {bg_file}")
    
    cmd = [
        magick_cmd,
        "-size", f"{width_px}x{height_px}",
        "xc:#FFFFFF",
        "-density", str(dpi),
        "-units", "PixelsPerInch",
        str(bg_file)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ 背景图已生成")
            return True
        else:
            print(f"❌ 生成失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

def add_background_single(args):
    """单张图片加背景（用于多进程）"""
    filename, output_folder, bg_file, magick_cmd, offset_x, offset_y = args
    file_name = Path(filename).name
    output_path = Path(output_folder) / file_name
    
    if not os.path.exists(bg_file) or not os.path.exists(filename):
        return False
    
    Path(output_folder).mkdir(parents=True, exist_ok=True)
    
    cmd = [
        magick_cmd, "composite",
        "-geometry", f"+{offset_x}+{offset_y}",
        "-gravity", "north",
        filename, bg_file, str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  ✅ {file_name}")
            return True
        else:
            print(f"  ❌ {file_name}")
            return False
    except Exception as e:
        print(f"  ❌ {file_name}: {e}")
        return False

def step_add_background(magick_cmd, config, input_folder, output_folder):
    """步骤2: 给所有JPG添加背景"""
    print("\n" + "=" * 60)
    print("步骤2: 给JPG添加背景")
    print("=" * 60)
    
    bg_name = get_str(config, '路径设置', '背景图文件名', '背景.png')
    bg_file = Path(output_folder) / bg_name
    
    if not bg_file.exists():
        print(f"❌ 背景图不存在: {bg_file}")
        return False
    
    offset_x = get_int(config, '添加背景参数', '偏移_X', 0)
    offset_y = get_int(config, '添加背景参数', '偏移_Y', 0)
    
    # 获取JPG文件
    jpg_files = []
    for ext in ['.jpg', '.jpeg', '.JPG', '.JPEG']:
        jpg_files.extend(Path(input_folder).glob(f'*{ext}'))
    jpg_files.sort(key=lambda x: x.name)
    
    if not jpg_files:
        print("❌ 没有找到JPG文件")
        return False
    
    print(f"找到 {len(jpg_files)} 张图片")
    print(f"偏移量: X={offset_x}, Y={offset_y}")
    print("开始处理...")
    
    Path(output_folder).mkdir(parents=True, exist_ok=True)
    
    args_list = [(str(f), output_folder, str(bg_file), magick_cmd, offset_x, offset_y) 
                 for f in jpg_files]
    
    with Pool(processes=8) as pool:
        results = pool.map(add_background_single, args_list)
    
    success_count = sum(results)
    print(f"✅ 成功处理 {success_count}/{len(jpg_files)} 张图片")
    return success_count > 0

def step_merge_pairs(magick_cmd, config, input_folder, output_folder):
    """步骤3: 两两拼接（可选）"""
    print("\n" + "=" * 60)
    print("步骤3: 两两拼接图片")
    print("=" * 60)
    
    delete_original = get_bool(config, '拼接参数', '拼接_删除原始', False)
    
    # 获取JPG文件并排序
    jpg_files = []
    for ext in ['.jpg', '.jpeg', '.JPG', '.JPEG']:
        jpg_files.extend(Path(input_folder).glob(f'*{ext}'))
    jpg_files.sort(key=lambda x: x.name)
    
    if len(jpg_files) < 2:
        print("⚠️  图片少于2张，跳过拼接")
        return input_folder
    
    merged_folder = Path(output_folder) / "merged"
    merged_folder.mkdir(parents=True, exist_ok=True)
    
    pair_count = len(jpg_files) // 2
    print(f"共 {len(jpg_files)} 张图片，配成 {pair_count} 对")
    
    for i in range(pair_count):
        img1 = jpg_files[i * 2]
        img2 = jpg_files[i * 2 + 1]
        output_path = merged_folder / f"merged_{i+1:03d}.jpg"
        
        print(f"  拼接: {img1.name} + {img2.name}")
        
        cmd = [magick_cmd, str(img1), str(img2), "-append", str(output_path)]
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            if delete_original:
                img1.unlink()
                img2.unlink()
        except Exception as e:
            print(f"  ❌ 拼接失败: {e}")
            return None
    
    # 处理剩余单张图片
    if len(jpg_files) % 2 == 1:
        last_img = jpg_files[-1]
        output_path = merged_folder / f"single_{last_img.name}"
        print(f"  单张: {last_img.name}")
        try:
            cmd = [magick_cmd, str(last_img), "-gravity", "north", 
                   "-extent", f"%wx%[fx:h*2]", str(output_path)]
            subprocess.run(cmd, capture_output=True, check=True)
            if delete_original:
                last_img.unlink()
        except Exception as e:
            print(f"  ❌ 处理失败: {e}")
            return None
    
    print(f"✅ 拼接完成，输出到: {merged_folder}")
    return str(merged_folder)

def step_set_dpi(magick_cmd, config, input_folder):
    """步骤4: 设置所有JPG的DPI"""
    print("\n" + "=" * 60)
    print("步骤4: 设置DPI")
    print("=" * 60)
    
    dpi = get_int(config, 'DPI设置参数', 'DPI_设置值', 300)
    
    jpg_files = []
    for ext in ['.jpg', '.jpeg', '.JPG', '.JPEG']:
        jpg_files.extend(Path(input_folder).glob(f'*{ext}'))
    jpg_files.sort(key=lambda x: x.name)
    
    if not jpg_files:
        print("❌ 没有找到JPG文件")
        return False
    
    print(f"设置 DPI = {dpi}，共 {len(jpg_files)} 张图片")
    
    for f in jpg_files:
        cmd = [magick_cmd, str(f), "-density", str(dpi), "-units", "PixelsPerInch", str(f)]
        try:
            subprocess.run(cmd, capture_output=True, check=True)
        except Exception as e:
            print(f"  ❌ {f.name}: {e}")
            return False
    
    print(f"✅ 所有图片DPI已设置为 {dpi}")
    return True

def step_merge_to_pdf(magick_cmd, config, input_folder, output_folder):
    """步骤5: 合并为PDF"""
    print("\n" + "=" * 60)
    print("步骤5: 合并为PDF")
    print("=" * 60)
    
    quality = get_int(config, 'PDF参数', 'PDF_质量', 80)
    pdf_name = get_str(config, '路径设置', 'PDF文件名', 'output.pdf')
    pdf_file = Path(output_folder) / pdf_name
    
    jpg_files = []
    for ext in ['.jpg', '.jpeg', '.JPG', '.JPEG']:
        jpg_files.extend(Path(input_folder).glob(f'*{ext}'))
    jpg_files.sort(key=lambda x: x.name)
    
    if not jpg_files:
        print("❌ 没有找到JPG文件")
        return False
    
    print(f"找到 {len(jpg_files)} 张图片")
    print(f"压缩质量: {quality}")
    print(f"输出: {pdf_file}")
    
    # 构建命令
    if magick_cmd == "magick":
        cmd = [magick_cmd, "convert"]
    else:
        cmd = [magick_cmd]
    
    for f in jpg_files:
        cmd.append(str(f))
    cmd.extend(["-compress", "jpeg", "-quality", str(quality), str(pdf_file)])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            size = pdf_file.stat().st_size
            if size < 1024 * 1024:
                size_str = f"{size/1024:.2f} KB"
            else:
                size_str = f"{size/1024/1024:.2f} MB"
            print(f"✅ PDF生成成功! 大小: {size_str}, 页数: {len(jpg_files)}")
            return True
        else:
            print(f"❌ 生成失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 60)
    print("📄 PDF制作工具")
    print("=" * 60)
    print("从JPG到PDF的一站式处理")
    print("=" * 60)
    
    # 检查ImageMagick
    magick_cmd = find_imagemagick_command()
    if magick_cmd is None:
        print("❌ 错误: 找不到 ImageMagick 命令")
        print("请安装 ImageMagick:")
        print("  macOS: brew install imagemagick")
        print("  Linux: sudo apt-get install imagemagick")
        print("  Windows: 从 https://imagemagick.org/script/download.php 下载安装")
        sys.exit(1)
    print(f"✅ 使用 ImageMagick 命令: {magick_cmd}")
    
    # 读取配置
    config = get_config()
    
    # 获取路径
    input_folder = get_str(config, '路径设置', '输入文件夹', './images')
    output_folder = get_str(config, '路径设置', '输出文件夹', './output')
    
    # 确保输出目录存在
    Path(output_folder).mkdir(parents=True, exist_ok=True)
    
    print(f"📁 输入文件夹: {input_folder}")
    print(f"📁 输出文件夹: {output_folder}")
    print("-" * 60)
    
    # 执行各步骤
    steps = [
        ('执行_生成背景', step_generate_background, [magick_cmd, config, output_folder]),
        ('执行_添加背景', step_add_background, [magick_cmd, config, input_folder, output_folder]),
        ('执行_两两拼接', step_merge_pairs, [magick_cmd, config, output_folder, output_folder]),
        ('执行_设置DPI', step_set_dpi, [magick_cmd, config, output_folder]),
        ('执行_合并PDF', step_merge_to_pdf, [magick_cmd, config, output_folder, output_folder]),
    ]
    
    current_folder = output_folder
    
    for step_key, step_func, step_args in steps:
        if not get_bool(config, '步骤控制', step_key, False):
            print(f"\n⏭️  跳过: {step_key}")
            continue
        
        # 执行步骤，传入当前文件夹
        if step_key == '执行_添加背景':
            result = step_func(step_args[0], step_args[1], step_args[2], step_args[3])
        elif step_key == '执行_两两拼接':
            result = step_func(step_args[0], step_args[1], step_args[2], step_args[3])
            if result and result != current_folder:
                current_folder = result
        elif step_key == '执行_设置DPI':
            result = step_func(step_args[0], step_args[1], current_folder)
        elif step_key == '执行_合并PDF':
            result = step_func(step_args[0], step_args[1], current_folder, step_args[3])
        else:
            result = step_func(step_args[0], step_args[1], step_args[2])
        
        if not result:
            print(f"\n❌ 步骤失败: {step_key}")
            sys.exit(1)
    
    print("\n" + "=" * 60)
    print("🎉 所有步骤完成！")
    print(f"📁 最终输出: {current_folder}")
    pdf_name = get_str(config, '路径设置', 'PDF文件名', 'output.pdf')
    print(f"📄 PDF文件: {Path(output_folder) / pdf_name}")
    print("=" * 60)

if __name__ == "__main__":
    main()