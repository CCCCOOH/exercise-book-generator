"""做题本 PDF 生成引擎。"""

from pathlib import Path


def suggested_output_name(input_path):
    """根据输入 PDF/文件夹生成不会默认覆盖原 PDF 的成品名。"""
    path = Path(input_path)
    base = path.stem if path.suffix.casefold() == ".pdf" else path.name
    return f"{base}-题本.pdf"
