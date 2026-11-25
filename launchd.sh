#!/bin/sh
# Run both agents in the background in real mode. ./launchd.sh install | uninstall | status
# Env vars (API keys) come from ~/.zshenv / ~/.zprofile, since launchd starts a login zsh.
cd "$(dirname "$0")" || exit 1
DIR=$(pwd); mkdir -p log
for i in 0 1; do
  L=group.computer01.agent$i; P=~/Library/LaunchAgents/$L.plist
  case $1 in
  install)
    cat > "$P" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$L</string>
  <key>ProgramArguments</key><array>
    <string>/bin/zsh</string><string>-lc</string><string>exec python3 agent.py --id $i</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/log/c$i.out</string>
  <key>StandardErrorPath</key><string>$DIR/log/c$i.err</string>
</dict></plist>
PLIST
    launchctl bootstrap "gui/$(id -u)" "$P" && echo "started $L" ;;
  uninstall) launchctl bootout "gui/$(id -u)/$L" 2>/dev/null; rm -f "$P"; echo "stopped $L" ;;
  status) launchctl print "gui/$(id -u)/$L" 2>/dev/null | grep -E '^\s*(state|pid|last exit code) =' || echo "$L not loaded" ;;
  *) echo "usage: $0 install|uninstall|status"; exit 1 ;;
  esac
done
