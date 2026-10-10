"""Crop strips around candidate strike frames for visual verification.
usage: strike_tiles.py nat.mp4 ball_raw.json pose.npz out_dir f1,f2,...
Each output image: 7 crops (frames f-3..f+3) of 420x420 px around the ball (or the
event centre), with the ball track dot and the 4 skeletons drawn thin, labelled."""
import sys, os, json
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import read_frames

video, ballp, posep, out = sys.argv[1:5]
frames = [int(x) for x in sys.argv[5].split(',')]
tr = json.load(open(ballp)); tr = tr.get('track') or tr.get('ball')
lm = np.load(posep)['lm'] if os.path.exists(posep) else None
COLS = [(61, 122, 255), (87, 255, 156), (210, 95, 255), (255, 227, 77)]
EDGES = [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24), (23, 25), (25, 27), (24, 26), (26, 28)]
need = set()
for f in frames:
    need.update(range(f - 3, f + 4))
cache = {}
for i, fr in read_frames(video):
    if i in need:
        cache[i] = fr
    if i > max(need):
        break
os.makedirs(out, exist_ok=True)

def ball_near(f):
    for d in range(0, 8):
        for g in (f - d, f + d):
            if 0 <= g < len(tr) and tr[g] is not None:
                return tr[g][:2]
    return None

for f in frames:
    c = ball_near(f)
    if c is None:
        c = (960, 450)
    cx, cy = int(c[0]), int(c[1])
    tiles = []
    for g in range(f - 3, f + 4):
        fr = cache.get(g)
        if fr is None:
            continue
        im = fr.copy()
        if lm is not None and g < lm.shape[1]:
            for p in range(lm.shape[0]):
                for a, b in EDGES:
                    pa, pb = lm[p, g, a], lm[p, g, b]
                    cv2.line(im, (int(pa[0]), int(pa[1])), (int(pb[0]), int(pb[1])), COLS[p], 1, cv2.LINE_AA)
                hp = lm[p, g, [23, 24], :2].mean(0)
                cv2.putText(im, f"P{p + 1}", (int(hp[0]) + 8, int(hp[1])), 0, 0.7, COLS[p], 2)
        if 0 <= g < len(tr) and tr[g] is not None:
            cv2.circle(im, (int(tr[g][0]), int(tr[g][1])), 9, (0, 0, 255), 1)
        x0 = int(np.clip(cx - 210, 0, im.shape[1] - 420)); y0 = int(np.clip(cy - 210, 0, im.shape[0] - 420))
        crop = im[y0:y0 + 420, x0:x0 + 420].copy()
        cv2.putText(crop, str(g), (6, 26), 0, 0.8, (0, 255, 255) if g == f else (255, 255, 255), 2)
        tiles.append(crop)
    cv2.imwrite(os.path.join(out, f"ev_{f:04d}.jpg"), np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 88])
print('wrote', len(frames), 'strips to', out)
