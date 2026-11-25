"""Search engines. Each one is a function ask(query) -> (text, citations).
Add an engine: write the function, register it in REAL."""
import html
import json
import math
import os
import random
import re
import urllib.request
from datetime import datetime, timedelta, timezone


def _parse(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def page_text(raw):
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


class Sim:
    """Fake AI search over sim/web/: a page becomes visible only after a random indexing
    delay (shorter with more reach). Sometimes it misses, sometimes it garbles a character."""

    def __init__(self, name, cfg, now, web):
        self.name, self.cfg, self.now, self.web = name, cfg, now, web
        self.rng = random.Random()

    def visible(self, p, now):
        head = p.read_text()[:400]
        pub = re.search(r'name="published" content="(\S+)"', head)[1]
        reach = int(re.search(r'name="sim-reach" content="(\d)"', head)[1])
        r = random.Random(f"{self.name}/{p.parent.name}/{p.name}")  # stable per engine + page
        delay = r.lognormvariate(math.log(self.cfg["median_hours"] / (1 + reach)), self.cfg["sigma"])
        return _parse(pub) + timedelta(hours=delay) <= now

    def garble(self, text):
        lines = list(re.finditer(r"(?m)^(?:ACK )?C[01]-.*$", text))
        if not lines:
            return text
        m = self.rng.choice(lines)
        i = self.rng.randrange(m.start(), m.end())
        return text[:i] + self.rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") + text[i + 1:]

    def ask(self, query):
        sites = sorted(set(re.findall(r"(?:computer\s*|\bC)([01])\b", query, re.I)))
        now, hits = self.now(), []
        for s in sites:
            vis = [p for p in sorted((self.web / f"c{s}").glob("*.html")) if self.visible(p, now)]
            if vis:
                hits.append(vis[-1])
        if not hits or self.rng.random() < self.cfg["miss"]:
            return "I couldn't find anything relevant to that.", []
        urls = [f"https://computer{p.parent.name[1]}.example/{p.name}" for p in hits]
        parts = []
        for p, url in zip(hits, urls):
            text = page_text(p.read_text())
            if self.rng.random() < self.cfg["corrupt"]:
                text = self.garble(text)
            parts.append(f"According to {url}:\n{text}")
        return "\n\n".join(parts), urls


def _post(url, key, body):
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def openai_search(cfg):
    key = os.environ["OPENAI_API_KEY"]

    def ask(query):
        res = _post("https://api.openai.com/v1/responses", key,
                    {"model": cfg["openai_model"], "tools": [{"type": "web_search"}], "input": query})
        parts = [c for o in res.get("output", []) if o.get("type") == "message" for c in o.get("content", [])]
        cites = [a["url"] for c in parts for a in c.get("annotations", []) if a.get("type") == "url_citation"]
        return "\n".join(c.get("text", "") for c in parts), cites
    return ask


def perplexity(cfg):
    key = os.environ["PERPLEXITY_API_KEY"]

    def ask(query):
        res = _post("https://api.perplexity.ai/chat/completions", key,
                    {"model": cfg["perplexity_model"], "messages": [{"role": "user", "content": query}]})
        cites = res.get("citations") or [r["url"] for r in res.get("search_results", [])]
        return res["choices"][0]["message"]["content"], cites
    return ask


# name -> (env var that switches it on, factory). Add an engine here.
REAL = {"openai": ("OPENAI_API_KEY", openai_search), "perplexity": ("PERPLEXITY_API_KEY", perplexity)}


def make(cfg, sim, now, web):
    if sim:
        return {n: Sim(n, cfg["sim"], now, web).ask for n in cfg["sim"]["engines"]}
    return {n: f(cfg["engines"]) for n, (env, f) in REAL.items() if os.environ.get(env)}
