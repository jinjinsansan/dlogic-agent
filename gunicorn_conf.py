"""Gunicorn configuration for Dlogic LINE Bot.

gevent workers: each worker handles 100+ concurrent connections via green threads.
With 4 workers on a 4-core VPS, this handles 400+ simultaneous LINE webhook requests.
"""

import multiprocessing

# Server socket
bind = "0.0.0.0:5000"

# Worker processes
# Use 1 gevent worker: all work is I/O-bound (Claude API, Supabase, HTTP)
# so gevent handles 1000+ concurrent connections in a single process.
# Multiple workers would split in-memory conversation history across processes.
workers = 1
worker_class = "gevent"
worker_connections = 1000  # max concurrent connections per worker

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
