#!/bin/sh
set -e
node server.js &
if [ -n "$MAX_BOT_TOKEN" ]; then
  python3 bot/main.py &
fi
wait -n
exit $?
