"""Ball track solved as one global path.

  ball_viterbi.py profile work60.mp4 --known "f,x,y f,x,y"
        brightness against radius at known ball positions -> darkest radius (rim)
  ball_viterbi.py cands   work60.mp4 bg.png cands.npz --rim "y1:r1,y2:r2" [--h 5,45 --s 80 --v 110]
        per-frame candidates (HSV mask minus static background, opening, components)
  ball_viterbi.py solve   cands.npz ball_raw.json [--anchors anchors.json]
        beam search over (position, velocity, missed frames)
  ball_viterbi.py smooth  ball_raw.json strikes.json ball.json [--anchors anchors.json]
        per segment between strikes: robust spline x4, PCHIP across gaps, Gaussian 1.2
  ball_viterbi.py check   work60.mp4 ball.json out.png [--frame N]
        prints the position every 6 frames, flags stuck runs, draws the whole track
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.interpolate import PchipInterpolator, UnivariateSpline
from scipy.ndimage import gaussian_filter1d

from common import load, read_frame, read_frames, save


# ---------------------------------------------------------------- rim profile
def radial_profile(gray, x, y, rmax=14):
    h, w = gray.shape
    yy, xx = np.mgrid[-rmax - 1:rmax + 2, -rmax - 1:rmax + 2]
    rr = np.sqrt(xx ** 2 + yy ** 2)
    x0, y0 = int(round(x)), int(round(y))
    prof = []
    for r in range(0, rmax + 1):
        sel = (rr >= r - 0.5) & (rr < r + 0.5)
        ys, xs = yy[sel] + y0, xx[sel] + x0
        ok = (ys >= 0) & (ys < h) & (xs >= 0) & (xs < w)
        prof.append(float(gray[ys[ok], xs[ok]].mean()) if ok.any() else np.nan)
    return np.array(prof)


def channel(fr, chan):
    """gray, or 'yellow' = (R+G)/2 - B, which separates the ball from both the
    dark floor and the blue court."""
    if chan == "yellow":
        b, g, r = [fr[..., k].astype(np.float32) for k in range(3)]
        return np.clip((r + g) / 2 - b + 128, 0, 255)
    return cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32)


def cmd_profile(a):
    out = []
    for item in a.known.split():
        f, x, y = [float(v) for v in item.split(",")]
        fr = read_frame(a.video, int(f))
        p = radial_profile(channel(fr, a.chan), x, y)
        # darkest radius beyond the bright core; if the profile only falls to the
        # background (no dark rim), the edge is where it gets within 15% of it
        dark = int(np.nanargmin(p[2:]) + 2)
        bgv = np.nanmedian(p[-4:])
        edge = int(np.argmax(p - bgv <= 0.15 * (p[0] - bgv)))
        has_rim = p[dark] < bgv - 0.1 * (p[0] - bgv)
        r = dark if has_rim else edge
        out.append({"frame": int(f), "x": x, "y": y, "rim": r, "profile": np.round(p, 1).tolist()})
        print(f"frame {int(f)} ({x:.0f},{y:.0f}) darkest r={dark} edge r={edge} dark rim={'yes' if has_rim else 'no'}"
              f" -> r={r}  profile: " + " ".join(f"{v:.0f}" for v in p))
    print("rim spec: --rim \"" + ",".join(f"{o['y']:.0f}:{o['rim']}" for o in out) + "\"")
    cons = [o["profile"][0] - np.mean(o["profile"][o["rim"] - 1:o["rim"] + 2]) for o in out]
    print(f"reference contrast (core - rim): {np.round(cons, 1).tolist()} -> --cref {np.mean(cons):.0f}")


# ---------------------------------------------------------------- candidates
def parse_rim(spec):
    pts = sorted([tuple(float(v) for v in p.split(":")) for p in spec.split(",")])
    ys = np.array([p[0] for p in pts])
    rs = np.array([p[1] for p in pts])
    return lambda y: float(np.interp(y, ys, rs)) if len(ys) > 1 else float(rs[0])


def ball_mask(hsv, a):  # noqa: D401
    h0, h1 = a.hrange
    return ((hsv[..., 0] >= h0) & (hsv[..., 0] <= h1) & (hsv[..., 1] >= a.s) &
            (hsv[..., 2] >= a.v)).astype(np.uint8) * 255


def rim_contrast(gray, x, y, r):
    """Brightness inside the ball minus brightness on the rim (r-1..r+1)."""
    p = radial_profile(gray, x, y, rmax=int(np.ceil(r)) + 2)
    rr = int(round(r))
    core = np.nanmean(p[:max(1, rr - 1)])
    rim = np.nanmean(p[max(1, rr - 1):rr + 2])
    return core - rim


def cmd_cands(a):
    a.hrange = [int(v) for v in a.h.split(",")]
    bg = cv2.imread(a.bg)
    if bg is None:
        raise ValueError(f"Cannot read background: {a.bg}")
    height, width = bg.shape[:2]
    court_path = Path(a.court) if a.court else Path(a.bg).with_name("court.json")
    court_mask = np.ones((height, width), np.uint8)
    if a.court or court_path.exists():
        court = load(court_path)
        corners = np.asarray(court["corners"], dtype=float)
        if corners.shape != (4, 2) or not np.isfinite(corners).all():
            raise ValueError("Court must contain four finite image coordinates")
        if court.get("width", width) != width or court.get("height", height) != height:
            raise ValueError("Court and background dimensions must match")
        # Include airborne balls above the court, as in the upload detector.
        x0, y0 = corners.min(axis=0); x1, y1 = corners.max(axis=0)
        court_mask.fill(0)
        left = max(0, int(np.floor(x0 - 0.12 * width)))
        right = min(width, int(np.ceil(x1 + 0.12 * width)))
        top = max(0, int(np.floor(y0 - 0.45 * (y1 - y0))))
        bottom = min(height, int(np.ceil(y1 + 0.05 * height)))
        if left >= right or top >= bottom:
            raise ValueError("Court does not overlap the video")
        court_mask[top:bottom, left:right] = 1
    else:
        print("No court.json: searching the full frame; use --court to restrict the search")
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    if not np.isfinite(fps) or fps <= 0:
        raise ValueError(f"Cannot read video frame rate: {a.video}")
    bg_mask = cv2.dilate(ball_mask(cv2.cvtColor(bg, cv2.COLOR_BGR2HSV), a),
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))  # 5 px each side
    excl = np.zeros(bg.shape[:2], np.uint8)
    for r in (a.exclude or "").split():
        x, y, w, h = [int(v) for v in r.split(",")]
        excl[y:y + h, x:x + w] = 255
    rim_of = parse_rim(a.rim)
    # contrast reference from the known positions, if given
    cref = a.cref
    k3 = np.ones((3, 3), np.uint8)
    F, X, Y, A, R, C = [], [], [], [], [], []
    nfr = 0
    for i, fr in read_frames(a.video):
        if fr.shape[:2] != bg.shape[:2]:
            raise ValueError("Video and background dimensions must match")
        nfr = i + 1
        hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
        gray = channel(fr, a.chan)
        m = ball_mask(hsv, a)
        m[court_mask == 0] = 0
        m[bg_mask > 0] = 0
        m[excl > 0] = 0
        if a.diff:
            m[cv2.absdiff(fr, bg).max(axis=2) < a.diff] = 0
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k3)
        n, lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
        for j in range(1, n):
            x, y, w, h, area = st[j]
            if not (a.amin <= area <= a.amax):
                continue
            asp = w / max(h, 1)
            if not (1 / a.aspect <= asp <= a.aspect):
                continue
            if area / float(w * h) <= a.fill:
                continue
            cx, cy = cen[j]
            con = rim_contrast(gray, cx, cy, rim_of(cy))
            rim = float(np.clip(con / cref, 0, 1))
            F.append(i); X.append(cx); Y.append(cy); A.append(area); R.append(rim)
            C.append(1.6 * (1 - rim) + 0.004 * abs(area - 45))
        if i % 120 == 0:
            print(f"frame {i}: {sum(1 for f in F if f == i)} candidates")
    np.savez(a.out, n=nfr, fps=fps, width=width, f=np.array(F), x=np.array(X), y=np.array(Y), area=np.array(A),
             rim=np.array(R), cost=np.array(C))
    print(f"{len(F)} candidates over {nfr} frames ({len(F) / max(nfr, 1):.1f}/frame)")


# ---------------------------------------------------------------- beam search
def moving_candidates(per, fps, spatial_scale):
    """Remove persistent spots before zero-velocity paths can win the beam search."""
    window = max(4, int(0.2 * fps + 0.5))
    radius = 3 * spatial_scale
    out = []
    # shortcut: assumes a fixed camera; compensate camera motion for panning footage.
    for t, cs in enumerate(per):
        lo, hi = max(0, t - window), min(len(per), t + window + 1)
        out.append([c for c in cs if hi - lo < 8 or sum(
            any(np.hypot(p[0] - c[0], p[1] - c[1]) <= radius for p in per[k])
            for k in range(lo, hi)) < 0.8 * (hi - lo)])
    return out


def cmd_solve(a):
    if not np.isfinite(a.scale) or a.scale <= 0:
        raise ValueError("Scale must be positive and finite")
    d = np.load(a.cands)
    n = int(d["n"])
    per = [[] for _ in range(n)]
    for k in range(len(d["f"])):
        per[int(d["f"][k])].append((d["x"][k], d["y"][k], d["cost"][k], d["rim"][k]))
    fps = float(d["fps"]) if "fps" in d else 60 / a.scale
    spatial_scale = float(d["width"]) / 1920 if "width" in d else 1
    if not np.isfinite([fps, spatial_scale]).all() or fps <= 0 or spatial_scale <= 0:
        raise ValueError("Candidate frame rate and width must be positive and finite")
    per = moving_candidates(per, fps, spatial_scale)
    anchors = load(a.anchors)["anchors"] if a.anchors else []
    for an in anchors:  # anchors enter as candidates with cost -4
        per[an["frame"]].append((an["x"], an["y"], -4.0, 1.0))

    MISS, START, MAXMISS, K_PER, K_MISS = 2.2, 4.0, 24, 6, 120
    # state arrays: x, y, vx, vy, lx, ly (last observed), miss, cost, alive(flag pos known)
    st = dict(x=np.zeros(1), y=np.zeros(1), vx=np.zeros(1), vy=np.zeros(1), lx=np.zeros(1),
              ly=np.zeros(1), m=np.zeros(1), cost=np.zeros(1), live=np.zeros(1, bool), newv=np.zeros(1, bool))
    back_parent, back_obs = [], []
    for t in range(n):
        cs = per[t]
        cx = np.array([c[0] for c in cs]); cy = np.array([c[1] for c in cs])
        cc = np.array([c[2] for c in cs])
        S = len(st["x"])
        live = st["live"]
        # predictions
        px = st["x"] + st["vx"]; py = st["y"] + st["vy"]
        new = {k: [] for k in ("x", "y", "vx", "vy", "lx", "ly", "m", "cost", "live", "newv")}
        parents, obs = [], []

        def push(pi, ci, x, y, vx, vy, lx, ly, m, cost, lv, nv):
            new["x"].append(x); new["y"].append(y); new["vx"].append(vx); new["vy"].append(vy)
            new["lx"].append(lx); new["ly"].append(ly); new["m"].append(m); new["cost"].append(cost)
            new["live"].append(lv); new["newv"].append(nv); parents.append(pi); obs.append(ci)

        if len(cs):
            dist = np.hypot(px[:, None] - cx[None, :], py[:, None] - cy[None, :])
            gate = (45 + 22 * st["m"][:, None]) * a.scale
            tc = st["cost"][:, None] + 0.06 * dist / a.scale + np.where(dist > gate, 60.0, 0.0) + cc[None, :]
            tc = np.where(live[:, None], tc, np.inf)
            # start a fresh track from the best dead state
            dead = np.where(~live)[0]
            for j in range(len(cs)):
                col = tc[:, j]
                order = np.argsort(col)[:K_PER]
                for pi in order:
                    if not np.isfinite(col[pi]):
                        break
                    gap = st["m"][pi] + 1
                    mvx = (cx[j] - st["lx"][pi]) / gap; mvy = (cy[j] - st["ly"][pi]) / gap
                    if st["newv"][pi]:
                        vx, vy = mvx, mvy
                    else:
                        vx = 0.7 * mvx + 0.3 * st["vx"][pi]; vy = 0.7 * mvy + 0.3 * st["vy"][pi]
                    push(pi, j, cx[j], cy[j], vx, vy, cx[j], cy[j], 0, col[pi], True, False)
                if len(dead):
                    pi = dead[np.argmin(st["cost"][dead])]
                    push(pi, j, cx[j], cy[j], 0.0, 0.0, cx[j], cy[j], 0, st["cost"][pi] + START + cc[j],
                         True, True)
        # missed frame for live states
        li = np.where(live)[0]
        li = li[np.argsort(st["cost"][li])][:K_MISS]
        for pi in li:
            m = st["m"][pi] + 1
            if m > MAXMISS:
                push(pi, -1, 0, 0, 0, 0, 0, 0, 0, st["cost"][pi] + MISS, False, True)
            else:
                push(pi, -1, px[pi], py[pi], st["vx"][pi], st["vy"][pi], st["lx"][pi], st["ly"][pi], m,
                     st["cost"][pi] + MISS, True, st["newv"][pi])
        # dead state continues
        dead = np.where(~live)[0]
        if len(dead):
            pi = dead[np.argmin(st["cost"][dead])]
            push(pi, -1, 0, 0, 0, 0, 0, 0, 0, st["cost"][pi] + MISS, False, True)
        st = {k: np.array(v) for k, v in new.items()}
        st["live"] = st["live"].astype(bool); st["newv"] = st["newv"].astype(bool)
        # keep the beam bounded
        if len(st["cost"]) > 600:
            keep = np.argsort(st["cost"])[:600]
            st = {k: v[keep] for k, v in st.items()}
            parents = list(np.array(parents)[keep]); obs = list(np.array(obs)[keep])
        back_parent.append(np.array(parents)); back_obs.append(np.array(obs))
        if t % 120 == 0:
            print(f"frame {t}: beam {len(st['cost'])} best {st['cost'].min():.1f}")

    # backtrack
    i = int(np.argmin(st["cost"]))
    path = [None] * n
    for t in range(n - 1, -1, -1):
        j = back_obs[t][i]
        path[t] = int(j)
        i = back_parent[t][i]
    out = []
    for t in range(n):
        j = path[t]
        if j >= 0:
            c = per[t][j]
            out.append([round(float(c[0]), 2), round(float(c[1]), 2), round(float(c[3]), 3)])
        else:
            out.append(None)
    save(a.out, {"frames": n, "track": out})
    print(f"observed in {sum(o is not None for o in out)} of {n} frames")


# ---------------------------------------------------------------- smoothing
def robust_fit(t, x, y, fixed, rounds=4, thr=18.0):
    keep = np.ones(len(t), bool)
    for _ in range(rounds):
        if keep.sum() < 5:
            break
        tk = t[keep]
        s = keep.sum() * 4.0
        try:
            sx = UnivariateSpline(tk, x[keep], k=3, s=s)
            sy = UnivariateSpline(tk, y[keep], k=3, s=s)
        except Exception:
            break
        res = np.hypot(sx(t) - x, sy(t) - y)
        new_keep = (res <= thr) | fixed
        if (new_keep == keep).all():
            break
        keep = new_keep
    return keep


def cmd_smooth(a):
    raw = load(a.raw)
    n = raw["frames"]
    tr = raw["track"]
    strikes = sorted(s["frame"] for s in load(a.strikes)["strikes"])
    anchors = {an["frame"] for an in (load(a.anchors)["anchors"] if a.anchors else [])}
    obs = np.array([i for i in range(n) if tr[i] is not None])
    if len(obs) == 0:
        raise SystemExit("empty track")
    start = min(strikes[0], obs[0]) if strikes else obs[0]
    end = obs[-1] if not a.end else a.end
    bounds = [start] + [s for s in strikes if start < s < end] + [end]
    X = np.full(n, np.nan); Y = np.full(n, np.nan)
    for s, e in zip(bounds[:-1], bounds[1:]):
        idx = np.array([i for i in range(s, e + 1) if tr[i] is not None])
        if len(idx) < 2:
            continue
        x = np.array([tr[i][0] for i in idx]); y = np.array([tr[i][1] for i in idx])
        fixed = np.array([i in anchors for i in idx])
        keep = robust_fit(idx.astype(float), x, y, fixed)
        ti, xi, yi = idx[keep], x[keep], y[keep]
        if len(ti) < 2:
            continue
        span = np.arange(max(s, ti[0]), min(e, ti[-1]) + 1)
        px = PchipInterpolator(ti, xi)(span); py = PchipInterpolator(ti, yi)(span)
        for t0, t1 in zip(ti[:-1], ti[1:]):  # leave long gaps (ball out of view) empty
            if t1 - t0 > a.max_gap:
                px[(span > t0) & (span < t1)] = np.nan; py[(span > t0) & (span < t1)] = np.nan
        X[span] = px; Y[span] = py
        # reach the strike frames at both ends: extend the flight by up to 3 frames at its own velocity
        if len(ti) >= 2:
            for edge, (ta, tb) in ((s, (ti[1], ti[0])), (e, (ti[-2], ti[-1]))):
                gap = abs(edge - tb)
                if 0 < gap <= 3:
                    vx = (X[tb] - X[ta]) / (tb - ta); vy = (Y[tb] - Y[ta]) / (tb - ta)
                    for g in range(1, gap + 1):
                        f = tb + g * int(np.sign(edge - tb))
                        X[f] = X[tb] + vx * (f - tb); Y[f] = Y[tb] + vy * (f - tb)
        print(f"segment {s}-{e}: {len(idx)} obs, dropped {int((~keep).sum())}")
    ok = ~np.isnan(X)
    # Gaussian 1.2 frames inside each continuous run, never across a strike
    out = [None] * n
    cuts = set(strikes)
    runs, cur = [], []
    for i in range(n):
        if ok[i] and not (i in cuts and cur):
            cur.append(i)
        else:
            if cur:
                runs.append(cur)
            cur = [i] if ok[i] else []
    if cur:
        runs.append(cur)
    for r in runs:
        r = np.array(r)
        gx = gaussian_filter1d(X[r], a.sigma, mode="nearest") if len(r) > 3 else X[r]
        gy = gaussian_filter1d(Y[r], a.sigma, mode="nearest") if len(r) > 3 else Y[r]
        for k, i in enumerate(r):
            out[i] = [round(float(gx[k]), 1), round(float(gy[k]), 1)]
    save(a.out, {"frames": n, "start": int(start), "end": int(end), "ball": out})
    print(f"smoothed track covers {sum(o is not None for o in out)} frames ({start}-{end})")


# ---------------------------------------------------------------- check
def cmd_check(a):
    b = load(a.ball)
    key = "ball" if "ball" in b else "track"
    tr = b[key]
    last, run = None, 0
    for i in range(0, len(tr), 6):
        p = tr[i]
        s = "-" if p is None else f"({p[0]:.0f},{p[1]:.0f})"
        print(f"{i:5d} {s}")
    for i in range(len(tr)):
        p = tr[i]
        q = None if p is None else (round(p[0]), round(p[1]))
        run = run + 1 if (q is not None and q == last) else 0
        if run == 9:
            print(f"!! stuck: frames {i - 9}-{i} at {q}")
        last = q
    fr = read_frame(a.video, a.frame)
    pts = [(i, p) for i, p in enumerate(tr) if p is not None]
    for (i0, p0), (i1, p1) in zip(pts[:-1], pts[1:]):
        if i1 - i0 > 1:
            continue
        hue = int(120 * i0 / max(len(tr), 1))
        col = cv2.cvtColor(np.uint8([[[hue, 255, 255]]]), cv2.COLOR_HSV2BGR)[0, 0].tolist()
        cv2.line(fr, (int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1])), col, 2, cv2.LINE_AA)
    for i, p in pts[::30]:
        cv2.putText(fr, str(i), (int(p[0]) + 4, int(p[1]) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    (255, 255, 255), 1)
    cv2.imwrite(a.out, fr)
    print("->", a.out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("profile"); p.add_argument("video"); p.add_argument("--known", required=True)
    p.add_argument("--chan", default="gray", choices=["gray", "yellow"])
    c = sub.add_parser("cands"); c.add_argument("video"); c.add_argument("bg"); c.add_argument("out")
    c.add_argument("--rim", required=True); c.add_argument("--cref", type=float, default=40.0)
    c.add_argument("--court", help="court JSON in video pixels (default: court.json beside background)")
    c.add_argument("--h", default="5,45"); c.add_argument("--s", type=int, default=80)
    c.add_argument("--v", type=int, default=110); c.add_argument("--exclude", help='"x,y,w,h x,y,w,h"')
    c.add_argument("--chan", default="gray", choices=["gray", "yellow"])
    c.add_argument("--diff", type=int, default=0, help="also require this much change against the background")
    c.add_argument("--amin", type=int, default=6); c.add_argument("--amax", type=int, default=400)
    c.add_argument("--aspect", type=float, default=2.5); c.add_argument("--fill", type=float, default=0.45)
    s = sub.add_parser("solve"); s.add_argument("cands"); s.add_argument("out"); s.add_argument("--anchors")
    s.add_argument("--scale", type=float, default=1.0,
                   help="pixel distances per frame relative to 60 fps footage (2 for 30 fps)")
    m = sub.add_parser("smooth"); m.add_argument("raw"); m.add_argument("strikes"); m.add_argument("out")
    m.add_argument("--anchors"); m.add_argument("--end", type=int)
    m.add_argument("--sigma", type=float, default=1.2, help="Gaussian in frames (1.2 at 60 fps)")
    m.add_argument("--max-gap", type=int, default=12, help="longest gap (frames) bridged by interpolation")
    k = sub.add_parser("check"); k.add_argument("video"); k.add_argument("ball"); k.add_argument("out")
    k.add_argument("--frame", type=int, default=0)
    a = ap.parse_args()
    {"profile": cmd_profile, "cands": cmd_cands, "solve": cmd_solve, "smooth": cmd_smooth,
     "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    main()
