import os
import sys
import unittest

# frame-zero/cycle.py is self-contained; put the folder on the path.
FRAME_ZERO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'frame-zero')
sys.path.insert(0, FRAME_ZERO)

from cycle import PANEL_H, PANEL_W, WINDOWS, collage_url, fit, load_config  # noqa: E402


class FrameZeroTests(unittest.TestCase):
    def test_default_config(self):
        cfg = load_config(None)
        self.assertEqual(cfg["windows"], ["all", "today"])
        self.assertEqual(cfg["interval"], 300)
        self.assertEqual((cfg["width"], cfg["height"]), (800, 480))

    def test_config_file(self):
        fd, path = os.path.join(FRAME_ZERO, "config.example.toml"), None
        cfg = load_config(fd)
        self.assertEqual(cfg["base_url"], "http://birdnet.local")
        self.assertEqual(cfg["windows"], ["all", "today"])

    def test_collage_url(self):
        cfg = load_config(None)
        self.assertEqual(collage_url(cfg, "all"),
                         "http://birdnet.local/all?orientation=landscape&w=800&h=480")
        self.assertEqual(collage_url(cfg, "today"),
                         "http://birdnet.local/today?orientation=landscape&w=800&h=480")

    def test_windows_are_valid(self):
        self.assertIn("all", WINDOWS)
        self.assertIn("today", WINDOWS)

    def test_fit_exact_size_is_noop(self):
        from PIL import Image
        img = Image.new("RGB", (800, 480))
        out = fit(img, 800, 480)
        self.assertEqual(out.size, (800, 480))
        self.assertIs(out, img)

    def test_fit_4x3_crops_to_panel(self):
        from PIL import Image
        img = Image.new("RGB", (1600, 1200))
        out = fit(img, 800, 480)
        self.assertEqual(out.size, (800, 480))
        self.assertEqual(out.width / out.height, 800 / 480)

    def test_fit_squarish_pad(self):
        from PIL import Image
        img = Image.new("RGB", (400, 400))
        out = fit(img, 800, 480)
        self.assertEqual(out.size, (800, 480))
        self.assertEqual(out.width / out.height, 800 / 480)


if __name__ == "__main__":
    unittest.main()
