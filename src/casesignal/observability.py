"""Central Sentry wiring for backend components (API + workers).

Dormant unless ``SENTRY_DSN`` is set, so calling any of this is always safe:
local dev, tests, and CI need no Sentry account, and production is strictly
opt-in via env. Errors are captured for free; tracing is sampled (default 0)
to bound cost on a self-funded project.

Capture strategy: the codebase already calls ``logger.exception(...)`` at every
failure site (API exception handlers, the worker loop). Sentry's default
LoggingIntegration turns ``ERROR``-and-above records into events, so simply
calling :func:`init_sentry` at each entrypoint wires up error reporting without
touching those call sites.

Worker liveness: :func:`worker_heartbeat` sends throttled check-ins to a Sentry
cron monitor (a dead-man's-switch). If the worker crashes OR silently hangs
(e.g. a wedged Ollama backend), check-ins stop and Sentry alerts after the
grace period.
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

_initialized = False
_last_checkin = 0.0


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw.strip())


def init_sentry(component: str) -> bool:
    """Initialize Sentry for a backend ``component`` (e.g. ``"api"``).

    Returns ``True`` if Sentry is active afterward, ``False`` if it stayed
    dormant (no ``SENTRY_DSN``). Idempotent: a second call is a cheap no-op.
    """
    global _initialized
    if _initialized:
        return True

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    import sentry_sdk

    environment = os.getenv("SENTRY_ENVIRONMENT") or os.getenv("APP_ENV", "production")
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=(os.getenv("SENTRY_RELEASE") or None),
        traces_sample_rate=_float_env("SENTRY_TRACES_SAMPLE_RATE", 0.0),
        # This platform handles sensitive case data (victim narratives, full
        # street addresses sent to the geocoder). Lock down every channel Sentry
        # could otherwise exfiltrate sensitive payloads through:
        #   - send_default_pii: no request bodies / headers / user identifiers.
        #   - include_local_variables: drop stack-frame locals — the most likely
        #     place an address or narrative shows up in a traceback.
        #   - max_breadcrumbs=0: ship NO breadcrumbs at all. Log records (e.g.
        #     census logs full_address at WARNING) and outbound-HTTP breadcrumbs
        #     (the geocoder URL embeds the address) would otherwise leak.
        # Errors, stack traces (without locals), messages, and tags still flow,
        # which is what we actually need for triage.
        send_default_pii=False,
        include_local_variables=False,
        max_breadcrumbs=0,
    )
    sentry_sdk.set_tag("component", component)
    _initialized = True
    logger.info("sentry initialized component=%s environment=%s", component, environment)
    return True


def worker_heartbeat(min_interval_seconds: float = 60.0) -> None:
    """Send a throttled OK check-in to the worker's Sentry cron monitor.

    No-op unless Sentry is initialized AND ``SENTRY_WORKER_MONITOR_SLUG`` is
    set. Safe to call on every loop iteration; check-ins are throttled to at
    most one per ``min_interval_seconds``. The monitor is upserted on first
    check-in, so no manual setup in the Sentry UI is required: an interval
    schedule with a grace margin means a stalled worker is flagged
    automatically once check-ins lapse.
    """
    global _last_checkin
    if not _initialized:
        return
    slug = os.getenv("SENTRY_WORKER_MONITOR_SLUG", "").strip()
    if not slug:
        return

    now = time.monotonic()
    if _last_checkin and (now - _last_checkin) < min_interval_seconds:
        return
    _last_checkin = now

    import sentry_sdk

    sentry_sdk.crons.capture_checkin(
        monitor_slug=slug,
        status="ok",
        monitor_config={
            "schedule": {"type": "interval", "value": 5, "unit": "minute"},
            "checkin_margin": 5,  # grace minutes before a missed check-in alerts
            "max_runtime": 30,
            "failure_issue_threshold": 1,
            "recovery_threshold": 1,
        },
    )
