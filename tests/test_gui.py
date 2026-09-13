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
from pdf_maker_gui import (PAPER_NAMES, PdfMakerGUI, load_config_dict,
                           load_custom_paper_presets)


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

    def test_drop_pdf_or_folder_selects_the_matching_input(self):
        pdf = self.base / '拖入题目.pdf'
        pdf.write_bytes(b'%PDF-1.4')
        folder = self.base / '拖入图片'
        folder.mkdir()

        self.assertTrue(self.app._handle_drop_paths([str(pdf)]))
        self.assertEqual(self.app.var_input_type.get(), 'pdf')
        self.assertEqual(self.app.vars['路径设置', '输入pdf文件'].get(), str(pdf))
        self.assertEqual(self.app.vars['路径设置', 'pdf文件名'].get(), '拖入题目-题本.pdf')

        self.assertTrue(self.app._handle_drop_paths([str(folder)]))
        self.assertEqual(self.app.var_input_type.get(), 'folder')
        self.assertEqual(self.app.vars['路径设置', '输入文件夹'].get(), str(folder))
        self.assertEqual(self.app.vars['路径设置', 'pdf文件名'].get(), '拖入图片-题本.pdf')

    def test_pdf_picker_initializes_a_non_conflicting_output_name(self):
        pdf = self.base / '模拟卷.PDF'
        pdf.write_bytes(b'%PDF-1.4')
        var = self.app.vars['路径设置', '输入pdf文件']
        with patch('pdf_maker_gui.filedialog.askopenfilename', return_value=str(pdf)):
            self.app._pick_pdf(var)
        self.assertEqual(var.get(), str(pdf))
        self.assertEqual(self.app.vars['路径设置', 'pdf文件名'].get(), '模拟卷-题本.pdf')

    def test_controls_unlock_and_preview_validation(self):
        self.app._set_running(True)
        self.app._set_running(False)
        combo = next(w for w in self.app.lock_widgets if isinstance(w, ttk.Combobox))
        self.assertEqual(str(combo['state']), 'readonly')
        self.app.vars['排版参数', '每页题目数'].set('')
        self.assertIn('1–12', self.app.var_summary.get())
        self.app.vars['排版参数', '每页题目数'].set('3')
        self.assertIn('每页 3 题', self.app.var_summary.get())

    def test_tablet_landscape_presets_and_dropdown_presentation(self):
        self.assertIn('平板横屏 4:3', PAPER_NAMES)
        self.assertIn('平板横屏 16:10', PAPER_NAMES)
        self.assertGreaterEqual(int(self.app.paper_combo.cget('width')), 20)
        self.app.var_paper.set('平板横屏 4:3')
        self.app._apply_selected_paper()
        self.assertEqual(self.app.vars['排版参数', '页面宽度_mm'].get(), '280')
        self.assertEqual(self.app.vars['排版参数', '页面高度_mm'].get(), '210')
        self.assertIn('280 × 210 mm', self.app.var_summary.get())

    def test_custom_paper_preset_is_persisted_selected_and_deletable(self):
        self.assertTrue(self.app._store_custom_preset('我的笔记屏', '300', '180', show_errors=False))
        self.assertIn('我的笔记屏', self.app.paper_combo.cget('values'))
        self.assertEqual(self.app.var_paper.get(), '我的笔记屏')
        self.assertEqual(load_custom_paper_presets(self.base / 'config.ini'), [('我的笔记屏', '300', '180')])
        self.app.save_config(show_msg=False)
        self.assertEqual(load_custom_paper_presets(self.base / 'config.ini'), [('我的笔记屏', '300', '180')])
        self.assertTrue(self.app._delete_custom_preset('我的笔记屏'))
        self.assertEqual(load_custom_paper_presets(self.base / 'config.ini'), [])
        self.assertEqual(self.app.var_paper.get(), 'A4')

    def test_custom_paper_preset_validation_rejects_builtin_or_bad_size(self):
        self.assertFalse(self.app._store_custom_preset('A4', '300', '180', show_errors=False))
        self.assertFalse(self.app._store_custom_preset('太小', '10', '10', show_errors=False))
        self.assertEqual(self.app.custom_paper_presets, [])

    def test_custom_paper_preset_dialog_is_visible_and_usable(self):
        self.app.open_paper_presets()
        self.root.update_idletasks()
        self.assertTrue(self.app._paper_dialog.winfo_ismapped())
        self.assertTrue(self.app._preset_tree.winfo_ismapped())
        self.assertGreaterEqual(self.app._paper_dialog.winfo_width(), 520)
        self.assertGreaterEqual(self.app._paper_dialog.winfo_height(), 400)

    def test_cover_settings_save_and_summary(self):
        self.app.var_cover_enabled.set(True)
        self.app.var_cover_title.set('线性代数练习册')
        self.app.var_cover_description.set('矩阵与向量专题')
        self.assertIn('线性代数练习册', self.app.var_cover_summary.get())
        self.app.open_cover_settings()
        self.root.update_idletasks()
        self.assertTrue(self.app._cover_dialog.winfo_exists())
        self.assertTrue(self.app.cover_card.winfo_ismapped())
        self.app.save_config(show_msg=False)
        values = load_config_dict(self.base / 'config.ini')
        self.assertEqual(values['封面设置', '生成封面'], 'true')
        self.assertEqual(values['封面设置', '标题'], '线性代数练习册')
        self.assertEqual(values['封面设置', '描述'], '矩阵与向量专题')

    def test_cover_enable_checkbox_remains_clickable_when_cover_is_off(self):
        self.assertFalse(self.app.var_cover_enabled.get())
        self.app.open_cover_settings()
        self.root.update_idletasks()
        checkbox = self.app._cover_enable_control
        self.assertEqual(str(checkbox['state']), 'normal')
        checkbox.invoke()
        self.assertTrue(self.app.var_cover_enabled.get())

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
        with patch.object(self.app, 'open_output_dir'):
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
