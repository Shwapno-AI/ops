#!/bin/sh
set -e

# Optional password protection: set BASIC_AUTH_USER and BASIC_AUTH_PASSWORD in Coolify.
if [ -n "$BASIC_AUTH_USER" ] && [ -n "$BASIC_AUTH_PASSWORD" ]; then
  printf '%s:%s\n' "$BASIC_AUTH_USER" "$(openssl passwd -apr1 "$BASIC_AUTH_PASSWORD")" > /etc/nginx/.htpasswd
  printf 'auth_basic "Operations dashboard";\nauth_basic_user_file /etc/nginx/.htpasswd;\n' > /etc/nginx/auth.conf
  echo "Password protection on for user $BASIC_AUTH_USER"
else
  : > /etc/nginx/auth.conf
fi

# Refresh loop: download the Drive files and rebuild the data files.
#  - Watch: every WATCH_MINUTES (5), day and night, scripts/watch_drive.py lists the Drive folders (names and
#    modified times only). When a file was added, replaced, renamed or removed, the refresh runs straight away.
#  - Backstop: a full refresh at start-up and every REFRESH_MINUTES between REFRESH_FROM and REFRESH_TO (Dhaka).
# The download cache is kept between runs (files are keyed by Drive id + last-modified), so only new
# or changed files are downloaded; files a run did not use are dropped. A failed run keeps the last good data.
export DRIVE_CACHE=/tmp/drive-cache
refresh() {
  { mkdir -p "$DRIVE_CACHE" && touch /tmp/run-start && sleep 1; } || true
  python3 /app/scripts/build_data.py || echo "Refresh failed; keeping the last good data."
  python3 /app/scripts/network/refresh.py || echo "Outlet network refresh failed; keeping the last good data."
  python3 /app/scripts/cw/refresh.py || echo "Consumable and wastage refresh failed; keeping the last good data."
  python3 /app/scripts/av/refresh.py || echo "Availability refresh failed; keeping the last good data."
  python3 /app/scripts/sku/refresh.py || echo "Item performance refresh failed; keeping the last good data."
  find "$DRIVE_CACHE" -type f ! -newer /tmp/run-start -delete 2>/dev/null || true
  echo "Refresh finished at $(date '+%d %b %H:%M')."
}
(
  last=0
  while true; do
    now=$(date +%s)
    hour=$(date +%H | sed 's/^0//')
    due=0
    if [ "$last" = 0 ]; then due=1
    elif [ $(( now - last )) -ge $(( ${REFRESH_MINUTES:-60} * 60 )) ] && [ "${hour:-0}" -ge "${REFRESH_FROM:-8}" ] && [ "${hour:-0}" -le "${REFRESH_TO:-23}" ]; then due=1
    fi
    if [ "$due" = 1 ]; then
      # remember the listing first, so a file uploaded during the refresh is caught by the next watch
      python3 /app/scripts/watch_drive.py --baseline || true
      echo "Scheduled refresh."
      refresh; last=$(date +%s)
    elif python3 /app/scripts/watch_drive.py; then
      echo "Drive changed; refreshing now."
      refresh; last=$(date +%s)
    fi
    sleep $(( ${WATCH_MINUTES:-5} * 60 ))
  done
) &

# Receiving loop: every RCV_MINUTES (10) around the clock, the receiving snapshot (rcv.json) and the
# drill-down snapshot (data/rcv-drill/, read from Power BI) are renewed, so the Receiving pages never
# wait for Power BI. A run that takes longer than the interval starts the next one right after it.
(
  sleep 20   # let the first Drive run write data.json (the outlet master) first
  while true; do
    start=$(date +%s)
    python3 /app/scripts/rcv/refresh.py || echo "Receiving refresh failed; keeping the last good data."
    node /app/scripts/rcv/drill.mjs || echo "Receiving drill snapshot failed; keeping the last good data."
    left=$(( ${RCV_MINUTES:-10} * 60 - ($(date +%s) - start) ))
    [ "$left" -gt 30 ] && sleep "$left" || sleep 30
  done
) &

exec nginx -g 'daemon off;'
