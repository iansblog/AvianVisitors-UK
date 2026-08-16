import os
import sys
import unittest

import numpy as np

# frame/panel.py does "import display"; put the frame dir on the path.
FRAME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'frame')
sys.path.insert(0, FRAME)

from panel import SPECTRA6, fit_panel, load_config, quantize  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _gradient(w, h):
    import numpy as np
    yy, xx = np.mgrid[0:h, 0:w]
    return np.dstack([(xx * 255 // max(1, w - 1)).astype(np.uint8),
                      (yy * 255 // max(1, h - 1)).astype(np.uint8),
                      ((xx + yy) * 255 // max(1, w + h - 2)).astype(np.uint8)])


class PanelTests(unittest.TestCase):
    def test_fit_panel_exact_noop(self):
        from PIL import Image
        img = Image.new('RGB', (800, 480))
        self.assertIs(fit_panel(img, 800, 480), img)

    def test_fit_panel_resizes(self):
        from PIL import Image
        img = Image.fromarray(_gradient(640, 384))
        out = fit_panel(img, 400, 300)
        self.assertEqual(out.size, (400, 300))

    def test_quantize_spectra6_uses_only_palette(self):
        from PIL import Image
        out = quantize(Image.fromarray(_gradient(120, 90)), SPECTRA6)
        cols = sorted(set(out.getdata()))
        self.assertLessEqual(len(cols), len(SPECTRA6))
        for c in cols:
            self.assertIn(tuple(c), SPECTRA6)

    def test_quantize_mono_is_black_and_white(self):
        from PIL import Image
        mono = [(255, 255, 255), (0, 0, 0)]
        out = quantize(Image.fromarray(_gradient(120, 90)), mono)
        self.assertEqual(sorted(set(out.getdata())), [(0, 0, 0), (255, 255, 255)])

    def test_quantize_order_keeps_palette(self):
        from PIL import Image
        img = Image.fromarray(_gradient(120, 90))
        for inks in (SPECTRA6, list(reversed(SPECTRA6))):
            out = quantize(img, inks)
            cols = sorted(set(out.getdata()))
            self.assertLessEqual(len(cols), len(SPECTRA6))
            for c in cols:
                self.assertIn(tuple(c), SPECTRA6)

    def test_load_config_parses_types(self):
        path = os.path.join(ROOT, 'frame', 'config.example.toml')
        cfg = load_config(path)
        self.assertEqual(cfg['width'], 800)
        self.assertEqual(cfg['height'], 480)
        self.assertIsInstance(cfg['inks'], list)
        self.assertTrue(all(len(i) == 3 for i in cfg['inks']))

    def test_load_config_missing_file_raises(self):
        from panel import load_config
        with self.assertRaises(FileNotFoundError):
            load_config('/nonexistent/config.toml')


if __name__ == '__main__':
    unittest.main()
