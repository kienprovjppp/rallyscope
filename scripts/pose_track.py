"""Four players tracked frame by frame, each in their own crop.

  pose_track.py track work60.mp4 court.json pose.npz --seeds "x,y x,y x,y x,y" --model pose_landmarker_heavy.task
  pose_track.py check work60.mp4 pose.npz out.png [--every 45]

Seeds are the hip centres on frame 0 in the order P1 near right, P2 near left,
P3 far left, P4 far right. Crop side = 2.4 x the player's pixel height, where
the height comes from perspective: h = kh x (hip y - horizon y), kh = 0.42 for
the reference camera (measure it on frame 0 for another camera). All four players
advance together so that no two of them can take the same body.
"""
import argparse
import multiprocessing as mproc

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d

from common import court_dims, frame_count, load, project, read_frames

EDGES = [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24),
         (23, 25), (25, 27), (24, 26), (26, 28), (27, 29), (29, 31), (27, 31), (28, 30), (30, 32), (28, 32)]
COLS = [(61, 122, 255), (87, 255, 156), (210, 95, 255), (255, 227, 77)]  # BGR of P1..P4


def worker(model, q_in, q_out):
    """One PoseLandmarker per process; answers crops with every pose it finds."""
    import mediapipe as mp
    opts = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=model),
        running_mode=mp.tasks.vision.RunningMode.IMAGE, num_poses=3,
        min_pose_detection_confidence=0.3, min_pose_presence_confidence=0.3)
    det = mp.tasks.vision.PoseLandmarker.create_from_options(opts)
    while True:
        job = q_in.get()
        if job is None:
            break
        pid, crop = job
        res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=crop))
        poses = []
        for k, pl in enumerate(res.pose_landmarks):
            poses.append((np.array([[p.x, p.y, p.visibility] for p in pl], np.float32),
                          np.array([[p.x, p.y, p.z] for p in res.pose_world_landmarks[k]], np.float32)))
        q_out.put((pid, poses))
    det.close()


def shirt(fr, pts):
    """Torso colour class from the quad shoulders-hips: 'red', 'white', 'blue',
    'other', or None when the torso is too small or off-frame."""
    q = pts[[11, 12, 24, 23], :2].astype(np.int32)
    if np.isnan(pts[[11, 12, 23, 24], :2]).any():
        return None
    m = np.zeros(fr.shape[:2], np.uint8)
    cv2.fillConvexPoly(m, cv2.convexHull(q), 255)
    m = cv2.erode(m, np.ones((5, 5), np.uint8))
    if cv2.countNonZero(m) < 80:
        return None
    hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)[m > 0].astype(np.float32)
    hh, ss, vv = hsv[:, 0], hsv[:, 1], hsv[:, 2]
    frac = {"red": np.mean(((hh < 10) | (hh > 170)) & (ss > 90) & (vv > 70)),
            "white": np.mean((ss < 60) & (vv > 150)),
            "blue": np.mean((hh > 95) & (hh < 130) & (ss > 90) & (vv > 60))}
    best = max(frac, key=frac.get)
    return best if frac[best] > 0.3 else "other"


def make_crop(fr, pred, h, miss):
    fh, fw = fr.shape[:2]
    side = h * 2.4 * (1.15 ** min(miss, 2))  # bigger crops make far players too small to detect
    s = int(round(side))
    x0, y0 = int(round(pred[0] - side / 2)), int(round(pred[1] - side * 0.55))
    crop = np.zeros((s, s, 3), np.uint8)
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(fw, x0 + s), min(fh, y0 + s)
    if sx1 > sx0 and sy1 > sy0:
        crop[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = fr[sy0:sy1, sx0:sx1]
    crop = cv2.resize(crop, (768, 768), interpolation=cv2.INTER_CUBIC if s < 768 else cv2.INTER_AREA)
    return cv2.cvtColor(crop, cv2.COLOR_BGR2RGB), x0, y0, s


def track_all(video, seeds, horizon, model, kh, n, jobs, H=None, net_y=None, margin=0.5, scan=None,
              use_kit=True):
    """All players advance together, one frame at a time. Each player's crop may
    hold two poses; poses are assigned jointly so that no two players can take
    the same body (the pose closest to its own prediction wins). With a court
    homography, a pose only counts for a player if its feet stand on that
    player's side of the net (P1, P2 near; P3, P4 far) within `margin` metres."""
    P = len(seeds)
    ctx = mproc.get_context("spawn")
    q_in, q_out = ctx.Queue(), ctx.Queue()
    procs = [ctx.Process(target=worker, args=(model, q_in, q_out), daemon=True) for _ in range(jobs)]
    for pr in procs:
        pr.start()
    L = np.full((P, n, 33, 3), np.nan, np.float32)
    Wd = np.full((P, n, 33, 3), np.nan, np.float32)
    kit = [None] * P  # shirt colour of each player, learnt on the first frames
    Hh = np.zeros((P, n), np.float32)
    c = np.array(seeds, np.float64)
    v = np.zeros((P, 2))
    miss = np.zeros(P, int)
    for i, fr in read_frames(video):
        if i >= n:
            break
        pred = c + v
        h = np.maximum(40.0, kh * (pred[:, 1] - horizon))
        Hh[:, i] = h
        meta = {}
        for p in range(P):
            ctr = pred[p].copy()
            hp = h[p]
            if miss[p] > 3 and scan is not None:
                # a lost player is searched for on its own side: normal-size crops visit a
                # grid of spots there in turn, nearest to where the player was last seen first
                spots = scan[0 if p < 2 else 1]
                order = np.argsort(np.hypot(*(spots - c[p]).T))
                ctr = spots[order[(miss[p] - 4) % len(spots)]].copy()
                hp = max(40.0, kh * (ctr[1] - horizon))
            crop, x0, y0, s = make_crop(fr, ctr, hp, min(miss[p], 2))
            meta[p] = (x0, y0, s)
            q_in.put((p, crop))
        found = {}
        for _ in range(P):
            p, poses = q_out.get()
            x0, y0, s = meta[p]
            found[p] = [(np.c_[lm[:, 0] * s + x0, lm[:, 1] * s + y0, lm[:, 2]], wd) for lm, wd in poses]
        pairs = []
        for p in range(P):
            lost = miss[p] > 3
            for k, (pts, wd) in enumerate(found[p]):
                hip = pts[[23, 24], :2].mean(0)
                if use_kit and kit[p] is not None:
                    sc = shirt(fr, pts)
                    if sc is not None and sc != "other" and sc != kit[p]:
                        continue
                if H is not None:
                    # side of the net from the hip: feet ~ half a body height below it
                    hh_ = kh * (hip[1] - horizon)
                    gy = project(H, [hip[0], hip[1] + 0.5 * hh_])[1]
                    if (p < 2 and gy < net_y - margin) or (p >= 2 and gy > net_y + margin):
                        continue
                d = np.hypot(*(hip - pred[p])) / h[p]
                if d < 0.35 * (1 + 0.25 * min(miss[p], 4)):
                    pairs.append((d, p, k, hip))
                elif lost:  # a lost player takes any free body on its side with its shirt
                    pairs.append((1.0 + d, p, k, hip))
        pairs.sort(key=lambda t: t[0])
        taken, done = [], set()
        J = [11, 12, 23, 24, 25, 26, 27, 28]
        for d, p, k, hip in pairs:
            pts, wd = found[p][k]
            if p in done:
                continue
            # same body = the whole skeleton lies on an assigned one, not just the hips
            if any(np.nanmean(np.hypot(*(pts[J, :2] - t[J, :2]).T)) < 0.12 * h[p] for t in taken):
                continue
            L[p, i], Wd[p, i] = pts, wd
            if use_kit and i < 10 and kit[p] is None:
                sc = shirt(fr, pts)
                kit[p] = sc if sc not in (None, "other") else None
            v[p] = 0.5 * (hip - c[p]) / (miss[p] + 1) + 0.5 * v[p] if miss[p] <= 3 else np.zeros(2)
            c[p] = hip
            miss[p] = 0
            taken.append(pts)
            done.add(p)
        for p in range(P):
            if p not in done:
                miss[p] += 1
                c[p] = pred[p] if miss[p] <= 2 else c[p]  # hold the last place after two frames
                v[p] = v[p] * 0.5 if miss[p] <= 2 else np.zeros(2)
        if i == 10:
            print("shirt colours: " + ", ".join(f"P{p + 1}={kit[p]}" for p in range(P)), flush=True)
        if i % 60 == 0:
            print(f"frame {i}: " + "  ".join(f"P{p + 1}=({c[p][0]:.0f},{c[p][1]:.0f}) h={h[p]:.0f} miss={miss[p]}"
                                              for p in range(P)), flush=True)
    for _ in procs:
        q_in.put(None)
    for pr in procs:
        pr.join(timeout=10)
    return L, Wd, Hh


def fill_smooth(A, sigma=1.6):
    """Linear gap fill then Gaussian along time, per coordinate."""
    A = A.copy()
    n = A.shape[0]
    t = np.arange(n)
    flat = A.reshape(n, -1)
    for j in range(flat.shape[1]):
        col = flat[:, j]
        ok = ~np.isnan(col)
        if ok.sum() == 0:
            continue
        col[~ok] = np.interp(t[~ok], t[ok], col[ok])
        flat[:, j] = gaussian_filter1d(col, sigma, mode="nearest")
    return flat.reshape(A.shape)


def cmd_track(a):
    court = load(a.court)
    seeds = [[float(v) for v in p.split(",")] for p in a.seeds.split()]
    n = frame_count(a.video)
    _, L, _ = court_dims(court["kind"])
    Hm = np.array(court["H"])
    # search spots (hip positions in the image) for lost players: 3 x 3 grid on each side
    Hinv = np.linalg.inv(Hm)
    W_, _, K_ = court_dims(court["kind"])
    hz = court["horizon_y"]
    scan = []
    for ys in ((L / 2 + K_ + 0.4, L / 2 + K_ + 2.2, L - 0.6), (L / 2 - K_ - 0.4, L / 2 - K_ - 2.2, 0.6)):
        spots = []
        for cy in ys:
            for cx in (0.2 * W_, 0.5 * W_, 0.8 * W_):
                fx, fy = project(Hinv, [cx, cy])
                spots.append([fx, (fy + 0.5 * a.kh * hz) / (1 + 0.5 * a.kh)])
        scan.append(np.array(spots))
    raw, world, hh = track_all(a.video, seeds, hz, a.model, a.kh, n, a.jobs,
                               H=Hm, net_y=L / 2, scan=scan)
    P = len(seeds)
    ok = ~np.isnan(raw[..., 0, 0])
    lm = np.stack([fill_smooth(raw[p], a.sigma) for p in range(P)])
    wd = np.stack([fill_smooth(world[p], a.sigma) for p in range(P)])
    np.savez_compressed(a.out, lm=lm, world=wd, ok=ok, h=hh, raw=raw, world_raw=world)
    for p in range(P):
        print(f"P{p + 1}: detected in {ok[p].sum()}/{n} frames ({100 * ok[p].mean():.0f}%)")
    hips = lm[:, :, [23, 24], :2].mean(2)
    for p in range(P):
        for q in range(p + 1, P):
            d = np.hypot(*(hips[p] - hips[q]).T)
            close = d < 0.15 * hh[p].clip(40)
            if close.sum() > 5:
                print(f"!! P{p + 1} and P{q + 1} share a body in {close.sum()} frames, e.g. {np.where(close)[0][:8]}")


def drop_outliers(raw, hh, thr=0.6, win=5):
    """Drop single detections whose hips jump away from their neighbours (a second
    pose found on someone else's body)."""
    P, n = raw.shape[:2]
    hips = np.nanmean(raw[:, :, [23, 24], :2], axis=2)
    dropped = 0
    # two players on one body: the one that strays from its own path loses the frame
    for i in range(n):
        for p in range(P):
            for q in range(p + 1, P):
                if np.isnan(hips[p, i, 0]) or np.isnan(hips[q, i, 0]):
                    continue
                if np.hypot(*(hips[p, i] - hips[q, i])) > 0.3 * max(hh[p, i], 40):
                    continue
                dev = []
                for r in (p, q):
                    nb = [j for j in range(max(0, i - 15), min(n, i + 16)) if abs(j - i) > 0 and not np.isnan(hips[r, j, 0])
                          and all(np.isnan(hips[o, j, 0]) or np.hypot(*(hips[r, j] - hips[o, j])) > 0.3 * max(hh[r, j], 40)
                                  for o in range(P) if o != r)]
                    dev.append(np.hypot(*(hips[r, i] - np.median(hips[r, nb], axis=0))) if nb else 0.0)
                loser = p if dev[0] > dev[1] else q
                raw[loser, i] = np.nan
                hips[loser, i] = np.nan
                dropped += 1
    # short islands inside long gaps must sit on the line between the detections around them
    for p in range(P):
        ok = ~np.isnan(hips[p, :, 0])
        runs, st = [], None
        for i in range(n + 1):
            if i < n and ok[i] and st is None:
                st = i
            if (i == n or not ok[i]) and st is not None:
                runs.append((st, i - 1)); st = None
        for k, (a, b) in enumerate(runs):
            if b - a + 1 > 3:
                continue
            gap_b = a - runs[k - 1][1] - 1 if k > 0 else n
            gap_a = runs[k + 1][0] - b - 1 if k + 1 < len(runs) else n
            if gap_b < 4 and gap_a < 4:
                continue
            # anchors: nearest long runs on each side
            left = next((r for r in reversed(runs[:k]) if r[1] - r[0] + 1 > 3), None)
            right = next((r for r in runs[k + 1:] if r[1] - r[0] + 1 > 3), None)
            if left is None or right is None:
                continue
            for i in range(a, b + 1):
                w = (i - left[1]) / (right[0] - left[1])
                exp = hips[p, left[1]] * (1 - w) + hips[p, right[0]] * w
                if np.hypot(*(hips[p, i] - exp)) > 0.5 * max(hh[p, i], 40):
                    raw[p, i] = np.nan; hips[p, i] = np.nan; dropped += 1
    for p in range(P):
        for i in range(n):
            if np.isnan(hips[p, i, 0]):
                continue
            nb = [j for j in range(max(0, i - win), min(n, i + win + 1)) if j != i and not np.isnan(hips[p, j, 0])]
            if len(nb) < 2:
                continue
            med = np.median(hips[p, nb], axis=0)
            if np.hypot(*(hips[p, i] - med)) > thr * max(hh[p, i], 40):
                raw[p, i] = np.nan
                dropped += 1
    return dropped


def cmd_refine(a):
    """Second pass over the gaps: each missing frame is searched again around the
    straight line between the hips before and after the gap, with both ends known."""
    import mediapipe as mp
    court = load(a.court)
    Hm = np.array(court["H"])
    _, L, _ = court_dims(court["kind"])
    hz = court["horizon_y"]
    d = dict(np.load(a.pose))
    raw, world, hh = d["raw"].copy(), d.get("world_raw", d["world"]).copy(), d["h"]
    P, n = raw.shape[:2]
    print(f"outliers dropped before refine: {drop_outliers(raw, hh)}")
    opts = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=a.model),
        running_mode=mp.tasks.vision.RunningMode.IMAGE, num_poses=3,
        min_pose_detection_confidence=0.2, min_pose_presence_confidence=0.2)
    det = mp.tasks.vision.PoseLandmarker.create_from_options(opts)
    hips = np.nanmean(raw[:, :, [23, 24], :2], axis=2)
    todo = {}
    for p in range(P):
        ok = ~np.isnan(hips[p, :, 0])
        idx = np.where(ok)[0]
        for i in range(n):
            if ok[i]:
                continue
            before, after = idx[idx < i], idx[idx > i]
            if len(before) == 0 or len(after) == 0:
                continue
            b, e = before[-1], after[0]
            w = (i - b) / (e - b)
            todo.setdefault(i, []).append((p, hips[p, b] * (1 - w) + hips[p, e] * w))
    found_n = 0
    kit = {0: "blue", 1: "blue", 2: "red", 3: "white"} if a.kits is None else dict(enumerate(a.kits.split(",")))
    for i, fr in read_frames(a.video):
        if i not in todo:
            continue
        for p, ctr in todo[i]:
            hpx = max(40.0, a.kh * (ctr[1] - hz))
            best = None
            for scale in (2.0, 2.6):
                s = int(round(hpx * scale))
                x0, y0 = int(round(ctr[0] - s / 2)), int(round(ctr[1] - s * 0.55))
                crop = np.zeros((s, s, 3), np.uint8)
                sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(fr.shape[1], x0 + s), min(fr.shape[0], y0 + s)
                crop[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = fr[sy0:sy1, sx0:sx1]
                crop = cv2.cvtColor(cv2.resize(crop, (768, 768)), cv2.COLOR_BGR2RGB)
                res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=crop))
                for k, pl in enumerate(res.pose_landmarks):
                    pts = np.array([[q.x * s + x0, q.y * s + y0, q.visibility] for q in pl], np.float32)
                    hip = pts[[23, 24], :2].mean(0)
                    dd = np.hypot(*(hip - ctr)) / hpx
                    if dd > a.radius:
                        continue
                    sc = shirt(fr, pts)
                    if sc not in (None, "other") and sc != kit[p]:
                        continue
                    gy = project(Hm, [hip[0], hip[1] + 0.5 * a.kh * (hip[1] - hz)])[1]
                    if (p < 2 and gy < L / 2 - 0.5) or (p >= 2 and gy > L / 2 + 0.5):
                        continue
                    J = [11, 12, 23, 24, 25, 26, 27, 28]
                    clash = False
                    for q in range(P):
                        if q != p and not np.isnan(raw[q, i, 0, 0]):
                            if np.nanmean(np.hypot(*(pts[J, :2] - raw[q, i, J, :2]).T)) < 0.15 * hpx:
                                clash = True
                    if clash:
                        continue
                    if best is None or dd < best[0]:
                        wd = np.array([[q.x, q.y, q.z] for q in res.pose_world_landmarks[k]], np.float32)
                        best = (dd, pts, wd)
                if best is not None:
                    break
            if best is not None:
                raw[p, i], world[p, i] = best[1], best[2]
                found_n += 1
        if i == max(todo):
            break
    det.close()
    print(f"refine filled {found_n} of {sum(len(v) for v in todo.values())} missing player-frames")
    print(f"outliers dropped after refine: {drop_outliers(raw, hh)}")
    ok = ~np.isnan(raw[..., 0, 0])
    lm = np.stack([fill_smooth(raw[p], a.sigma) for p in range(P)])
    wdx = world.copy()
    wdx[~ok] = np.nan
    wd = np.stack([fill_smooth(wdx[p], a.sigma) for p in range(P)])
    np.savez_compressed(a.out, lm=lm, world=wd, ok=ok, h=hh, raw=raw, world_raw=wdx)
    for p in range(P):
        print(f"P{p + 1}: detected in {ok[p].sum()}/{n} frames ({100 * ok[p].mean():.0f}%)")


def draw_skel(img, pts, col, th=2):
    for i, j in EDGES:
        p, q = pts[i], pts[j]
        if np.isnan(p[0]) or np.isnan(q[0]):
            continue
        cv2.line(img, (int(p[0]), int(p[1])), (int(q[0]), int(q[1])), col, th, cv2.LINE_AA)


def cmd_check(a):
    d = np.load(a.pose)
    lm = d["lm"]
    tiles = []
    for i, fr in read_frames(a.video, step=a.every):
        if i >= lm.shape[1]:
            break
        for p in range(lm.shape[0]):
            draw_skel(fr, lm[p, i], COLS[p % 4], 3)
            hp = lm[p, i, [23, 24], :2].mean(0)
            cv2.putText(fr, f"P{p + 1}", (int(hp[0]) + 10, int(hp[1])), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                        COLS[p % 4], 2)
        cv2.putText(fr, str(i), (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
        tiles.append(cv2.resize(fr, (640, int(640 * fr.shape[0] / fr.shape[1]))))
    cols = 3
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[r:r + cols]) for r in range(0, len(tiles), cols)]
    cv2.imwrite(a.out, np.vstack(rows))
    print("->", a.out, f"({len(tiles)} tiles)")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("track")
    t.add_argument("video"); t.add_argument("court"); t.add_argument("out")
    t.add_argument("--seeds", required=True); t.add_argument("--model", required=True)
    t.add_argument("--kh", type=float, default=0.42,
                   help="pixel height = kh x (hip y - horizon y); calibrate on the first frame")
    t.add_argument("--jobs", type=int, default=4)
    t.add_argument("--sigma", type=float, default=1.6, help="Gaussian smoothing in frames")
    r = sub.add_parser("refine")
    r.add_argument("video"); r.add_argument("court"); r.add_argument("pose"); r.add_argument("out")
    r.add_argument("--model", required=True); r.add_argument("--kh", type=float, default=0.42)
    r.add_argument("--sigma", type=float, default=1.6); r.add_argument("--radius", type=float, default=0.8)
    r.add_argument("--kits", help="shirt colour per player, e.g. blue,blue,red,white")
    c = sub.add_parser("check")
    c.add_argument("video"); c.add_argument("pose"); c.add_argument("out")
    c.add_argument("--every", type=int, default=45)
    a = ap.parse_args()
    {"track": cmd_track, "refine": cmd_refine, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    main()
