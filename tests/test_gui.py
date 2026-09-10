"""GUI state/worker integration tests; run with a Tk-enabled Python."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pdf_maker_gui import PdfMakerGUI, load_config_dict


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.app = PdfMakerGUI(self.root, config_path=self.base / 'config.ini', base_dir=self.base)
        self.root.update_idletasks()

    def test_source_switch_and_configuration_roundtrip(self):
        self.assertEqual(self.app.var_input_type.get(), 'pdf')
        self.assertTrue(self.app._input_rows['pdf'].winfo_ismapped())
        self.app.var_input_type.set('folder')
        self.app._sync_input_rows()
        self.root.update_idletasks()
        self.assertFalse(self.app._input_rows['pdf'].winfo_ismapped())
        self.assertTrue(self.app._input_rows['folder'].winfo_ismapped())
        self.app.save_config(show_msg=False)
        values = load_config_dict(self.base / 'config.ini')
        self.assertEqual(values['路径设置', '输入类型'], 'folder')
        self.assertEqual(values['步骤控制', '执行_pdf转图片'], 'false')
        self.assertEqual(values['步骤控制', '执行_合并pdf'], 'true')
        self.app.var_input_type.set('pdf')
        self.app._sync_input_rows()
        self.assertTrue(self.app._step_vars['执行_pdf转图片'].get())

    def test_controls_unlock_and_preview_validation(self):
        self.app._set_running(True)
        self.app._set_running(False)
        combo = next(w for w in self.app.lock_widgets if isinstance(w, ttk.Combobox))
        self.assertEqual(str(combo['state']), 'readonly')
        self.app.vars['排版参数', '每页题目数'].set('')
        self.assertIn('1–12', self.app.var_summary.get())
        self.app.vars['排版参数', '每页题目数'].set('3')
        self.assertIn('每页 3 题', self.app.var_summary.get())

    def test_small_window_keeps_action_and_log_visible(self):
        self.root.geometry('980x740')
        self.root.update_idletasks()
        for widget in (self.app.btn_start, self.app.log, self.app.preview):
            self.assertTrue(widget.winfo_ismapped())
            bottom = widget.winfo_rooty() - self.root.winfo_rooty() + widget.winfo_height()
            self.assertLessEqual(bottom, self.root.winfo_height(), str(widget))
        self.assertGreaterEqual(self.app.log.winfo_height(), 40)

    def test_folder_validation_and_complete_background_generation(self):
        images = self.base / 'images'
        images.mkdir()
        self.app.var_input_type.set('folder')
        self.app._sync_input_rows()
        with patch('pdf_maker_gui.messagebox.showerror') as error:
            self.assertFalse(self.app._validate())
            error.assert_called_once()
        # BMP fixture written with stdlib only; GUI Python need not have Pillow.
        import struct
        width, height = 20, 20
        pixels = bytes([0, 0, 255]) * width * height
        header = b'BM' + struct.pack('<IHHI', 54 + len(pixels), 0, 0, 54)
        dib = struct.pack('<IiiHHIIiiII', 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
        for i in range(3):
            (images / f'{i}.bmp').write_bytes(header + dib + pixels)
        self.app.vars['排版参数', 'dpi'].set('72')
        self.app.vars['路径设置', 'pdf文件名'].set('中文练习')
        self.app.vars['输出设置', '只生成pdf文件'].set(True)
        self.assertTrue(self.app._validate())
        self.assertEqual(self.app.vars['路径设置', 'pdf文件名'].get(), '中文练习.pdf')
        self.app.start_run()
        deadline = time.monotonic() + 20
        while self.app.running and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.02)
        self.assertFalse(self.app.running)
        self.assertIn('已完成', self.app.var_status.get(), self.app.log.get('1.0', 'end'))
        result = self.base / 'output' / '中文练习.pdf'
        self.assertTrue(result.read_bytes().startswith(b'%PDF'))
        self.assertEqual(list(result.parent.iterdir()), [result])


if __name__ == '__main__':
    unittest.main()
