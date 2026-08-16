import math
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta

import numpy as np

from avian.scripts.render_collage import (GRID_STRIDE, PAPER, RNG, layout,
                                          masks, mask_pack, recent_species,
                                          render, seed_for, slugify)

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _items(n, count=None):
    slugs = [s for s in masks() if not s.endswith("-2")][:n]
    return [{"sci": s.replace("-", " ").title(), "com": s,
             "n": count[i] if count else (i * 7) % 500 + 1}
            for i, s in enumerate(slugs)]


def _assert_no_overlap(test, placed, W, H):
    grid = np.zeros((math.ceil(H / GRID_STRIDE) + 2, math.ceil(W / GRID_STRIDE) + 2),
                    dtype=np.uint8)
    overlap = 0
    for t in placed:
        test.assertGreater(t["x"], -1000, "tile should be placed on-screen")
        test.assertGreaterEqual(t["x"], 0)
        test.assertGreaterEqual(t["y"], 0)
        test.assertLessEqual(t["x"] + t["fullW"], W + 0.5)
        test.assertLessEqual(t["y"] + t["fullH"], H + 0.5)
        test.assertAlmostEqual(t["fullW"] / t["fullH"], t["ar"], delta=0.01)
        gx0 = int(math.floor(t["x"] / GRID_STRIDE))
        gy0 = int(math.floor(t["y"] / GRID_STRIDE))
        kw, kh = t["fpw"], t["fph"]
        seg = grid[gy0:gy0 + kh, gx0:gx0 + kw]
        overlap += int(np.count_nonzero(seg & t["fp"]))
        seg |= t["fp"]
    test.assertEqual(overlap, 0, "tile silhouettes must not overlap")


class TestCollageLayout(unittest.TestCase):

    def setUp(self):
        self.items = _items(20)

    def test_layout_places_all_tiles_on_screen(self):
        placed = layout(self.items, 800, 480)
        self.assertIsNotNone(placed)
        self.assertEqual(len(placed), 20)

    def test_no_silhouette_overlaps(self):
        for W, H in ((800, 480), (1200, 1600)):
            placed = layout(self.items, W, H)
            _assert_no_overlap(self, placed, W, H)

    def test_counts_size_tiles(self):
        loud = [dict(x) for x in self.items]
        loud[0]["n"] = 1000
        quiet = [dict(x) for x in self.items]
        quiet[0]["n"] = 1
        # mask_pack re-sorts by area, so find the target species by sci.
        def area_of(items):
            placed = layout(items, 800, 480)
            t = next(t for t in placed if t["sci"] == items[0]["sci"])
            return t["fullW"] * t["fullH"]
        self.assertGreater(area_of(loud), area_of(quiet))

    def test_render_is_deterministic(self):
        a = render(self.items, 800, 480).tobytes()
        b = render(self.items, 800, 480).tobytes()
        self.assertEqual(a, b)

    def test_render_draws_content(self):
        img = render(self.items, 800, 480)
        arr = np.asarray(img)
        diff = np.abs(arr.astype(int) - np.array(PAPER)).sum(axis=2) > 20
        self.assertGreater(diff.mean(), 0.01)

    def test_fill_spans_more_viewport(self):
        # Fill mode must zoom the cluster toward the frame edges: the placed
        # tiles' bounding box should span a clearly larger fraction of the
        # viewport than the airy browser-default layout.
        from avian.scripts.render_collage import cluster_bounds

        def span(fill):
            placed = layout(self.items, 800, 480, fill=fill)
            self.assertIsNotNone(placed)
            b = cluster_bounds(placed)
            return (b["R"] - b["L"]) * (b["B"] - b["T"]) / (800 * 480)
        self.assertGreater(span(0.9), span(0.0) * 1.2)

    def test_empty_state_renders(self):
        img = render([], 800, 480)
        self.assertEqual(img.size, (800, 480))
        arr = np.asarray(img)
        diff = np.abs(arr.astype(int) - np.array(PAPER)).sum(axis=2) > 20
        self.assertGreater(diff.mean(), 0.0)

    def test_maskless_species_are_dropped(self):
        unknown = [{"sci": "Homo sapiens sapiens", "com": "you", "n": 5}]
        self.assertIsNone(layout(unknown, 800, 480))

    def test_known_species_rendered(self):
        known = [{"sci": "Calypte anna", "com": "Anna's Hummingbird", "n": 40}]
        img = render(known, 800, 480)
        arr = np.asarray(img)
        diff = np.abs(arr.astype(int) - np.array(PAPER)).sum(axis=2) > 20
        self.assertGreater(diff.mean(), 0.01)

    def test_seed_for_is_stable(self):
        items = _items(8)
        self.assertEqual(seed_for(items), seed_for(items))
        self.assertNotEqual(seed_for(items), seed_for(_items(8, [1] * 8)))

    def test_rng_matches_apt_js_sequence(self):
        rng = RNG(0x9E3779B9)
        expected = (0x9E3779B9 * 16807) % 2147483647
        self.assertEqual(rng.next(), expected / 2147483647)

    def test_recent_species_against_repo_db(self):
        db = os.path.join(ROOT, "scripts", "birds.db")
        if not os.path.exists(db):
            self.skipTest("no birds.db")
        rows = recent_species(db, 1000000)
        self.assertGreaterEqual(len(rows), 0)
        for r in rows:
            self.assertIn("sci", r)
            self.assertIn("n", r)

    def test_recent_species_today_window(self):
        # A calendar-day ("today") window must match only today's Date column,
        # while the rolling hours window uses time-since-now instead.
        now = datetime.now()
        old = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        fd, db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE detections (Sci_Name TEXT, Com_Name TEXT, "
                         "Date TEXT, Time TEXT, Confidence REAL, File_Name TEXT)")
            conn.execute("INSERT INTO detections VALUES ('Turdus migratorius', 'American Robin', "
                         "?, ?, 0.9, 'a.wav')", (now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")))
            conn.execute("INSERT INTO detections VALUES ('Corvus corax', 'Common Raven', "
                         "?, '06:00:00', 0.8, 'b.wav')", (old,))
            conn.commit()
            conn.close()

            today = recent_species(db, today=True)
            self.assertEqual([r["sci"] for r in today], ["Turdus migratorius"])
            self.assertEqual(today[0]["n"], 1)

            rolling = recent_species(db, 24)
            self.assertEqual([r["sci"] for r in rolling], ["Turdus migratorius"])

            everything = recent_species(db, 1000000)
            self.assertEqual(len(everything), 2)
        finally:
            os.unlink(db)

    def test_floor_keeps_rare_birds_visible(self):
        placed = layout(self.items, 800, 480, floor=0.0)
        placed_f = layout(self.items, 800, 480, floor=0.5)
        rare = [t for t in placed if t["score"] == min(p["score"] for p in placed)]
        rare_f = [t for t in placed_f if t["score"] == min(p["score"] for p in placed_f)]
        if rare and rare_f:
            self.assertGreaterEqual(rare_f[0]["fullW"] * rare_f[0]["fullH"],
                                    rare[0]["fullW"] * rare[0]["fullH"])


if __name__ == "__main__":
    unittest.main()
