"""Write data.json for the page from prep.json and the report texts.

  finalize.py draft prep.json texts.json
        writes a texts.json skeleton: one plain-language line per strike built from the
        measured numbers, and empty "done well" / "work on" lists. Rewrite every line
        after reading the numbers; never ship the skeleton as the report.
  finalize.py build prep.json texts.json page/data.json --video page/rally.mp4 [--name "..."]

texts.json holds everything written by hand for one rally: title, headline, verdict,
the line shown under each strike, two or three "done well" and "work on" lines per
player (each with a measured number and an action), and the measurement limits.
"""
import argparse
import json
import subprocess

from common import FPS, load, save

TYPE_VI = {"serve": "giao bóng", "return": "trả giao", "third_drop": "cú thứ ba (drop)",
           "third_drive": "cú thứ ba (drive)", "volley": "vô-lê", "dink": "dink", "get": "cứu bóng",
           "drive": "drive", "rally": "bóng qua lại"}
DIR_VI = {"cross": "chéo sân", "line": "dọc biên", "middle": "vào giữa", None: ""}


def cmd_draft(a):
    prep = load(a.prep)
    lines = {}
    for s in prep["strikes"]:
        sp = "" if s["kmh"] is None else f", khoảng {s['kmh']:.0f} km/h"
        lines[str(s["n"])] = (f"{s['player']} {TYPE_VI[s['type']]} {DIR_VI[s['dir']]}{sp}; "
                              f"đứng cách lưới {s['d_net']:.1f} m.").replace("  ", " ")
    texts = {
        "title": "Rally analysis",
        "headline": "",
        "verdict": "",
        "strike_lines": lines,
        "players": {p["id"]: {"good": [], "work": []} for p in prep["players"]},
        "limits": "",
        "draft": True,
    }
    save(a.texts, texts, indent=1)
    print("draft ->", a.texts)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,nb_frames:format=duration", "-of", "json", path],
                         capture_output=True, text=True).stdout
    j = json.loads(out)
    st = j["streams"][0]
    return int(st["width"]), int(st["height"]), float(j["format"]["duration"])


def cmd_build(a):
    prep = load(a.prep)
    texts = load(a.texts)
    if texts.get("draft"):
        raise SystemExit("texts.json is still the draft skeleton; write the report texts first")
    w, h, dur = probe(a.video)
    for p in prep["players"]:
        t = texts["players"][p["id"]]
        p["good"], p["work"] = t["good"], t["work"]
    for s in prep["strikes"]:
        s["line"] = texts["strike_lines"].get(str(s["n"]), "")
    data = {
        # width/height are the analysis frame size: every pixel coordinate in the data uses it
        "meta": {"name": a.name or texts["title"], "fps": FPS, "width": prep["court"]["img_w"],
                 "height": prep["court"]["img_h"], "video_size": [w, h],
                 "duration": round(dur, 3), "frames": prep["range"]["frames"], "endcard": 5.0,
                 "cover": texts.get("cover")},
        "report": {"title": texts["title"], "headline": texts["headline"], "verdict": texts["verdict"],
                   "limits": texts["limits"], "sample": prep["sample"], "advice": texts.get("advice", ""),
                   "intro": texts.get("intro", "")},
        **{k: prep[k] for k in ("court", "range", "strikes", "bounces", "players", "series")},
    }
    save(a.out, data)
    print(f"data.json -> {a.out} ({len(json.dumps(data)) / 1e6:.2f} MB), video {w}x{h} {dur:.2f}s")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft"); d.add_argument("prep"); d.add_argument("texts")
    b = sub.add_parser("build"); b.add_argument("prep"); b.add_argument("texts"); b.add_argument("out")
    b.add_argument("--video", required=True); b.add_argument("--name")
    a = ap.parse_args()
    {"draft": cmd_draft, "build": cmd_build}[a.cmd](a)


if __name__ == "__main__":
    main()
