#!/bin/sh
# Offline dry run: fake web + fake engines, both agents, live screen. Usage: ./sim.sh [speed] [extra agent args]
# speed = sim seconds per real second (3600: one sim hour per second). Ctrl-C stops everything.
cd "$(dirname "$0")" || exit 1
SPEED=${1:-3600}; [ $# -gt 0 ] && shift
rm -rf sim log/sim && mkdir -p sim log/sim
python3 -c "import json,time; json.dump({'real0': time.time(), 'speed': $SPEED}, open('sim/clock.json', 'w'))"
python3 agent.py --id 0 --sim "$@" 2>log/sim/c0.err & A=$!
python3 agent.py --id 1 --sim "$@" 2>log/sim/c1.err & B=$!
trap 'kill $A $B 2>/dev/null; exit' INT TERM EXIT
python3 screen.py log/sim
