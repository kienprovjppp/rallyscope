"""Strike candidates from the paddle sound.

High-pass at 1.2 kHz, 10 ms energy envelope, a peak counts when it is 2.5 times
the mean of the previous 60 ms, and only the highest peak within 0.25 s is kept.

usage: audio_hits.py audio.wav out.json [--fps 60] [--ratio 2.5] [--floor 4]
"""
import argparse

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfiltfilt


def envelope(x, sr, win_ms=10.0, hop_ms=1.0):
    win = max(1, int(sr * win_ms / 1000))
    hop = max(1, int(sr * hop_ms / 1000))
    sq = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
    starts = np.arange(0, len(x) - win, hop)
    e = (sq[starts + win] - sq[starts]) / win
    t = (starts + win / 2) / sr
    return t, e, hop_ms / 1000.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=60.0)
    ap.add_argument("--ratio", type=float, default=2.5, help="peak / mean of previous 60 ms")
    ap.add_argument("--floor", type=float, default=4.0,
                    help="peak must also exceed this many times the median envelope")
    ap.add_argument("--nms", type=float, default=0.25)
    a = ap.parse_args()

    sr, x = wavfile.read(a.wav)
    x = x.astype(np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    x /= (np.abs(x).max() + 1e-9)
    sos = butter(4, 1200, btype="highpass", fs=sr, output="sos")
    y = sosfiltfilt(sos, x)
    t, e, hop = envelope(y, sr)

    back = int(round(0.060 / hop))
    gap = int(round(0.010 / hop))  # skip the 10 ms right before the peak (rise time)
    med = np.median(e) + 1e-12
    cands = []
    for i in range(back + gap, len(e) - 1):
        if e[i] < e[i - 1] or e[i] < e[i + 1]:
            continue
        prev = e[i - back - gap:i - gap].mean() + 1e-12
        if e[i] >= a.ratio * prev and e[i] >= a.floor * med:
            cands.append((i, e[i], e[i] / prev))

    # keep only the highest peak within the NMS window
    cands.sort(key=lambda c: -c[1])
    kept = []
    win = int(round(a.nms / hop))
    for c in cands:
        if all(abs(c[0] - k[0]) >= win for k in kept):
            kept.append(c)
    kept.sort(key=lambda c: c[0])

    out = []
    ref = max((k[1] for k in kept), default=1.0)
    for i, val, rat in kept:
        out.append({"t": round(float(t[i]), 4), "frame": int(round(t[i] * a.fps)),
                    "energy": round(float(val / ref), 4), "ratio": round(float(rat), 2)})
    import json
    with open(a.out, "w") as f:
        json.dump({"sr": int(sr), "hits": out}, f, indent=1)
    print(f"{len(out)} audio peaks")
    for o in out:
        print(f"  t={o['t']:7.3f}s frame={o['frame']:5d} energy={o['energy']:.3f} ratio={o['ratio']:.1f}")


if __name__ == "__main__":
    main()
