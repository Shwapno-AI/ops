#!/bin/sh
# Prepares the data folder, then runs the website as a normal user rather than root.
set -e
DATA_DIR="${DATA_DIR:-/data}"
PORT="${PORT:-3000}"
mkdir -p "$DATA_DIR"

# One worker, because jobs run one at a time from an in-process queue. Threads serve the page during uploads.
# Keep-alive outlasts the proxy's idle timeout, so the proxy never reuses a connection just as it closes.
SERVER="gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 16 --timeout 120 --keep-alive 120 --access-logfile - webapp.app:create_app()"

if [ "$(id -u)" = "0" ]; then
  chown -R app:app "$DATA_DIR"
  exec setpriv --reuid=app --regid=app --init-groups $SERVER
fi
exec $SERVER
