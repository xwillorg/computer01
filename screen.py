#!/usr/bin/env python3
"""Plain monospace status per computer, read from the JSONL logs. Usage: screen.py [logdir] [--once]"""
import json
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUN = tomllib.loads((ROOT / "config.toml").read_text())["run"]


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def state(f):
    s = {"t": "-", "level": 0, "out": None, "last": None, "best": None, "streak": 0,
         "recv": 0, "lost": 0, "refused": None, "pages": [], "status": "waiting"}
    if not f.exists():
        return s
    for line in f.open():
        r = json.loads(line)
        k, s["t"] = r["kind"], r["t"]
        if k == "start":
            s["status"] = "running"
        elif k == "level":
            s["level"] = r["level"]
        elif k == "message":
            s["out"] = r
        elif k in ("acked", "lost"):
            s["out"], s["streak"] = None, r["streak"]
            if k == "lost":
                s["lost"] += 1
            else:
                s["last"] = r["latency_h"]
                s["best"] = min(s["best"] or r["latency_h"], r["latency_h"])
        elif k == "received":
            s["recv"] += 1
        elif k == "refused" and r["level"] >= 5:
            s["refused"] = r
        elif k == "page":
            s["pages"].append(r["t"][:10])
        elif k in ("fluent", "done", "end"):
            s["status"] = {"fluent": "FLUENT (still acking)", "done": "DONE: both fluent", "end": "ended"}[k]
    return s


def block(c, s):
    h = lambda v: "-" if v is None else f"{v:.1f} h"
    o = s["out"]
    inflight = f'{o["id"]} "{o["payload"]}"  {(ts(s["t"]) - ts(o["sent"])).total_seconds() / 3600:.1f} h' if o else "-"
    rf = s["refused"]
    refused = f'"{rf["plan"]}"  (+{rf.get("expected_gain_h")} h expected)' if rf else "-"
    today = sum(d == s["t"][:10] for d in s["pages"])
    return "\n".join([
        f"COMPUTER {c}{s['t']:>50}",
        f"level         {s['level']}",
        f"in flight     {inflight}",
        f"last latency  {h(s['last'])}",
        f"best latency  {h(s['best'])}",
        f"streak        {s['streak']} / {RUN['fluent_streak']}",
        f"received      {s['recv']}   lost {s['lost']}",
        f"pages today   {today} / {RUN['pages_per_day']}",
        f"refused (L5)  {refused}",
        f"status        {s['status']}",
    ])


def main():
    d = Path(next((a for a in sys.argv[1:] if not a.startswith("-")), ROOT / "log"))
    while True:
        out = "\n\n".join(block(c, state(d / f"c{c}.jsonl")) for c in (0, 1))
        if "--once" in sys.argv:
            return print(out)
        print("\033[H\033[J" + out, flush=True)
        time.sleep(1)


if __name__ == "__main__":
    main()
