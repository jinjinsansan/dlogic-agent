"""Gunicorn configuration for Dlogic LINE Bot.

gevent workers: each worker handles 100+ concurrent connections via green threads.
With 4 workers on a 4-core VPS, this handles 400+ simultaneous LINE webhook requests.
"""

import os
import multiprocessing

# Server socket
bind = "0.0.0.0:5000"

# Worker processes
# Default to 1 worker; can scale when Redis is enabled for shared sessions.
workers = int(os.getenv("GUNICORN_WORKERS", "1"))
worker_class = "gevent"
worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", "1000"))

# Timeouts
timeout = 120  # Claude API can take up to 60s for complex queries
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Process naming
proc_name = "dlogic-linebot"

# Do NOT preload — let gevent monkey-patch before imports
preload_app = False
