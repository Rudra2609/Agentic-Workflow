# Grafana with hmap's datasources and dashboard provisioned (no bind mounts: Colima only shares $HOME).
FROM grafana/grafana:13.0.1
COPY provisioning /etc/grafana/provisioning
COPY dashboards /var/lib/grafana/dashboards
