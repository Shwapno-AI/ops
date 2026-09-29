# Operations Dashboard for Coolify (or any Docker host).
# Serves the site with nginx and refreshes data from Google Drive every REFRESH_MINUTES.
FROM nginx:1.27-alpine

RUN apk add --no-cache python3 py3-pip nodejs openssl tzdata \
 && pip3 install --no-cache-dir --break-system-packages "openpyxl==3.1.5" "xlrd>=2.0,<3"

ENV TZ=Asia/Dhaka \
    REFRESH_MINUTES=60 \
    REFRESH_FROM=8 \
    REFRESH_TO=23 \
    WATCH_MINUTES=5 \
    RCV_MINUTES=10 \
    RCV_DRILL_DIR=/usr/share/nginx/html/data/rcv-drill \
    DATA_OUT=/usr/share/nginx/html/data/data.json \
    NETWORK_OUT=/usr/share/nginx/html/data/network.json \
    CW_OUT=/usr/share/nginx/html/data/cw.json \
    AV_OUT=/usr/share/nginx/html/data/av.json \
    RCV_OUT=/usr/share/nginx/html/data/rcv.json \
    SKU_OUT=/usr/share/nginx/html/data/sku.json

COPY index.html /usr/share/nginx/html/
COPY assets /usr/share/nginx/html/assets
COPY data /usr/share/nginx/html/data
COPY scripts /app/scripts
# the receiving drill snapshot (scripts/rcv/drill.mjs) uses the browser's Power BI client
COPY assets/vendor/rcv-powerbi.js /app/assets/vendor/rcv-powerbi.js
RUN echo '{"type":"module"}' > /app/assets/package.json
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s CMD wget -qO- http://127.0.0.1/healthz || exit 1
ENTRYPOINT ["/entrypoint.sh"]
