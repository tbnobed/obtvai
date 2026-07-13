---
name: nginx in Docker caches upstream IPs
description: Why every /api request 502s after rebuilding a backend container behind an nginx frontend
---

# Static upstream blocks break after container rebuilds
An nginx `upstream { server api:8000; }` block resolves the container hostname once at startup and caches the IP. Rebuilding/recreating the backend container assigns a new IP, and nginx keeps sending traffic to the dead one — every proxied request returns 502 "connection refused" while the backend itself is healthy.

**Why:** Docker Compose gives recreated containers new IPs; nginx only re-resolves static upstreams on reload.

**How to apply:** In containerized nginx, proxy with `resolver 127.0.0.11 valid=10s ipv6=off;` + `set $upstream http://api:8000; proxy_pass $upstream;` inside the location block so DNS is re-resolved per request. Symptom to recognize: 502s on all proxied paths right after `docker compose up -d --build <backend>` without restarting the nginx container.
