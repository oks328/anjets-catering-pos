"""Database-backed authentication limits shared by all application workers."""

import hashlib
import hmac
import math
from datetime import datetime, timedelta, timezone

from flask import current_app, make_response, render_template, request
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import db
from app.models import AuthRateLimit


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def consume_bucket(connection, key, limit, window, now):
    table = AuthRateLimit.__table__
    for _ in range(2):
        active = connection.execute(
            update(table)
            .where(
                table.c.key == key,
                table.c.expires_at > now,
                table.c.attempts < limit,
            )
            .values(attempts=table.c.attempts + 1)
        )
        if active.rowcount:
            return 0
        expired = connection.execute(
            update(table)
            .where(
                table.c.key == key,
                table.c.expires_at <= now,
            )
            .values(attempts=1, expires_at=now + timedelta(seconds=window))
        )
        if expired.rowcount:
            return 0
        row = connection.execute(select(table.c.expires_at).where(table.c.key == key)).first()
        if row:
            return max(1, math.ceil((row.expires_at - now).total_seconds()))
        try:
            with connection.begin_nested():
                connection.execute(
                    insert(table).values(
                        key=key, attempts=1, expires_at=now + timedelta(seconds=window)
                    )
                )
            return 0
        except IntegrityError:
            # Another worker inserted this bucket; retry the conditional update.
            continue
    raise RuntimeError("Could not reserve an authentication attempt")


def enforce_auth_limits():
    endpoint = request.endpoint
    if request.method != "POST" or endpoint not in (
        "client_login",
        "admin_login",
        "client_forgot_password",
        "client_reset_token",
    ):
        return
    reset = endpoint in ("client_forgot_password", "client_reset_token")
    prefix = "AUTH_RESET" if reset else "AUTH_LOGIN"
    config = current_app.config
    window = config[f"{prefix}_WINDOW_SECONDS"]
    buckets = [("ip", request.remote_addr or "unknown", config[f"{prefix}_IP_LIMIT"])]
    if endpoint != "client_reset_token":
        identity = (
            request.form.get("username" if endpoint == "admin_login" else "email", "")
            .strip()
            .casefold()
        )
        buckets.append(("account", identity, config[f"{prefix}_ACCOUNT_LIMIT"]))
    now = utc_now()
    retry_after = 0
    try:
        with db.engine.begin() as connection:
            connection.execute(
                delete(AuthRateLimit).where(AuthRateLimit.expires_at < now - timedelta(days=1))
            )
            for kind, identity, limit in buckets:
                scope = f"{endpoint}:{kind}:{identity}"
                key = hmac.new(
                    current_app.secret_key.encode(), scope.encode(), hashlib.sha256
                ).hexdigest()
                retry_after = consume_bucket(connection, key, limit, window, now)
                if retry_after:
                    break
    except (SQLAlchemyError, RuntimeError):
        current_app.logger.exception("Authentication limit storage failed")
        response = make_response(
            "Sign-in is temporarily unavailable. Please try again shortly.", 503
        )
        response.headers["Retry-After"] = "5"
        return response
    if retry_after:
        response = make_response(
            render_template("auth_rate_limited.html", retry_after=retry_after), 429
        )
        response.headers["Retry-After"] = str(retry_after)
        return response
