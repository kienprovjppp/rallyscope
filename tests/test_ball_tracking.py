"""Run with: python -m unittest discover -s tests -p test_ball_tracking.py"""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import numpy as np
import cv2
from ball_viterbi import cmd_cands, cmd_solve, moving_candidates


class BallTrackingTest(unittest.TestCase):
    def solve(self, per, fps, anchors=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [(t, *c) for t, cs in enumerate(per) for c in cs]
            columns = list(zip(*rows)) if rows else [[], [], [], [], []]
            np.savez(root / "cands.npz", n=len(per), fps=fps, width=1920,
                     **dict(zip(("f", "x", "y", "cost", "rim"), columns)))
            (root / "anchors.json").write_text(json.dumps({"anchors": anchors or []}))
            cmd_solve(SimpleNamespace(cands=root / "cands.npz", out=root / "ball.json",
                                     anchors=root / "anchors.json", scale=60 / fps))
            return json.loads((root / "ball.json").read_text())["track"]

    def test_moving_ball_and_occlusion_do_not_select_static_dots(self):
        for fps in (30, 60):
            dots = [[(700 + t % 3 - 1, 400, 0, 1), (900, 500, 0, 1)] for t in range(fps)]
            ball = [(100 + 300 * t / fps, 200, 0.4, 1) for t in range(fps)]
            per = [[ball[t], *dots[t]] for t in range(fps)]
            for gap in (False, True):
                candidates = [dots[t] if gap and fps / 3 <= t < fps / 2 else per[t] for t in range(fps)]
                track = self.solve(candidates, fps)
                for t, p in enumerate(track):
                    expected = None if gap and fps / 3 <= t < fps / 2 else [*ball[t][:2], 1]
                    self.assertEqual(p, expected)
            self.assertTrue(all(p is None for p in self.solve(dots, fps)))

    def test_empty_and_manual_anchor(self):
        self.assertEqual(self.solve([], 60), [])
        per = [[(500, 300, 0, 1)] for _ in range(40)]
        track = self.solve(per, 60, [{"frame": 20, "x": 500, "y": 300}])
        self.assertEqual(track[20], [500, 300, 1])
        self.assertEqual(sum(p is not None for p in track), 1)

    def test_slow_turn_and_short_clips_are_preserved(self):
        per = [[(100 + 0.3 * (t - 30) ** 2, 200, 0, 1)] for t in range(60)]
        self.assertEqual(moving_candidates(per, 60, 1), per)
        short = [[(100, 200, 0, 1)] for _ in range(5)]
        self.assertEqual(moving_candidates(short, 60, 1), short)

    def test_candidates_use_court_and_save_video_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bg = np.zeros((180, 320, 3), np.uint8)
            cv2.imwrite(str(root / "bg.png"), bg)
            court = {"width": 320, "height": 180, "corners": [[120, 60], [200, 60], [200, 140], [120, 140]]}
            (root / "court.json").write_text(json.dumps(court))
            frame = bg.copy()
            frame[85:95, 155:165] = frame[85:95, 15:25] = (0, 255, 255)
            args = SimpleNamespace(bg=str(root / "bg.png"), court=None, video="synthetic",
                                   out=root / "cands.npz", h="5,45", s=80, v=110, exclude=None,
                                   rim="0:5", cref=40, chan="yellow", diff=0,
                                   amin=6, amax=400, aspect=2.5, fill=0.45)
            with patch("ball_viterbi.cv2.VideoCapture") as cap, patch("ball_viterbi.read_frames", return_value=[(0, frame)]):
                cap.return_value.get.return_value = 30
                cmd_cands(args)
            with np.load(args.out) as data:
                self.assertEqual(len(data["x"]), 1)
                self.assertAlmostEqual(data["x"][0], 159.5)
                self.assertEqual(float(data["fps"]), 30)
                self.assertEqual(int(data["width"]), 320)


if __name__ == "__main__":
    unittest.main()
