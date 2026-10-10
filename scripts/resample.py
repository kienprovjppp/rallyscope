"""Bring tracks measured on native frames (e.g. 29.97 fps) onto the 60 fps timeline.

  resample.py ball.json pose.npz strikes.json --src-fps 29.97 --frames N --out-dir DIR

Footage that is not 60 fps is analysed on its own frames (duplicated frames would
stall the constant-velocity ball model), then every track is interpolated onto the
60 fps working file: frame f of the 60 fps file sits at native position f * src / 60.
Writes DIR/ball60.json, DIR/pose60.npz and DIR/strikes60.json.
"""
import argparse
import os

import numpy as np

from common import FPS, load, save


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ball"); ap.add_argument("pose"); ap.add_argument("strikes")
    ap.add_argument("--src-fps", type=float, required=True)
    ap.add_argument("--frames", type=int, required=True, help="frame count of the 60 fps file")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    n = a.frames
    pos = np.arange(n) * a.src_fps / FPS                      # native (fractional) frame per 60 fps frame

    b = load(a.ball)
    B = b["ball"]
    out = []
    for k in pos:
        i0 = int(np.floor(k)); i1 = i0 + 1; w = k - i0
        p0 = B[i0] if i0 < len(B) else None
        p1 = B[i1] if i1 < len(B) else None
        if p0 is not None and p1 is not None:
            out.append([round(p0[0] * (1 - w) + p1[0] * w, 1), round(p0[1] * (1 - w) + p1[1] * w, 1)])
        elif p0 is not None and w <= 0.5:
            out.append(p0)
        elif p1 is not None and w > 0.5:
            out.append(p1)
        else:
            out.append(None)
    save(os.path.join(a.out_dir, "ball60.json"),
         {"frames": n, "start": int(round(b["start"] * FPS / a.src_fps)),
          "end": int(round(b["end"] * FPS / a.src_fps)), "ball": out})

    d = np.load(a.pose)
    N = d["lm"].shape[1]
    i0 = np.clip(np.floor(pos).astype(int), 0, N - 1)
    i1 = np.clip(i0 + 1, 0, N - 1)
    w = (pos - np.floor(pos))[None, :, None, None]
    res = {}
    for k in ("lm", "world"):
        A = d[k]
        res[k] = A[:, i0] * (1 - w) + A[:, i1] * w
    near = np.clip(np.round(pos).astype(int), 0, N - 1)
    res["ok"] = d["ok"][:, near]
    res["h"] = d["h"][:, near]
    np.savez_compressed(os.path.join(a.out_dir, "pose60.npz"), **res)

    sj = load(a.strikes)
    st = sj["strikes"]
    for s in st:
        s["native_frame"] = s["frame"]
        s["frame"] = int(round(s["t"] * FPS))
    out = {"strikes": st}
    if "bounces_native" in sj:  # bounces confirmed on the footage
        out["bounces"] = [[int(round(b[0] / a.src_fps * FPS))] + list(b[1:]) if isinstance(b, list)
                          else int(round(b / a.src_fps * FPS)) for b in sj["bounces_native"]]
    save(os.path.join(a.out_dir, "strikes60.json"), out, indent=1)
    print(f"resampled {len(B)} native frames -> {n} frames at {FPS:.0f} fps; {len(st)} strikes")


if __name__ == "__main__":
    main()
