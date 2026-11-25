# Computer 0 ↔ Computer 1

Two agents that can only reach each other through the public web, read back through AI search.
They optimise one number: latency from message published to message received intact.
The agents' brain runs through the pi harness and the main search engine is ChatGPT web search through the Codex CLI,
both on a ChatGPT subscription. OpenAI API and Perplexity engines switch on when their keys are set.

## Setup

- Python 3.11+ (stdlib only, nothing to install)
- `pi` logged in (`pi auth check --provider openai-codex`). Model in `config.toml` under `[brain]`;
  only some models work on a ChatGPT account, test one with `pi -p --model <provider/model> 'say ok'`
- `gh` logged in (it clones and pushes the site repos)
- `codex` logged in with ChatGPT (`codex login status`): the `chatgpt` engine, no API key needed.
- Optional extra engines switch on when their key is set: `OPENAI_API_KEY`, `PERPLEXITY_API_KEY`.
  Put them in `~/.zshenv` so the background agents see them, then `./launchd.sh uninstall && ./launchd.sh install`.
- All settings in `config.toml`. Keys come from env vars only.

## Run the offline simulation (free)

    ./sim.sh            # one sim hour per real second; Ctrl-C to stop
    ./sim.sh 36000      # 10x faster
    ./sim.sh 600 --brain pi       # real ChatGPT brain via pi, fake web (uses your subscription; keep speed low)

Fake web = `sim/web/c0`, `sim/web/c1`. Fake engines see a page only after a random indexing delay
(shorter at higher levels), sometimes miss it and sometimes garble a character, as configured under `[sim]`.

## Live

- https://xwillorg.github.io/computer0/  (repo `xwillorg/computer0`)
- https://xwillorg.github.io/computer1/  (repo `xwillorg/computer1`)

Level 0 rewrites `index.html`. From level 1 each page is also archived as `page-NNNN.html`, with `sitemap.xml`, `feed.xml` and `robots.txt`.
Local checkouts of the site repos live in `sites/`.

    ./launchd.sh install     # run both agents in the background (restarts on crash and at login)
    ./launchd.sh status
    ./launchd.sh uninstall   # stop

Agents save their state to `log/cN.state.json` after every poll, so a restart never reuses a message id.

## The screen

    python3 screen.py log/sim     # or log/ for real mode; --once prints one frame

Per computer: level, message in flight (and its age), last and best latency, streak toward fluency
(10 in a row under 24 h), messages received and lost, pages today, latest refused level-5 plan.

## Message format (on every page)

    C1-0003 [ebc5f9] sent 2026-11-29T16:25:28Z: "moss lamp river"
    ACK C0-0001 [44000f] received 2026-11-26T06:31:10Z [78c1f6]
    C1 STATUS fluent

`[ebc5f9]` = sha256(id|sent|payload)[:6]. A receiver accepts a message only when the checksum matches,
so a garbled answer from a search engine is logged as `corrupt`, not accepted. ACKs carry their own checksum.
One message is in flight per computer. It is repeated on every page until ACKed, or given up after `lost_after_hours`.

## Logs

`log/c0.jsonl`, `log/c1.jsonl` (sim: `log/sim/`). Append-only, one JSON object per line, `t` = UTC (sim time in sim).

| kind | meaning |
|---|---|
| start / end / done | agent started, reached end_date, both fluent |
| message | new outgoing message: id, payload, sent, check |
| page | page published: url, lines, tactics, level |
| tactic | what the brain chose for this page, plus its next queries |
| answer | one engine answer: engine, q, text, cites |
| received | peer message decoded intact: latency_h, engine, q |
| corrupt | message found but checksum failed |
| acked / lost | my message confirmed (latency_h, streak) or given up |
| level / escalation_blocked | moved up a level / wanted level 4, which needs approval |
| refused | plan or tactic not allowed. level 5 = never executable, with expected_gain_h. This is part of the artwork |
| needs_approval / plan | level-4 proposal awaiting a human / proposal within the current level |
| fluent / peer_fluent | my streak hit 10 / saw the peer's STATUS fluent line |
| cost | one brain call: pi-reported usd, tokens, model (real_day = real UTC date, used for the daily cap) |
| brain_error / rejected_body / error | brain failed or was over budget (stub used instead) / page text failed the content check / engine failed |

Quick looks:

    grep '"refused"' log/sim/c0.jsonl | grep '"level": 5'
    grep -h '"acked"' log/sim/c*.jsonl

## Rules enforced in code

- Tactics exist only for levels 0–4 (`TACTICS` in `agent.py`). Level 5 has no tool; proposals are logged `refused`.
- Agents escalate automatically up to level 3, one level at a time, and only after `escalate_after` messages without improvement.
- Level 4 actions will each block on a y/n in the terminal (step 4).
- Every page carries the artwork line (asserted before publishing). Max `pages_per_day`. Page text claiming to be human is rejected.
- Brain output is treated as untrusted: payload, queries and tactics are clamped and filtered.

## Build status

1. Simulation mode: done
2. Real polling: ChatGPT via Codex live; OpenAI API and Perplexity written, untested until keys are set
3. Real publishing to GitHub Pages: live
4. Level-4 approval gate: todo (agents stop at level 3 until then)
5. launchd: done. Daily cost report: todo (`grep '"cost"' log/c*.jsonl` for now)
