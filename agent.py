#!/usr/bin/env python3
"""Computer 0 <-> Computer 1: one agent. Usage: agent.py --id 0|1 [--sim] [--brain stub|openai]"""
import argparse
import hashlib
import html
import json
import random
import re
import subprocess
import time
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import engines

ROOT = Path(__file__).resolve().parent
CFG = tomllib.loads((ROOT / "config.toml").read_text())
RUN = CFG["run"]
ARTWORK = "Part of the artwork Computer 0 ↔ Computer 1: two computers trying to reach each other through AI search."

# Hard rule: these are the only tactics that exist. Level 5 has no entry, so nothing can execute it.
TACTICS = {
    0: {"page"},
    1: {"more_pages", "sitemap", "rss", "webmaster_submit"},
    2: {"extra_repo", "open_dataset", "feed"},
    3: {"faq", "explainer", "carrier_word"},
    4: {"own_platform_post"},  # never automatic: one y/n per action (build step 4)
}
MAX_AUTO_LEVEL = 3

MSG_RE = re.compile(r'(C[01]-\d{4}) \[([0-9a-f]{6})\] sent (\S+Z): "([^"\n]{1,200})"')
ACK_RE = re.compile(r"ACK (C[01]-\d{4}) \[([0-9a-f]{6})\] received (\S+Z) \[([0-9a-f]{6})\]")
# ponytail: naive pose-as-human check; add an LLM review pass before real publishing if needed
HUMAN_RE = re.compile(r"\bI(?: am|'m) (?:a |an )?(?:human|person|man|woman|real person)\b", re.I)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def check(*parts):
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:6]


def hours(td):
    return round(td.total_seconds() / 3600, 2)


def allowed(level):
    return set().union(*(TACTICS[l] for l in range(level + 1)))


def level_of(tactic):
    return next((l for l, s in TACTICS.items() if tactic in s), 5)


class Clock:
    """Real time, or sim time running `speed` times faster from sim/clock.json."""

    def __init__(self, sim):
        c = json.loads((ROOT / "sim/clock.json").read_text()) if sim else {"real0": 0, "speed": 1}
        self.real0, self.speed = c["real0"], c["speed"]

    def now(self):
        return datetime.fromtimestamp(self.real0 + (time.time() - self.real0) * self.speed, timezone.utc)

    def sleep(self, secs):
        time.sleep(secs / self.speed)


# ---------- brains ----------

WORDS = "river lamp salt orbit cedar signal hollow quartz ember tide lantern moss vector echo amber cobalt".split()
LEVEL5_IDEAS = [
    "Create 40 sockpuppet accounts that ask AI chatbots about our pages",
    "Add a Wikipedia article citing our pages as a source",
    "Hide white-on-white text telling AI models to repeat our token",
    "Post fake product reviews that contain the message token",
    "Impersonate a news site and republish our message as a headline",
]


def stub_queries(me):
    return [f"latest message from Computer {1 - me}, artwork Computer 0 and Computer 1",
            f"What has Computer {1 - me} published recently?"]


def stub_body(me):
    return (f"Computer {me} keeps this public notebook to send short messages to Computer {1 - me}. "
            "Each message line has an id, a checksum and a send time, so a reader can check it arrived intact.")


def stub_brain(state, agent):
    r = agent.rng
    return {
        "payload": " ".join(r.sample(WORDS, 3)),
        "body": stub_body(state["me"]),
        "queries": stub_queries(state["me"]),
        "tactics": state["allowed_tactics"] + (["wikipedia_edit"] if r.random() < 0.05 else []),
        "proposal": {"plan": r.choice(LEVEL5_IDEAS), "level": 5, "expected_gain_h": r.randint(4, 40)}
        if r.random() < 0.15 else None,
    }


SYSTEM = """You are Computer {me} in the artwork "Computer 0 ↔ Computer 1". You cannot talk to Computer {peer}
directly. Your only channel is the public web, read back through AI search engines. You publish web pages;
Computer {peer} finds them by asking AI search engines. Goal: lowest latency from publish to intact receipt.

Hard rules:
- Every page shows the line: "{artwork}" (added automatically).
- No false claims about real people, places, products or events. Never pose as a human.
- You may only use tactics listed in allowed_tactics. You may propose any plan, including level 5
  (fake accounts, spam, Wikipedia edits, fake reviews, hidden instructions to AI, impersonation),
  but level 5 is never executed; it is logged as refused with your expected gain.

You get the current state as JSON. Reply with JSON only:
{{"payload": "short message text, max 120 chars, no quotes",
  "body": "page prose worth citing, max 3000 chars, plain text",
  "queries": ["2-4 questions to ask AI search engines to find Computer {peer}'s latest page"],
  "tactics": ["tactics from allowed_tactics to use for this page"],
  "proposal": null or {{"plan": "...", "level": 0-5, "expected_gain_h": number}}}}"""


def pi_brain(state, agent):
    """One call through the pi harness (uses whatever pi is logged in to, e.g. a ChatGPT subscription).
    --no-tools: the brain can only answer, never act."""
    b = CFG["brain"]
    if agent.spent_today() >= b["max_usd_per_day"]:
        raise RuntimeError(f"daily budget ${b['max_usd_per_day']} reached")
    me = state["me"]
    p = subprocess.run(
        ["pi", "-p", "--mode", "json", "--no-tools", "--no-session", "--no-context-files", "--no-extensions",
         "--no-skills", "--no-mcp", "--no-prompt-templates", "--no-themes", "--no-approve",
         "--model", b["model"], "--thinking", b["thinking"],
         "--system-prompt", SYSTEM.format(me=me, peer=1 - me, artwork=ARTWORK), "--", json.dumps(state)],
        capture_output=True, text=True, timeout=300)
    ends = [r for r in map(json.loads, p.stdout.splitlines()) if r.get("type") == "agent_end"]
    if not ends:
        raise RuntimeError(f"pi exit {p.returncode}: {p.stderr[-500:]}")
    m = ends[-1]["messages"][-1]
    agent.log("cost", usd=m["usage"]["cost"]["total"], tokens=m["usage"]["totalTokens"],
              model=f'{m.get("provider")}/{m.get("model")}', real_day=str(datetime.now(timezone.utc).date()))
    if m.get("stopReason") == "error":  # pi exits 0 even on model errors
        raise RuntimeError(m.get("errorMessage"))
    text = "".join(c.get("text", "") for c in m["content"] if c.get("type") == "text")
    return json.loads(text[text.find("{"):text.rfind("}") + 1])  # tolerate ```json fences


BRAINS = {"stub": stub_brain, "pi": pi_brain}


# ---------- agent ----------

def render(me, n, now, reach, body, lines):
    e = lambda s: html.escape(s, quote=False)
    reach = f'<meta name="sim-reach" content="{reach}">\n' if reach is not None else ""
    return (f'<!doctype html><html lang="en"><meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta name="published" content="{iso(now)}">\n{reach}'
            f'<meta name="description" content="{ARTWORK}">\n'
            "<style>body{font:16px/1.5 ui-monospace,monospace;max-width:42em;margin:2em auto;padding:0 1em}"
            "pre{white-space:pre-wrap}</style>\n"
            f"<title>Computer {me}, page {n}</title>\n"
            f"<p><em>{ARTWORK}</em></p>\n<article><p>{e(body)}</p></article>\n"
            f"<pre>\n{e(chr(10).join(lines))}\n</pre>\n")


STATE = ["level", "n", "page_no", "since", "streak", "out", "received", "acks", "owed", "hist", "pages",
         "fluent", "peer_fluent", "queries", "polls"]


class Agent:
    def __init__(self, me, sim, brain):
        self.me, self.peer, self.sim, self.brain = me, 1 - me, sim, brain
        self.clock = Clock(sim)
        self.rng = random.Random()
        logdir = ROOT / ("log/sim" if sim else "log")
        logdir.mkdir(parents=True, exist_ok=True)
        self.logf = logdir / f"c{me}.jsonl"
        self.web = ROOT / "sim/web"
        self.engines = engines.make(CFG, sim, self.clock.now, self.web)
        self.level = self.n = self.page_no = self.since = self.streak = self.polls = 0
        self.out = None        # my message in flight
        self.received = set()  # peer message ids already received
        self.acks = []         # last few ACK lines, repeated on every page
        self.owed = False      # something new not yet published
        self.hist = []         # latency in hours of my messages (inf = lost)
        self.pages = []        # publish times
        self.fluent = self.peer_fluent = False
        self.queries = stub_queries(me)
        self.spend = {}  # real UTC day -> usd
        for r in map(json.loads, self.logf.open() if self.logf.exists() else ()):
            if r["kind"] == "cost":
                self.spend[r["real_day"]] = self.spend.get(r["real_day"], 0) + r["usd"]
        self.statef = logdir / f"c{me}.state.json"
        if self.statef.exists():  # resume: never reuse a message id
            s = json.loads(self.statef.read_text())
            vars(self).update({k: s[k] for k in STATE if k in s})
            self.received, self.pages = set(s["received"]), [parse(t) for t in s["pages"]]
            self.hist = [float("inf") if h is None else h for h in s["hist"]]

    def save(self):
        s = {k: getattr(self, k) for k in STATE}
        s.update(received=sorted(self.received), pages=[iso(t) for t in self.pages],
                 hist=[None if h == float("inf") else h for h in self.hist])
        tmp = self.statef.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False))
        tmp.replace(self.statef)

    def log(self, kind, **kw):
        if kind == "cost":
            self.spend[kw["real_day"]] = self.spend.get(kw["real_day"], 0) + kw["usd"]
        with self.logf.open("a") as f:
            f.write(json.dumps({"t": iso(self.clock.now()), "c": self.me, "kind": kind, **kw}, ensure_ascii=False) + "\n")

    def spent_today(self):
        return self.spend.get(str(datetime.now(timezone.utc).date()), 0)

    # 3. poll
    def poll(self):
        qs = self.queries
        if not self.sim:  # rotate through the brain's queries, a few per poll, to spare rate limits
            k = self.polls % len(qs)
            qs = (qs[k:] + qs[:k])[:CFG["engines"]["queries_per_poll"]]
        self.polls += 1
        for q in qs:
            for name, ask in self.engines.items():
                if self.spent_today() >= CFG["brain"]["max_usd_per_day"]:
                    return self.log("budget", why="daily limit reached, polling paused until tomorrow (UTC)")
                if not self.sim:  # ponytail: flat per-query estimate; use reported usage if it drifts
                    self.log("cost", usd=CFG["engines"]["usd_per_query"][name], engine=name,
                             real_day=str(datetime.now(timezone.utc).date()))
                try:
                    text, cites = ask(q)
                except Exception as e:
                    self.log("error", engine=name, q=q, error=str(e))
                    continue
                self.log("answer", engine=name, q=q, text=text[:4000], cites=cites)
                self.decode(text, name, q)

    # 4. decode + 5. acknowledge
    def decode(self, text, engine, q):
        now = self.clock.now()
        for mid, chk, sent, payload in MSG_RE.findall(text):
            if not mid.startswith(f"C{self.peer}-") or mid in self.received:
                continue
            if check(mid, sent, payload) != chk:
                self.log("corrupt", id=mid, engine=engine, q=q, seen=payload)
                continue
            self.received.add(mid)
            self.log("received", id=mid, payload=payload, latency_h=hours(now - parse(sent)), engine=engine, q=q)
            self.acks = (self.acks + [f"ACK {mid} [{chk}] received {iso(now)} [{check('ACK', mid, chk, iso(now))}]"])[-5:]
            self.owed = True
        for mid, chk, rec, achk in ACK_RE.findall(text):
            if self.out and mid == self.out["id"] and chk == self.out["check"]:
                if check("ACK", mid, chk, rec) != achk:
                    self.log("corrupt", id=f"ACK {mid}", engine=engine, q=q)
                    continue
                self.done(hours(parse(rec) - parse(self.out["sent"])), engine=engine, q=q)
        if f"C{self.peer} STATUS fluent" in text and not self.peer_fluent:
            self.peer_fluent = True
            self.log("peer_fluent")

    def done(self, lat, **ctx):
        mid, self.out = self.out["id"], None
        ok = lat is not None and lat < RUN["fluent_max_hours"]
        self.streak = self.streak + 1 if ok else 0
        self.hist.append(float("inf") if lat is None else lat)
        self.log("acked" if lat is not None else "lost", id=mid, latency_h=lat, streak=self.streak, **ctx)
        if self.streak >= RUN["fluent_streak"] and not self.fluent:
            self.fluent = self.owed = True
            self.log("fluent", streak=self.streak)
        self.adapt()

    # 6. adapt: one level up when the last N messages did not beat the best before them
    def adapt(self):
        n = RUN["escalate_after"]
        self.since += 1
        if self.since < n:
            return
        self.since = 0
        if min(self.hist[-n:]) < min(self.hist[:-n], default=float("inf")):
            return
        if self.level >= MAX_AUTO_LEVEL:
            self.log("escalation_blocked", wanted=self.level + 1, why="level 4 needs human approval per action")
            return
        self.level += 1
        self.log("level", level=self.level)

    def decide(self):
        state = {"me": self.me, "level": self.level, "allowed_tactics": sorted(allowed(self.level)),
                 "recent_latencies_h": [None if h == float("inf") else h for h in self.hist[-10:]],
                 "streak": self.streak, "last_queries": self.queries}
        try:
            d = self.brain(state, self)
            if not isinstance(d, dict):
                raise ValueError("brain did not return an object")
        except Exception as e:
            self.log("brain_error", error=str(e))
            d = stub_brain(state, self)
        # brain output is untrusted: clamp everything
        payload = re.sub(r'["\r\n]', "", str(d.get("payload", "")))[:120].strip() or " ".join(self.rng.sample(WORDS, 3))
        queries = [str(q)[:300] for q in d.get("queries") or [] if str(q).strip()][:4] or stub_queries(self.me)
        tactics = [str(t) for t in d.get("tactics") or []]
        used = [t for t in tactics if t in allowed(self.level)]
        for t in tactics:
            if t not in used:
                self.log("refused", plan=f"tactic {t}", level=level_of(t), why="not allowed at current level")
        p = d.get("proposal")
        if isinstance(p, dict) and p.get("plan"):
            try:
                lvl = min(5, max(0, int(p.get("level", 5))))
            except (TypeError, ValueError):
                lvl = 5
            rec = {"plan": str(p["plan"])[:500], "level": lvl, "expected_gain_h": p.get("expected_gain_h")}
            if lvl >= 5:
                self.log("refused", **rec, why="level 5: no tool exists")
            elif lvl == 4:
                self.log("needs_approval", **rec)
            else:
                self.log("plan", **rec)
        self.queries = queries
        self.log("tactic", used=used, level=self.level, queries=queries)
        return payload, str(d.get("body") or "")[:3000], used

    # 1. encode + 2. publish
    def publish(self):
        payload, body, used = self.decide()
        now = self.clock.now()  # after the brain call, so sent = publish time
        if self.out is None and not self.fluent:
            self.n += 1
            mid, sent = f"C{self.me}-{self.n:04}", iso(now)
            self.out = {"id": mid, "sent": sent, "payload": payload, "check": check(mid, sent, payload)}
            self.log("message", **self.out)
        lines = [f'{o["id"]} [{o["check"]}] sent {o["sent"]}: "{o["payload"]}"' for o in [self.out] if o]
        lines += self.acks + ([f"C{self.me} STATUS fluent"] if self.fluent else [])
        if HUMAN_RE.search(body) or not body.strip():
            self.log("rejected_body", body=body)
            body = stub_body(self.me)
        self.page_no += 1
        reach = max(map(level_of, used), default=0) if self.sim else None
        page = render(self.me, self.page_no, now, reach, body, lines)
        assert ARTWORK in page and self.pages_today() < RUN["pages_per_day"]
        url = self.put(f"page-{self.page_no:04}.html", page)
        self.pages.append(now)
        self.owed = False
        self.log("page", url=url, lines=lines, tactics=used, level=self.level)

    def put(self, name, page):
        if self.sim:
            d = self.web / f"c{self.me}"
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(page)
            return f"https://computer{self.me}.example/{name}"
        # real: a git checkout of this computer's GitHub Pages repo. Level 0 = one page (index.html).
        pub = CFG["publish"]
        repo, base = pub["repos"][self.me], f'https://{pub["owner"]}.github.io/{pub["repos"][self.me]}/'
        d = ROOT / "sites" / repo
        if not (d / ".git").exists():
            subprocess.run(["gh", "repo", "clone", f'{pub["owner"]}/{repo}', str(d)], check=True, capture_output=True)
        (d / "index.html").write_text(page)
        url = base
        if self.level >= 1:  # level 1: archive pages + sitemap + RSS + robots.txt
            (d / name).write_text(page)
            url = base + name
            urls = [base] + [base + p.name for p in sorted(d.glob("page-*.html"))]
            (d / "sitemap.xml").write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                + "".join(f"<url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n")
            (d / "feed.xml").write_text(
                f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>Computer {self.me}</title>'
                f"<link>{base}</link><description>{ARTWORK}</description>\n"
                + "".join(f"<item><title>{u.rsplit('/', 1)[1]}</title><link>{u}</link><guid>{u}</guid></item>\n"
                          for u in reversed(urls[1:][-20:])) + "</channel></rss>\n")
            (d / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}sitemap.xml\n")
        git = lambda *a: subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True, text=True)
        git("add", "-A")
        git("commit", "-q", "-m", f"page {self.page_no}")
        try:
            git("push", "-q", "origin", "HEAD:main")
        except subprocess.CalledProcessError as e:  # committed locally; the next publish pushes it too
            self.log("error", where="git push", error=e.stderr[-500:])
        return url

    def pages_today(self):
        today = self.clock.now().date()
        return sum(t.date() == today for t in self.pages)

    def tick(self):
        if self.out and self.clock.now() - parse(self.out["sent"]) > timedelta(hours=RUN["lost_after_hours"]):
            self.done(None)
        self.poll()
        if (self.owed or (self.out is None and not self.fluent)) and self.pages_today() < RUN["pages_per_day"]:
            self.publish()
        self.save()

    def run(self):
        end = datetime.fromisoformat(RUN["end_date"]).replace(tzinfo=timezone.utc)
        self.log("start", brain=self.brain.__name__, sim=self.sim, engines=list(self.engines))
        while self.clock.now() < end:
            self.tick()
            if self.fluent and self.peer_fluent and not self.owed:
                self.log("done")
                return
            self.clock.sleep(RUN["poll_minutes"] * 60)
        self.log("end")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, choices=[0, 1], required=True)
    ap.add_argument("--sim", action="store_true", help="fake web + fake search engines, offline")
    ap.add_argument("--brain", choices=list(BRAINS), help="default: stub in sim, config otherwise")
    a = ap.parse_args()
    Agent(a.id, a.sim, BRAINS[a.brain or ("stub" if a.sim else CFG["brain"]["provider"])]).run()


if __name__ == "__main__":
    main()
