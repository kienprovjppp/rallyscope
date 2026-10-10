"""Strike times from two sources that must agree.

  strikes.py rings  work60.mp4 rings.json [--h 0,10 --s 120 --v 120]
        footage that already carries a strike marker (a red ring): detect it by colour and
        shape, group detections by position (one ring is drawn for 20+ frames), strike =
        ring start + 3. Also writes anchors (first three frames of each ring) for the ball solver.
  strikes.py merge  audio_hits.json ball_raw.json pose.npz court.json strikes.json
                    [--rings rings.json] [--add f,f] [--drop f,f] [--first F] [--last F]
        raw footage: a strike is an audio peak where the ball sits near a player's hand and the
        ball reverses direction along the length of the court. A bounce does not reverse it.
"""
import argparse

import cv2
import numpy as np

from common import load, read_frames, save


def cmd_rings(a):
    h0, h1 = [int(v) for v in a.h.split(",")]
    dets = []
    for i, fr in read_frames(a.video):
        hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
        hue = hsv[..., 0]
        red = ((hue <= h1) | (hue >= 180 - h1)) if h0 == 0 else ((hue >= h0) & (hue <= h1))
        m = (red & (hsv[..., 1] >= a.s) & (hsv[..., 2] >= a.v)).astype(np.uint8) * 255
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            if not (a.rmin * 2 <= w <= a.rmax * 2 and 0.6 <= w / max(h, 1) <= 1.7):
                continue
            area = cv2.countNonZero(m[y:y + h, x:x + w])
            fill = area / float(w * h)
            if fill > 0.55:  # a ring is mostly hollow
                continue
            dets.append((i, x + w / 2, y + h / 2, (w + h) / 4))
    groups = []
    for f, x, y, r in dets:
        for g in groups:
            lf, lx, ly = g[-1][0], g[-1][1], g[-1][2]
            if 0 < f - lf <= 3 and np.hypot(x - lx, y - ly) < 40:
                g.append((f, x, y, r))
                break
        else:
            groups.append([(f, x, y, r)])
    groups = [g for g in groups if len(g) >= a.minlen]
    rings, anchors = [], []
    for g in groups:
        rings.append({"start": g[0][0], "end": g[-1][0], "x": round(g[0][1], 1), "y": round(g[0][2], 1),
                      "strike_frame": g[0][0] + 3})
        for f, x, y, r in g[:3]:
            anchors.append({"frame": f, "x": round(x, 1), "y": round(y, 1)})
    save(a.out, {"rings": rings, "anchors": anchors}, indent=1)
    for r in rings:
        print(f"ring frames {r['start']}-{r['end']} at ({r['x']:.0f},{r['y']:.0f}) -> strike {r['strike_frame']}")


def ball_at(track, f, win=3):
    for d in range(win + 1):
        for g in (f - d, f + d):
            if 0 <= g < len(track) and track[g] is not None:
                return np.array(track[g][:2], float)
    return None


def vy_window(track, f, lo, hi):
    pts = [(g, track[g][1]) for g in range(f + lo, f + hi + 1) if 0 <= g < len(track) and track[g] is not None]
    if len(pts) < 3:
        return None
    g, y = np.array(pts).T
    return float(np.polyfit(g, y, 1)[0])


def cmd_merge(a):
    hits = load(a.audio)["hits"]
    raw = load(a.ball)
    track = raw.get("track") or raw.get("ball")
    d = np.load(a.pose)
    lm = d["lm"]
    hh = d["h"]
    P = lm.shape[0]
    court = load(a.court)
    net_y_img = None
    rings = load(a.rings)["rings"] if a.rings else []
    drop = {int(v) for v in a.drop.split(",")} if a.drop else set()
    rows = []
    for hgt in hits:
        f = hgt["frame"]
        if a.first is not None and f < a.first or a.last is not None and f > a.last:
            continue
        b = ball_at(track, f)
        near = None
        if b is not None and f < lm.shape[1]:
            best = (1e9, None)
            for p in range(P):
                L = lm[p, f]
                dd = min(np.hypot(*(L[15, :2] - b)), np.hypot(*(L[16, :2] - b)), 1.3 * np.hypot(*(L[0, :2] - b)))
                dn = dd / max(hh[p, f], 40)
                if dn < best[0]:
                    best = (dn, p)
            near = best
        k = a.fps / 60.0
        vb = vy_window(track, f, -round(10 * k), -max(1, round(2 * k)))
        va = vy_window(track, f, max(1, round(2 * k)), round(10 * k))
        rev = vb is not None and va is not None and np.sign(vb) != np.sign(va) and abs(vb - va) > 1.0 * 60 / a.fps
        ring = any(abs(r["strike_frame"] - f) <= 4 for r in rings)
        rows.append(dict(frame=f, t=hgt["t"], energy=hgt["energy"], near=near, rev=rev, ring=ring, vb=vb, va=va))

    strikes = []
    last_team = None
    for r in rows:
        dn, p = r["near"] if r["near"] else (None, None)
        team = None if p is None else (0 if p < 2 else 1)
        if rings:
            ok = r["ring"]
        else:
            ok = dn is not None and dn < a.hand and r["rev"] and team != last_team
        if r["frame"] in drop:
            ok = False
        tag = "STRIKE" if ok else "-"
        vb = "-" if r["vb"] is None else f"{r['vb']:+.1f}"
        va = "-" if r["va"] is None else f"{r['va']:+.1f}"
        print(f"{tag:6s} frame {r['frame']:5d} t={r['t']:6.2f} e={r['energy']:.2f} "
              f"near={'-' if p is None else f'P{p + 1} {dn:.2f}h'} vy {vb}->{va} rev={r['rev']} ring={r['ring']}")
        if ok:
            strikes.append({"frame": r["frame"], "t": r["t"], "src": "ring" if rings else "audio+ball"})
            last_team = team
    for r in rings:  # rings without an audio peak still count; ring start + 3 is the strike
        if not any(abs(s["frame"] - r["strike_frame"]) <= 4 for s in strikes) and r["strike_frame"] not in drop:
            strikes.append({"frame": r["strike_frame"], "t": round(r["strike_frame"] / a.fps, 3), "src": "ring"})
    for f in (int(v) for v in a.add.split(",")) if a.add else []:
        strikes.append({"frame": f, "t": round(f / a.fps, 3), "src": "manual"})
    strikes.sort(key=lambda s: s["frame"])
    save(a.out, {"strikes": strikes}, indent=1)
    print(f"{len(strikes)} strikes: {[s['frame'] for s in strikes]}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rings")
    r.add_argument("video"); r.add_argument("out")
    r.add_argument("--h", default="0,10"); r.add_argument("--s", type=int, default=120)
    r.add_argument("--v", type=int, default=120); r.add_argument("--rmin", type=int, default=8)
    r.add_argument("--rmax", type=int, default=60); r.add_argument("--minlen", type=int, default=8)
    m = sub.add_parser("merge")
    m.add_argument("audio"); m.add_argument("ball"); m.add_argument("pose"); m.add_argument("court")
    m.add_argument("out"); m.add_argument("--rings"); m.add_argument("--add"); m.add_argument("--drop")
    m.add_argument("--first", type=int); m.add_argument("--last", type=int)
    m.add_argument("--hand", type=float, default=0.9, help="max ball-to-hand distance in player heights")
    m.add_argument("--fps", type=float, default=60.0, help="frame rate of the frames the tracks use")
    a = ap.parse_args()
    {"rings": cmd_rings, "merge": cmd_merge}[a.cmd](a)


if __name__ == "__main__":
    main()
