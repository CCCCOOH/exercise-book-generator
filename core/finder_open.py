"""macOS Finder 打开方式的无窗口生成入口。"""
import configparser
import tempfile
from pathlib import Path

from .pdf_engine import engine_main


def _build_job_config(saved_config_path, source_pdf):
    config = configparser.ConfigParser(interpolation=None)
    saved_config_path = Path(saved_config_path)
    if saved_config_path.is_file():
        config.read(saved_config_path, encoding="utf-8")
    for section, values in {
        "步骤控制": {"执行_pdf转图片": "true", "执行_排版页面": "true", "执行_合并pdf": "true"},
        "路径设置": {},
    }.items():
        if not config.has_section(section):
            config.add_section(section)
        for key, value in values.items():
            config.set(section, key, value)
    source_pdf = Path(source_pdf).expanduser().resolve()
    config.set("路径设置", "输入类型", "pdf")
    config.set("路径设置", "输入pdf文件", str(source_pdf))
    config.set("路径设置", "输出文件夹", str(source_pdf.parent))
    config.set("路径设置", "pdf文件名", f"题本-{source_pdf.name}")
    return config, source_pdf.parent / f"题本-{source_pdf.name}"


def run_opened_pdfs(pdf_paths, saved_config_path):
    outputs = []
    config_dir = Path(saved_config_path).expanduser().parent
    config_dir.mkdir(parents=True, exist_ok=True)
    for raw_path in pdf_paths:
        source = Path(raw_path).expanduser()
        if not source.is_file() or source.suffix.casefold() != ".pdf":
            return False, outputs
        config, output = _build_job_config(saved_config_path, source)
        temporary = tempfile.NamedTemporaryFile(mode="w", suffix=".ini", prefix="finder-job-", dir=config_dir, encoding="utf-8", delete=False)
        temporary_path = Path(temporary.name)
        try:
            with temporary:
                config.write(temporary)
            if not engine_main(temporary_path):
                return False, outputs
            outputs.append(output)
        finally:
            temporary_path.unlink(missing_ok=True)
    return True, outputs
