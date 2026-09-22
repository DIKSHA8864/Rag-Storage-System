"""
Rate limiting (slowapi, a Starlette-compatible wrapper around
limits) - protects the API from brute-force login attempts and
retrieval-endpoint abuse. Keyed by client IP by default; falls back
to a constant key if no IP is available (e.g. in tests via
TestClient), so tests never depend on rate limiting incidentally.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])