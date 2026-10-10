"""Union of audio peaks and ball direction changes, with the features needed to
decide strike / bounce / noise. usage: cand_events.py work_dir out.json"""
import sys, json
import numpy as np
W = sys.argv[1]
hits = json.load(open(f'{W}/audio_hits.json'))['hits']
tr = json.load(open(f'{W}/ball_raw.json'))['track']
pz = np.load(f'{W}/pose.npz'); lm, hh = pz['lm'], pz['h']
n = len(tr)
X = np.array([np.nan if p is None else p[0] for p in tr]); Y = np.array([np.nan if p is None else p[1] for p in tr])

def vel(i0, i1):
    idx = [i for i in range(i0, i1 + 1) if 0 <= i < n and not np.isnan(X[i])]
    if len(idx) < 2: return None
    t = np.array(idx); return np.array([np.polyfit(t, X[idx], 1)[0], np.polyfit(t, Y[idx], 1)[0]])

turns = []
for i in range(3, n - 3):
    a, b = vel(i - 4, i), vel(i, i + 4)
    if a is None or b is None: continue
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 2 or nb < 2: continue
    ang = np.degrees(np.arccos(np.clip(a @ b / na / nb, -1, 1)))
    if ang > 45: turns.append((i, ang))
grp = []
for t in turns:
    if grp and t[0] - grp[-1][-1][0] <= 3: grp[-1].append(t)
    else: grp.append([t])
turns = [max(g, key=lambda t: t[1]) for g in grp]

events = []
for h in hits:
    events.append({'frame': h['frame'], 'audio_ratio': h['ratio'], 'audio_energy': h['energy'], 'turn': None})
for f, ang in turns:
    ex = [e for e in events if abs(e['frame'] - f) <= 4]
    if ex: ex[0]['turn'] = round(ang); ex[0]['turn_frame'] = f
    else: events.append({'frame': f, 'audio_ratio': None, 'audio_energy': None, 'turn': round(ang), 'turn_frame': f})
events.sort(key=lambda e: e['frame'])

def ball_near(f, win=4):
    for d in range(win + 1):
        for g in (f - d, f + d):
            if 0 <= g < n and tr[g] is not None: return np.array(tr[g][:2]), g
    return None, None

for e in events:
    f = e['frame']
    b, g = ball_near(f)
    e['ball'] = None if b is None else [round(float(b[0])), round(float(b[1]))]
    if b is None or f >= lm.shape[1]:
        e['near'] = None; continue
    best = []
    for p in range(lm.shape[0]):
        L = lm[p, g]
        d = min(np.hypot(*(L[15, :2] - b)), np.hypot(*(L[16, :2] - b)), 1.3 * np.hypot(*(L[0, :2] - b)))
        best.append((d / max(hh[p, g], 40), p))
    best.sort()
    e['near'] = f"P{best[0][1] + 1}"; e['near_h'] = round(float(best[0][0]), 2)
    e['second'] = f"P{best[1][1] + 1}"; e['second_h'] = round(float(best[1][0]), 2)
json.dump(events, open(sys.argv[2], 'w'), indent=1)
for e in events:
    print(f"f{e['frame']:4d} audio={e['audio_ratio']} turn={e['turn']} ball={e['ball']} near={e.get('near')} {e.get('near_h')} 2nd={e.get('second')} {e.get('second_h')}")
print(len(events), 'events')
