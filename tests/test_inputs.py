"""Run with .venv/bin/python -m unittest discover -s tests -p 'test_inputs.py'."""
import configparser
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

import pymupdf
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import pdf_engine as engine


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.cards = self.base / '题目 cards'
        self.cards.mkdir()
        self.out = self.base / '成品 output'
        self.cfg = configparser.ConfigParser(interpolation=None)
        self.cfg.read_dict({
            '步骤控制': {'执行_pdf转图片': 'false', '执行_排版页面': 'true', '执行_合并pdf': 'true'},
            '路径设置': {'输入类型': 'folder', '输入文件夹': str(self.cards), '输出文件夹': str(self.out), 'pdf文件名': '练习.pdf'},
            '排版参数': {'页面宽度_mm': '210', '页面高度_mm': '297', 'dpi': '72', '每页题目数': '2', '间距_mm': '3'},
            'PDF参数': {'pdf_质量': '95'},
            '输出设置': {'只生成pdf文件': 'true'},
        })

    def run_engine(self):
        config = self.base / 'config.ini'
        with config.open('w') as f:
            self.cfg.write(f)
        with contextlib.redirect_stdout(io.StringIO()) as logs:
            result = engine.engine_main(config)
        return result, logs.getvalue()

    def test_folder_formats_natural_order_and_page_count(self):
        names = ['10.PNG', '2.jpg', '1.webp', '11.bmp', '12.tiff', '13.JPEG']
        for name, color in zip(names, ['blue', 'green', 'red', 'yellow', 'purple', 'cyan']):
            Image.new('RGB', (200, 50), color).save(self.cards / name)
        (self.cards / 'notes.txt').write_text('ignored')
        (self.cards / 'nested').mkdir()
        Image.new('RGB', (10, 10)).save(self.cards / 'nested' / '0.png')
        originals = {p.name: p.read_bytes() for p in self.cards.iterdir() if p.is_file()}
        self.assertEqual([p.name for p in engine.collect_image_files(self.cards)], ['1.webp', '2.jpg', '10.PNG', '11.bmp', '12.tiff', '13.JPEG'])
        ok, log = self.run_engine()
        self.assertTrue(ok, log)
        with pymupdf.open(self.out / '练习.pdf') as doc:
            self.assertEqual(len(doc), 3)
            self.assertAlmostEqual(doc[0].rect.width, engine.mm_to_pt(210), places=3)
            pix = doc[0].get_pixmap()
            r, g, b = pix.pixel(100, 30)
            self.assertGreater(r, 200)  # first card is red, not lexicographic 10.png
            self.assertLess(g, 30)
            self.assertLess(b, 30)
        self.assertEqual([p.name for p in self.out.iterdir()], ['练习.pdf'])
        self.assertEqual(originals, {p.name: p.read_bytes() for p in self.cards.iterdir() if p.is_file()})

    def test_pdf_pages_override_old_step_switch(self):
        source = self.base / '题目.pdf'
        with pymupdf.open() as doc:
            for color in [(1, 0, 0), (0, 1, 0), (0, 0, 1)]:
                page = doc.new_page(width=200, height=50)
                page.draw_rect(page.rect, color=color, fill=color)
            doc.save(source)
        original = source.read_bytes()
        self.cfg['路径设置']['输入类型'] = 'pdf'
        self.cfg['路径设置']['输入pdf文件'] = str(source)
        ok, log = self.run_engine()
        self.assertTrue(ok, log)
        with pymupdf.open(self.out / '练习.pdf') as doc:
            self.assertEqual(len(doc), 2)
            self.assertGreater(doc[0].get_pixmap().pixel(100, 30)[0], 240)
            self.assertGreater(doc[1].get_pixmap().pixel(100, 30)[2], 240)
        self.assertEqual(original, source.read_bytes())

    def test_alpha_is_white_and_exif_is_respected(self):
        Image.new('RGBA', (80, 20), (0, 0, 0, 0)).save(self.cards / '1.png')
        card = Image.new('RGB', (20, 80), 'red')
        exif = card.getexif()
        exif[274] = 6
        card.save(self.cards / '2.jpg', exif=exif)
        self.cfg['输出设置']['只生成pdf文件'] = 'false'
        ok, log = self.run_engine()
        self.assertTrue(ok, log)
        with Image.open(self.out / 'layout' / 'page-001.jpg') as page:
            self.assertTrue(all(c > 245 for c in page.getpixel((100, 30))))
            # Rotated to landscape: red covers almost full width near top of second band.
            r, g, b = page.getpixel((30, 440))
            self.assertGreater(r, 220)
            self.assertLess(g, 30)

    def test_empty_and_corrupt_inputs_fail(self):
        self.assertFalse(self.run_engine()[0])
        (self.cards / 'broken.png').write_bytes(b'invalid image')
        self.assertFalse(self.run_engine()[0])
        self.assertFalse((self.out / '练习.pdf').exists())
        source = self.base / 'bad.pdf'
        source.write_bytes(b'not a pdf')
        self.cfg['路径设置'].update({'输入类型': 'pdf', '输入pdf文件': str(source)})
        self.assertFalse(self.run_engine()[0])

    def test_input_layout_collision_preserves_images(self):
        self.cards = self.out / 'layout'
        self.cards.mkdir(parents=True)
        source = self.cards / 'page-001.jpg'
        Image.new('RGB', (50, 50), 'red').save(source)
        original = source.read_bytes()
        self.cfg['路径设置']['输入文件夹'] = str(self.cards)
        self.assertFalse(self.run_engine()[0])
        self.assertEqual(source.read_bytes(), original)

    def test_pdf_output_cannot_overwrite_source(self):
        source = self.base / 'input.pdf'
        with pymupdf.open() as doc:
            doc.new_page()
            doc.save(source)
        original = source.read_bytes()
        self.cfg['路径设置'].update({'输入类型': 'pdf', '输入pdf文件': str(source), '输出文件夹': str(self.base), 'pdf文件名': 'input.pdf'})
        self.assertFalse(self.run_engine()[0])
        self.assertEqual(source.read_bytes(), original)

    def test_failed_merge_preserves_previous_result(self):
        self.out.mkdir()
        target = self.out / '练习.pdf'
        target.write_bytes(b'previous result')
        (self.cards / 'bad.jpg').write_bytes(b'bad')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(engine.step_merge_to_pdf(self.cfg, self.cards, self.out))
        self.assertEqual(target.read_bytes(), b'previous result')
        self.assertEqual(list(self.out.iterdir()), [target])

    def test_pdf_does_not_delete_images_in_output_root(self):
        self.out.mkdir()
        image = self.out / 'original.jpg'
        Image.new('RGB', (50, 50), 'blue').save(image)
        original = image.read_bytes()
        source = self.base / 'input.pdf'
        with pymupdf.open() as doc:
            doc.new_page()
            doc.save(source)
        self.cfg['路径设置'].update({'输入类型': 'pdf', '输入pdf文件': str(source)})
        self.assertTrue(self.run_engine()[0])
        self.assertEqual(image.read_bytes(), original)

    def test_legacy_input_type_inference(self):
        del self.cfg['路径设置']['输入类型']
        self.assertEqual(engine.resolve_input_type(self.cfg), 'folder')
        self.cfg['步骤控制']['执行_pdf转图片'] = 'true'
        self.assertEqual(engine.resolve_input_type(self.cfg), 'pdf')


if __name__ == '__main__':
    unittest.main()
