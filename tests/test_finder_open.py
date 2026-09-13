"""Finder 打开入口的自动命名回归测试。"""

import tempfile
import unittest
from pathlib import Path

from core import suggested_output_name
from core.finder_open import _build_job_config


class FinderOpenTests(unittest.TestCase):
    def test_output_name_uses_suffix_and_cannot_equal_input(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            source = folder / "9月欧基里德错题集.pdf"
            source.write_bytes(b"%PDF-1.4")
            config, output = _build_job_config(folder / "saved.ini", source)
            self.assertEqual(suggested_output_name(source), "9月欧基里德错题集-题本.pdf")
            self.assertEqual(config["路径设置"]["pdf文件名"], "9月欧基里德错题集-题本.pdf")
            self.assertEqual(output.resolve(), (folder / "9月欧基里德错题集-题本.pdf").resolve())
            self.assertNotEqual(output, source)

    def test_existing_suffix_is_appended_again_to_avoid_collision(self):
        source = Path("数学-题本.pdf")
        self.assertEqual(suggested_output_name(source), "数学-题本-题本.pdf")


if __name__ == "__main__":
    unittest.main()
