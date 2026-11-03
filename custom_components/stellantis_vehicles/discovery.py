"""Turn a Supervisor discovery message into a login service URL.

Add-ons that offer a local login service (the same HTTP contract as the upstream
worker: ``POST {"url", "email", "password"}`` -> ``{"code": ...}``) announce
themselves with ``POST /discovery`` and a config like

    {"host": "0e0578fd-stellantis-login-worker", "port": 3000}

Home Assistant turns that into a config flow with source ``hassio``. This module
converts the announcement into the value of ``FIELD_OAUTH_CODE_URL`` so the user
does not have to type the URL.

Deliberately free of Home Assistant imports: the parsing rules are the part that
can be wrong, and they are testable without a running Home Assistant.
"""

from __future__ import annotations

from typing import Any


def login_service_url(config: dict[str, Any] | None) -> str | None:
    """Return ``http://host[:port][/path]`` for a discovery config, or None.

    Only a bare host (name or IP) is accepted - a message carrying a scheme or a
    query string is not something this integration can use. ``path`` is optional
    and defaults to ``/``, which is what the upstream worker serves; the local
    add-on accepts ``/`` as an alias for ``/oauth-code``.
    """
    if not isinstance(config, dict):
        return None

    host = config.get("host")
    if not isinstance(host, str):
        return None
    host = host.strip()
    if not host or "://" in host or "/" in host or " " in host:
        return None

    port = config.get("port")
    if port is not None:
        try:
            port = int(port)
        except (TypeError, ValueError):
            return None
        if not 1 <= port <= 65535:
            return None

    path = config.get("path") or ""
    if not isinstance(path, str):
        return None
    path = path.strip()
    if path and (not path.startswith("/") or "//" in path or "://" in path):
        return None

    return f"http://{host}" + (f":{port}" if port else "") + path
