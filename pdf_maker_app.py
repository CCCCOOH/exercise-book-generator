#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
pdf_maker_app.py —— 打包统一入口
=================================
  pdf_maker_app.py            → 启动图形界面
  pdf_maker_app.py --cli --config 路径   → 无界面运行引擎（供GUI子进程调用，
                             PyInstaller 冻结态下以“自己跑自己”的方式执行引擎）
"""

import sys


def main():
    args = sys.argv[1:]
    if "--cli" in args:
        # ---- 引擎模式（无界面）----
        import pdf_maker
        config_path = None
        if "--config" in args:
            i = args.index("--config")
            if i + 1 < len(args):
                config_path = args[i + 1]
        if config_path is None:
            # 与 GUI 保持一致的默认用户数据目录
            import pdf_maker_gui
            config_path = pdf_maker_gui.user_data_dir() / "config.ini"
        sys.exit(0 if pdf_maker.engine_main(str(config_path)) else 1)

    # ---- 图形界面模式 ----
    import pdf_maker_gui
    pdf_maker_gui.main()


if __name__ == "__main__":
    main()
