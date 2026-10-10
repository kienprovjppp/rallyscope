"""Static background, court corners and the pixel-to-metre mapping.

  court.py bg     work60.mp4 bg.png [--step 6] [--max 160]
  court.py detect bg.png court.json [--kind pickleball] [--corners "x,y x,y x,y x,y"]
  court.py check  frame.png court.json out.png

Corners are ordered far-left, far-right, near-right, near-left (as seen on
screen). --corners overrides the automatic detection; always look at the
`check` image before trusting either.
"""
import argparse
import sys

import cv2
import numpy as np

from common import (court_dims, court_lines, homography, line_intersection, load,
                    project, read_frames, frame_count, save)


def cmd_bg(a):
    n = frame_count(a.video)
    step = max(a.step, int(np.ceil(n / a.max)))
    frames = [f for _, f in read_frames(a.video, step=step)]
    bg = np.median(np.stack(frames), axis=0).astype(np.uint8)
    cv2.imwrite(a.out, bg)
    print(f"background from {len(frames)} frames (every {step}th) -> {a.out}")


def line_mask(bg, s_max=70, v_min=170, tophat=21):
    hsv = cv2.cvtColor(bg, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (tophat, tophat)))
    m = ((hsv[..., 1] < s_max) & (hsv[..., 2] > v_min) & (th > 25)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return m


def order_corners(pts):
    pts = np.asarray(pts, np.float64)
    idx = np.argsort(pts[:, 1])
    top = pts[idx[:2]][np.argsort(pts[idx[:2], 0])]
    bot = pts[idx[2:]][np.argsort(pts[idx[2:], 0])]
    return np.array([top[0], top[1], bot[1], bot[0]])


def detect_corners(bg):
    m = line_mask(bg)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    h, w = m.shape
    # The court outline is one large connected component; pick the component
    # with the biggest bounding box that touches the image centre region.
    best, best_area = None, 0
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 200:
            continue
        cx, cy = x + bw / 2, y + bh / 2
        if not (0.15 * w < cx < 0.85 * w):
            continue
        if bw * bh > best_area:
            best, best_area = i, bw * bh
    if best is None:
        return None, m
    comp = (lab == best).astype(np.uint8) * 255
    pts = cv2.findNonZero(comp)
    hull = cv2.convexHull(pts)
    peri = cv2.arcLength(hull, True)
    quad = None
    for eps in np.linspace(0.005, 0.08, 60):
        ap = cv2.approxPolyDP(hull, eps * peri, True)
        if len(ap) == 4:
            quad = ap.reshape(4, 2)
            break
    if quad is None:
        # extreme points of the hull as a fallback
        hp = hull.reshape(-1, 2).astype(np.float64)
        quad = np.array([hp[np.argmin(hp[:, 0] + hp[:, 1])], hp[np.argmax(hp[:, 0] - hp[:, 1])],
                         hp[np.argmax(hp[:, 0] + hp[:, 1])], hp[np.argmin(hp[:, 0] - hp[:, 1])]])
    return order_corners(quad), comp


def cmd_detect(a):
    bg = cv2.imread(a.bg)
    h, w = bg.shape[:2]
    if a.corners:
        corners = order_corners([[float(v) for v in p.split(",")] for p in a.corners.split()])
        src = "manual"
    else:
        corners, comp = detect_corners(bg)
        if corners is None:
            sys.exit("no court outline found; pass --corners")
        cv2.imwrite(a.out.replace(".json", "_mask.png"), comp)
        src = "auto"
    H, Hinv = homography(corners, a.kind)
    vp = line_intersection(corners[0], corners[3], corners[1], corners[2])
    horizon = float(vp[1]) if vp is not None else -10.0 * h
    save(a.out, {"kind": a.kind, "source": src, "width": w, "height": h,
                 "corners": corners.round(2).tolist(), "H": H.tolist(), "Hinv": Hinv.tolist(),
                 "vanishing_point": None if vp is None else vp.round(2).tolist(),
                 "horizon_y": round(horizon, 2)}, indent=1)
    print(f"{src} corners FL,FR,NR,NL = {corners.round(1).tolist()}  horizon y = {horizon:.1f}")


def draw_court(img, Hinv, kind, color=(255, 230, 80), grid=True):
    W, L, K = court_dims(kind)
    out = img.copy()
    if grid:
        for x in np.arange(0, W + 1e-6, 1.0):
            p = project(Hinv, [[x, 0], [x, L]]).astype(int)
            cv2.line(out, tuple(p[0]), tuple(p[1]), (120, 120, 60), 1, cv2.LINE_AA)
        for y in np.arange(0, L + 1e-6, 1.0):
            p = project(Hinv, [[0, y], [W, y]]).astype(int)
            cv2.line(out, tuple(p[0]), tuple(p[1]), (120, 120, 60), 1, cv2.LINE_AA)
    cols = {"outline": color, "kitchen": (80, 255, 120), "centre": color, "net": (40, 170, 255)}
    for k, segs in court_lines(kind).items():
        for s in segs:
            p = project(Hinv, s).astype(int)
            cv2.line(out, tuple(p[0]), tuple(p[1]), cols[k], 2, cv2.LINE_AA)
    return out


def cmd_check(a):
    img = cv2.imread(a.frame)
    c = load(a.court)
    out = draw_court(img, np.array(c["Hinv"]), c["kind"])
    for i, p in enumerate(c["corners"]):
        cv2.circle(out, (int(p[0]), int(p[1])), 7, (0, 0, 255), 2)
        cv2.putText(out, ["FL", "FR", "NR", "NL"][i], (int(p[0]) + 8, int(p[1]) - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.imwrite(a.out, out)
    print("->", a.out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bg")
    b.add_argument("video")
    b.add_argument("out")
    b.add_argument("--step", type=int, default=6)
    b.add_argument("--max", type=int, default=160)
    d = sub.add_parser("detect")
    d.add_argument("bg")
    d.add_argument("out")
    d.add_argument("--kind", default="pickleball")
    d.add_argument("--corners")
    c = sub.add_parser("check")
    c.add_argument("frame")
    c.add_argument("court")
    c.add_argument("out")
    a = ap.parse_args()
    {"bg": cmd_bg, "detect": cmd_detect, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    main()
