"""Real-time push alerting via ntfy.sh (https://ntfy.sh) — added after
reviewing the project honestly and finding a genuine gap: a "Risk Monitor"
that computes a Severe score and tells nobody. Researched free options
(2026-09-14) before picking this one:

  - ntfy.sh: open source (Apache 2.0 / GPLv2), the public hosted instance
    needs zero signup or API key — a plain HTTP POST to a topic URL is the
    entire integration — and the whole thing is self-hostable later if the
    public instance's reliability or a private topic ever matters. No
    third-party SDK, no billing risk.
  - Considered SMS (Twilio etc.): every option found needs a paid account
    or a time-limited trial, not a genuine no-cost path — see README
    research notes. Not used for that reason, not because it wouldn't
    reach people better.

Off by default (`NTFY_ENABLED=false`) since it needs a topic name you choose
yourself — see config.py. Topics on the public instance are unauthenticated
by name (anyone who knows/guesses the topic name can subscribe), so pick
something unguessable, e.g. `flood-risk-monitor-<random-suffix>`, not
something like "flood-alerts" — and treat it as a shared secret, the same
way you would an API key, not something to commit to the repo.
"""
import logging

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 10


def maybe_send_severe_alert(district, previous_level: str | None, new_level: str, risk_score: float) -> None:
    """Sends one push notification the moment a district's risk *newly*
    reaches Severe — not on every refresh it stays Severe, which would spam
    a daily job into one notification per district per day indefinitely.
    A no-op with zero network calls unless NTFY_ENABLED and NTFY_TOPIC are
    both set, and unless this snapshot is the one that crossed the line."""
    settings = get_settings()
    if not settings.ntfy_enabled or not settings.ntfy_topic:
        return
    if new_level != "Severe" or previous_level == "Severe":
        return

    url = f"{settings.ntfy_server.rstrip('/')}/{settings.ntfy_topic}"
    message = (
        f"{district.name} ({district.province}) risk score {risk_score:.2f} "
        f"has reached Severe. Was: {previous_level or 'no prior data'}."
    )
    try:
        requests.post(
            url,
            data=message.encode("utf-8"),
            headers={
                "Title": f"Flood risk Severe: {district.name}",
                "Priority": "urgent",
                "Tags": "rotating_light,droplet",
            },
            timeout=REQUEST_TIMEOUT_S,
        )
        logger.info("Sent ntfy Severe alert for %s", district.id)
    except requests.RequestException as e:
        # An alert failing to send should never fail the refresh it's
        # attached to — the risk data itself is still good.
        logger.warning("ntfy alert failed for %s: %s", district.id, e)
