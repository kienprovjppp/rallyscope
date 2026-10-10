"""Shared helpers: court geometry, JSON I/O, frame reading."""
import json
import os

import cv2
import numpy as np

# Pickleball court in metres. x runs across the court (0 = left sideline as seen
# from the camera), y runs along it (0 = far baseline, LEN = near baseline).
COURT = {
    "pickleball": {"W": 6.10, "L": 13.41, "kitchen": 2.134},
    "tennis": {"W": 10.97, "L": 23.77, "kitchen": 6.40},  # kitchen = service line
    "badminton": {"W": 6.10, "L": 13.40, "kitchen": 1.98},  # kitchen = short service line
}
FPS = 60.0

# MediaPipe pose landmark indices that the page and the metrics use.
LM = dict(nose=0, ls=11, rs=12, le=13, re=14, lw=15, rw=16, lh=23, rh=24,
          lk=25, rk=26, la=27, ra=28, lheel=29, rheel=30, lt=31, rt=32)
KEEP = [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32]


def load(path):
    with open(path) as f:
        return json.load(f)


def save(path, obj, indent=None):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=indent, separators=None if indent else (",", ":"))


def court_dims(kind="pickleball"):
    c = COURT[kind]
    return c["W"], c["L"], c["kitchen"]


def court_world_corners(kind="pickleball"):
    W, L, _ = court_dims(kind)
    # far-left, far-right, near-right, near-left
    return np.array([[0, 0], [W, 0], [W, L], [0, L]], np.float64)


def court_lines(kind="pickleball"):
    """Line segments of the court in metres: baselines, sidelines, net, kitchen
    lines and the centre lines from each kitchen line to its baseline."""
    W, L, K = court_dims(kind)
    n = L / 2
    return {
        "outline": [[[0, 0], [W, 0]], [[W, 0], [W, L]], [[W, L], [0, L]], [[0, L], [0, 0]]],
        "net": [[[0, n], [W, n]]],
        "kitchen": [[[0, n - K], [W, n - K]], [[0, n + K], [W, n + K]]],
        "centre": [[[W / 2, 0], [W / 2, n - K]], [[W / 2, n + K], [W / 2, L]]],
    }


def homography(img_corners, kind="pickleball"):
    """Image -> court (metres) homography and its inverse."""
    src = np.asarray(img_corners, np.float64)
    dst = court_world_corners(kind)
    H, _ = cv2.findHomography(src, dst)
    return H, np.linalg.inv(H)


def project(H, pts):
    pts = np.asarray(pts, np.float64)
    one = pts.ndim == 1
    p = np.atleast_2d(pts)
    q = np.c_[p, np.ones(len(p))] @ H.T
    q = q[:, :2] / q[:, 2:3]
    return q[0] if one else q


def line_intersection(p1, p2, p3, p4):
    """Intersection of the infinite lines p1-p2 and p3-p4."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(d) < 1e-9:
        return None
    a = x1 * y2 - y1 * x2
    b = x3 * y4 - y3 * x4
    return np.array([(a * (x3 - x4) - (x1 - x2) * b) / d, (a * (y3 - y4) - (y1 - y2) * b) / d])


def read_frames(path, start=0, end=None, step=1):
    cap = cv2.VideoCapture(path)
    if start:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    i = start
    while True:
        ok, fr = cap.read()
        if not ok or (end is not None and i >= end):
            break
        if (i - start) % step == 0:
            yield i, fr
        i += 1
    cap.release()


def frame_count(path):
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return n


def read_frame(path, idx):
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, fr = cap.read()
    cap.release()
    return fr if ok else None
