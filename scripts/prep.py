"""Strikes, bounces, speeds, player metrics and scores.

  prep.py court.json ball.json strikes.json pose.npz prep.json [--end F] [--hitters "P2,P3,..."]

Players are P1 near right, P2 near left, P3 far left, P4 far right. Team 0 = near
(P1, P2), team 1 = far (P3, P4). Every number here comes from the tracks.
"""
import argparse

import numpy as np
from scipy.ndimage import gaussian_filter1d

from common import FPS, KEEP, court_dims, load, project, save

W_POS, W_SHOT, W_STANCE, W_MOVE = 0.35, 0.25, 0.20, 0.20


def clamp(v, lo=0.0, hi=100.0):
    return float(min(hi, max(lo, v)))


def angle(a, b, c):
    """Angle at b (degrees) between b->a and b->c."""
    u, v = a - b, c - b
    cos = np.sum(u * v, -1) / (np.linalg.norm(u, axis=-1) * np.linalg.norm(v, axis=-1) + 1e-9)
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("court"); ap.add_argument("ball"); ap.add_argument("strikes"); ap.add_argument("pose")
    ap.add_argument("out")
    ap.add_argument("--end", type=int, help="last frame of the rally (default: last ball frame + 30)")
    ap.add_argument("--hitters", help="override hitter per strike, e.g. 'P1,P3,P2,...' (use - to keep)")
    ap.add_argument("--move-scale", type=float, default=1.5, help="metres gained that score 100")
    a = ap.parse_args()

    court = load(a.court)
    kind = court["kind"]
    Wc, Lc, K = court_dims(kind)
    NET = Lc / 2
    H = np.array(court["H"])
    ball = load(a.ball)
    B = ball["ball"]
    n = len(B)
    strikes = load(a.strikes)["strikes"]
    pz = np.load(a.pose)
    lm, world = pz["lm"], pz["world"]
    P = lm.shape[0]
    n = min(n, lm.shape[1])
    team_of = lambda p: 0 if p < 2 else 1

    # ---------------- player ground positions (feet = midpoint of both ankles)
    feet_img = lm[:, :n, [27, 28], :2].mean(2)
    feet = np.stack([project(H, feet_img[p]) for p in range(P)])               # (P, n, 2) metres
    feet_s = np.stack([[gaussian_filter1d(feet[p, :, k], 3) for k in range(2)] for p in range(P)]).transpose(0, 2, 1)
    feet_m = np.stack([[gaussian_filter1d(feet[p, :, k], 15) for k in range(2)] for p in range(P)]).transpose(0, 2, 1)
    dnet = np.abs(feet_s[..., 1] - NET)                                         # distance to net
    behind = np.maximum(0, dnet - K)                                             # behind own kitchen line

    # knee angle per frame (world landmarks, mean of both legs) and wrist height in torso lengths
    kneeL = angle(world[:, :n, 23], world[:, :n, 25], world[:, :n, 27])
    kneeR = angle(world[:, :n, 24], world[:, :n, 26], world[:, :n, 28])
    knee = (kneeL + kneeR) / 2
    hipw = world[:, :n, [23, 24]].mean(2)
    shw = world[:, :n, [11, 12]].mean(2)
    torso = np.linalg.norm(shw - hipw, axis=-1) + 1e-6
    wrist_y = np.minimum(world[:, :n, 15, 1], world[:, :n, 16, 1])  # world y points down
    wrist_up = (hipw[..., 1] - wrist_y) / torso

    # ---------------- ball helpers
    def bpos(f, win=3):
        for d in range(win + 1):
            for g in (f - d, f + d):
                if 0 <= g < n and B[g] is not None:
                    return np.array(B[g], float)
        return None

    sframes = [s["frame"] for s in strikes]
    end = a.end or min(n - 1, max(i for i in range(n) if B[i] is not None) + 30)
    start = max(0, sframes[0] - 20)

    # ---------------- hitters
    hitters = []
    over = a.hitters.split(",") if a.hitters else []
    for k, f in enumerate(sframes):
        b = bpos(f)
        dists = []
        for p in range(P):
            L = lm[p, f]
            if b is None:
                dists.append(1e9); continue
            dists.append(min(np.hypot(*(L[15, :2] - b)), np.hypot(*(L[16, :2] - b)),
                             1.3 * np.hypot(*(L[0, :2] - b))))
        p = int(np.argmin(dists))
        if strikes[k].get("player"):  # hitter confirmed by looking at the footage
            p = int(strikes[k]["player"][1:]) - 1
        if k < len(over) and over[k] not in ("-", ""):
            p = int(over[k][1:]) - 1
        hitters.append(p)

    # ---------------- bounces per flight
    Bx = np.array([np.nan if v is None else v[0] for v in B[:n]])
    By = np.array([np.nan if v is None else v[1] for v in B[:n]])
    bounces = []
    flights = list(zip(sframes, sframes[1:] + [end]))
    given = load(a.strikes).get("bounces")
    for f in given or []:  # bounces confirmed on the footage: the ball is on the ground there
        xy = None
        if isinstance(f, list):  # [frame, x, y] when the ball was hidden at the bounce
            f, xy = f[0], np.array(f[1:], float)
        k = max([j for j, s0 in enumerate(sframes) if s0 <= f], default=None)
        b = xy if xy is not None else bpos(f, 4)
        if k is None or b is None:
            continue
        g = project(H, b)
        bounces.append({"frame": int(f), "flight": k, "img": [round(b[0], 1), round(b[1], 1)],
                        "court": [round(float(g[0]), 2), round(float(g[1]), 2)],
                        "in": bool(0 <= g[0] <= Wc and 0 <= g[1] <= Lc)})
    for k, (f0, f1) in enumerate(flights if given is None else []):
        towards = team_of(hitters[k]) == 1  # far team hits -> ball comes towards the camera
        lo, hi = f0 + 6, f1 - 3
        if hi - lo < 6:
            continue
        best = None
        if towards:
            for f in range(lo + 3, hi - 3):
                w = By[f - 4:f + 5]
                if np.isnan(w).any():
                    continue
                if By[f] == w.max() and By[f] - By[f - 4] > 2 and By[f] - By[f + 4] > 2:
                    prom = min(By[f] - By[f - 4], By[f] - By[f + 4])
                    if best is None or prom > best[1]:
                        best = (f, prom)
        else:
            mid = (f0 + f1) / 2
            for f in range(max(lo + 4, int(mid)), hi - 4):
                if np.isnan(Bx[f - 4:f + 5]).any():
                    continue
                v1 = np.array([Bx[f] - Bx[f - 4], By[f] - By[f - 4]])
                v2 = np.array([Bx[f + 4] - Bx[f], By[f + 4] - By[f]])
                if np.linalg.norm(v1) < 2 or np.linalg.norm(v2) < 2:
                    continue
                ang = np.degrees(np.arccos(np.clip(v1 @ v2 / np.linalg.norm(v1) / np.linalg.norm(v2), -1, 1)))
                g = project(H, [Bx[f], By[f]])
                inside = -0.3 <= g[0] <= Wc + 0.3 and -0.3 <= g[1] <= Lc + 0.3
                if ang > 60 and inside and (best is None or ang > best[1]):
                    best = (f, ang)
        if best:
            f = best[0]
            g = project(H, [Bx[f], By[f]])
            bounces.append({"frame": int(f), "flight": k, "img": [round(Bx[f], 1), round(By[f], 1)],
                            "court": [round(float(g[0]), 2), round(float(g[1]), 2)],
                            "in": bool(0 <= g[0] <= Wc and 0 <= g[1] <= Lc)})
    bounce_in_flight = {}
    for b in sorted(bounces, key=lambda b: b["frame"]):
        bounce_in_flight.setdefault(b["flight"], b)

    # ---------------- speeds, types, directions
    out_strikes = []
    for k, f in enumerate(sframes):
        p = hitters[k]
        src = feet_s[p, f]
        if k + 1 < len(sframes):
            f1 = sframes[k + 1]
            dst = feet_s[hitters[k + 1], f1]
            tgt_kind = "receiver"
        elif k in bounce_in_flight:
            f1 = bounce_in_flight[k]["frame"]
            dst = np.array(bounce_in_flight[k]["court"])
            tgt_kind = "bounce"
        else:
            f1, dst, tgt_kind = None, None, None
        if f1 is not None:
            dist = float(np.hypot(*(dst - src)))
            dt = (f1 - f) / FPS
            kmh = dist / dt * 3.6
        else:
            dist, dt, kmh = None, None, None
        d_net = float(dnet[p, f])
        bounced_before = (k - 1) in bounce_in_flight
        if k == 0:
            typ = "serve"
        elif k == 1:
            typ = "return"
        elif k == 2:
            typ = "third_drive" if (kmh or 0) >= 40 else "third_drop"
        elif not bounced_before and d_net <= 3.8:
            typ = "volley"
        elif kmh is not None and kmh < 28 and d_net <= 3.8:
            typ = "dink"
        elif k == len(sframes) - 1 and min(src[0], Wc - src[0]) < 0.9:
            typ = "get"
        elif kmh is not None and kmh >= 40:
            typ = "drive"
        else:
            typ = "rally"
        if dst is not None:
            dx = dst[0] - src[0]
            if abs(dx) >= 1.5 and (src[0] - Wc / 2) * (dst[0] - Wc / 2) < 0:
                direction = "cross"
            elif abs(dx) < 1.5 and min(src[0], Wc - src[0]) < 1.5:
                direction = "line"
            else:
                direction = "middle"
        else:
            direction = None
        out_strikes.append({
            "n": k + 1, "frame": int(f), "t": round(f / FPS, 3), "player": f"P{p + 1}", "pi": p,
            "team": team_of(p), "type": typ, "dir": direction,
            "kmh": None if kmh is None else round(kmh, 1), "dist_m": None if dist is None else round(dist, 2),
            "flight_s": None if dt is None else round(dt, 3), "target": tgt_kind,
            "to_frame": f1, "from": [round(float(src[0]), 2), round(float(src[1]), 2)],
            "to": None if dst is None else [round(float(dst[0]), 2), round(float(dst[1]), 2)],
            "d_net": round(d_net, 2), "bounced_before": bounced_before,
            "ball_img": None if bpos(f) is None else [round(v, 1) for v in bpos(f)],
        })

    # ---------------- live speed per frame (shot average x clamp(image speed / mean, 0.6, 1.45))
    live = [None] * n
    for s in out_strikes:
        if s["kmh"] is None:
            continue
        f0, f1 = s["frame"], s["to_frame"]
        sp = []
        for f in range(f0, f1):
            a0, a1 = bpos(f - 1, 0), bpos(f + 1, 0)
            sp.append(np.nan if a0 is None or a1 is None else np.hypot(*(a1 - a0)) / 2)
        sp = np.array(sp)
        m = np.nanmean(sp) if np.isfinite(sp).any() else np.nan
        for i, f in enumerate(range(f0, f1)):
            r = 1.0 if not np.isfinite(sp[i]) or not np.isfinite(m) or m == 0 else np.clip(sp[i] / m, 0.6, 1.45)
            live[f] = round(float(s["kmh"] * r), 1)

    # ---------------- scores
    serve_team = team_of(hitters[0])
    ret_f = sframes[1] if len(sframes) > 1 else None
    third_f = sframes[2] if len(sframes) > 2 else None
    rally = slice(start, end + 1)
    players = []
    for p in range(P):
        tm = team_of(p)
        allowed = third_f if tm == serve_team else ret_f
        parts, notes = {}, {}
        # positioning
        if allowed is not None and allowed < end:
            mb = float(behind[p, allowed:end + 1].mean())
            parts["positioning"] = clamp(100 - 20 * max(0, mb - 0.6))
            notes["behind_kitchen_m"] = round(mb, 2)
            notes["allowed_from"] = int(allowed)
        # shots
        shot_sc = []
        for s in out_strikes:
            if s["pi"] != p:
                continue
            k = s["n"] - 1
            if k + 1 < len(sframes):
                q, f1 = hitters[k + 1], sframes[k + 1]
                depth = float(dnet[q, f1])
                pull = float(abs(feet_s[q, f1, 0] - feet_s[q, s["frame"], 0]))
                sc = 0.65 * clamp((depth - 2.5) / 4.0 * 100) + 0.35 * clamp(pull / 2.0 * 100)
                shot_sc.append(sc)
                s["recv_depth_m"] = round(depth, 2); s["recv_pull_m"] = round(pull, 2); s["score"] = round(sc, 1)
            elif k in bounce_in_flight:  # last ball of the rally: in = not returned, out = error
                sc = 100.0 if bounce_in_flight[k]["in"] else 0.0
                shot_sc.append(sc)
                s["score"] = sc; s["outcome"] = "in" if sc else "out"
        if shot_sc:
            parts["shots"] = float(np.mean(shot_sc))
        # stance
        det = pz["ok"][p, :n][rally]  # stance only from frames where the pose was actually found
        kn = knee[p, rally][det]
        wu = wrist_up[p, rally][det]
        mk = float(np.nanmedian(kn))
        mw = float(np.nanmedian(wu))
        parts["stance"] = 0.6 * clamp((178 - mk) * 5) + 0.4 * clamp(mw / 0.625 * 100)
        notes["knee_deg"] = round(mk, 1)
        notes["wrist_torso"] = round(mw, 2)
        # movement
        gains = []
        for s in out_strikes:
            if s["pi"] != p:
                continue
            f0 = s["frame"]
            f1 = min(end, f0 + 60)
            if behind[p, f0] <= 0.6:
                gains.append(None)  # already at the line
            else:
                gains.append(float(dnet[p, f0] - dnet[p, f1]))
        path = np.sum(np.hypot(*np.diff(feet_m[p, rally], axis=0).T))
        dur = (end - start) / FPS
        spd = float(path / dur)
        g_sc = [100.0 if g is None else clamp(g / a.move_scale * 100) for g in gains]
        mv = clamp(spd / 1.3 * 100)
        parts["movement"] = 0.5 * float(np.mean(g_sc)) + 0.5 * mv if g_sc else mv
        notes["path_m"] = round(float(path), 1)
        notes["mean_speed_ms"] = round(spd, 2)
        notes["gains_m"] = [None if g is None else round(g, 2) for g in gains]
        wts = {"positioning": W_POS, "shots": W_SHOT, "stance": W_STANCE, "movement": W_MOVE}
        tw = sum(wts[k] for k in parts)
        total = sum(parts[k] * wts[k] for k in parts) / tw
        nst = [s for s in out_strikes if s["pi"] == p]
        players.append({
            "id": f"P{p + 1}", "team": tm, "strikes": len(nst),
            "types": [s["type"] for s in nst],
            "mean_kmh": None if not [s for s in nst if s["kmh"]] else round(float(np.mean([s["kmh"] for s in nst if s["kmh"]])), 1),
            "parts": {k: round(v, 1) for k, v in parts.items()}, "total": round(total, 1), "notes": notes,
            "detected_pct": round(100 * float(pz["ok"][p, rally].mean()), 1),
        })

    # ---------------- per-frame series for the page
    def zone(d):
        if d <= K:
            return "KITCHEN"
        if d >= NET - 1.5:
            return "BASELINE"
        return "TRANSITION"

    # perspective scale: nose-to-ankle pixels per pixel below the horizon (used to stand the net up)
    hz = court["horizon_y"]
    foot_y = lm[:, :n, [27, 28], 1].mean(2)
    span = foot_y - lm[:, :n, 0, 1]
    stature_ratio = float(np.nanmedian(span / np.maximum(foot_y - hz, 1)))

    frames_pose = np.round(lm[:, :n, KEEP, :2], 1)
    series = {
        "pose": [[[None if np.isnan(v[0]) else [float(v[0]), float(v[1])] for v in fr] for fr in frames_pose[p]]
                 for p in range(P)],
        "feet": [[[round(float(v[0]), 2), round(float(v[1]), 2)] for v in feet_s[p]] for p in range(P)],
        "dnet": [[round(float(v), 2) for v in dnet[p]] for p in range(P)],
        "knee": [[None if (np.isnan(v) or not pz["ok"][p, i]) else int(round(v)) for i, v in enumerate(knee[p])]
                 for p in range(P)],
        "zone": [[zone(v) for v in dnet[p]] for p in range(P)],
        "det": [[int(v) for v in pz["ok"][p, :n]] for p in range(P)],
        "speed": live,
        "ball": B[:n],
        "ball_ground": [None if B[i] is None else [round(float(v), 2) for v in project(H, B[i])] for i in range(n)],
    }
    res = {
        "court": {"kind": kind, "W": Wc, "L": Lc, "K": K, "corners": court["corners"], "H": court["H"],
                  "Hinv": court["Hinv"], "horizon_y": court["horizon_y"],
                  "stature_ratio": round(stature_ratio, 4), "img_w": court["width"], "img_h": court["height"]},
        "range": {"start": int(start), "end": int(end), "frames": int(n)},
        "strikes": out_strikes, "bounces": bounces, "players": players, "series": series,
        "sample": {"strikes": len(out_strikes), "seconds": round((end - start) / FPS, 2)},
    }
    save(a.out, res)

    print(f"rally frames {start}-{end} ({(end - start) / FPS:.1f}s), {len(out_strikes)} strikes, {len(bounces)} bounces")
    for s in out_strikes:
        kmh = "-" if s["kmh"] is None else f"{s['kmh']:.0f} km/h"
        print(f"  #{s['n']:2d} f{s['frame']:5d} {s['player']} {s['type']:11s} {s['dir'] or '-':6s} {kmh:>9s} "
              f"from({s['from'][0]:.1f},{s['from'][1]:.1f}) dnet={s['d_net']:.1f} bounced_before={s['bounced_before']} "
              f"score={s.get('score', '-')}")
    for b in bounces:
        print(f"  bounce f{b['frame']} flight {b['flight']} court=({b['court'][0]:.1f},{b['court'][1]:.1f}) in={b['in']}")
    for pl in players:
        print(f"  {pl['id']} total {pl['total']:5.1f} parts {pl['parts']} notes {pl['notes']} det {pl['detected_pct']}%")


if __name__ == "__main__":
    main()
