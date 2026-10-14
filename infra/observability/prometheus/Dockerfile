# Prometheus with hmap's scrape config and alert rules baked in (no bind mounts: Colima only shares $HOME).
FROM prom/prometheus:v3.13.4
COPY prometheus.yml alerts.yml /etc/prometheus/
