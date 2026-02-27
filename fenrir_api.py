"""
fenrir-api — Drop-in Flask API for LLM agent access to SQLModel web apps.

Usage:
    from fenrir_api import create_fenrir_bp, secure_app

    app.register_blueprint(create_fenrir_bp(engine))
    secure_app(app)
"""

from __future__ import annotations

import os
import re
from functools import wraps
from pathlib import Path

from flask import Blueprint, Flask, Response, current_app, jsonify, request
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

__all__ = ["create_fenrir_bp", "secure_app"]

DEFAULT_ROW_LIMIT = 1000

# Matches SELECT or WITH ... SELECT (the only read-only shapes we allow)
_READ_ONLY_RE = re.compile(
    r"^\s*(SELECT|WITH\s)", re.IGNORECASE | re.DOTALL
)


def _require_auth(f):
    """Reject requests unless Authorization header matches FENRIR_API_KEY.

    Auth is skipped entirely when the Flask app has DEBUG enabled.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        if current_app.debug:
            return f(*args, **kwargs)

        api_key = os.environ.get("FENRIR_API_KEY")
        if not api_key:
            return jsonify({"error": "FENRIR_API_KEY not configured"}), 401

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != api_key:
            return jsonify({"error": "unauthorized"}), 401

        return f(*args, **kwargs)

    return wrapper


def secure_app(
    app: Flask,
    *,
    skip_paths: list[str] | None = None,
    api_key_header: str | None = None,
) -> None:
    """Add basic auth to all routes except /fenrir/ and static files.

    Uses FENRIR_API_KEY as the password (any username accepted).
    Skipped entirely when app.debug is True.

    Args:
        app: Flask application.
        skip_paths: Additional path prefixes to skip auth for (e.g. ["/health"]).
        api_key_header: Optional header name for API key auth (e.g. "X-API-Key").
            When set, requests with this header matching FENRIR_API_KEY are
            allowed through without basic auth.
    """
    _skip = ["/fenrir/", "/static/"]
    if skip_paths:
        _skip.extend(skip_paths)

    @app.before_request
    def _basic_auth_check():
        if app.debug:
            return

        # Skip excluded paths
        path = request.path
        if path == "/" or any(path.startswith(p) for p in _skip):
            return
        if request.endpoint == "static":
            return

        api_key = os.environ.get("FENRIR_API_KEY")
        if not api_key:
            return Response("Not configured", 503)

        # Check API key header if configured (for MCP / programmatic access)
        if api_key_header:
            header_val = request.headers.get(api_key_header)
            if header_val and header_val == api_key:
                return

        # Check basic auth — any username, password must match FENRIR_API_KEY
        auth = request.authorization
        if auth and auth.password == api_key:
            return

        return Response(
            "Authentication required",
            401,
            {"WWW-Authenticate": 'Basic realm="Login"'},
        )


def _read_fenrir_md() -> str | None:
    """Read FENRIR.md from the app's root directory."""
    root = Path(current_app.root_path)
    # Walk up at most two levels — root_path is often the package dir,
    # FENRIR.md lives at the project root (next to pyproject.toml).
    for base in [root, root.parent, root.parent.parent]:
        candidate = base / "FENRIR.md"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return None


def _extract_app_name(md: str | None, app_name: str) -> str:
    """Pull the first heading from FENRIR.md, or fall back to Flask app name."""
    if md:
        for line in md.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
    return app_name


def create_fenrir_bp(engine: Engine, *, row_limit: int = DEFAULT_ROW_LIMIT) -> Blueprint:
    """Create and return the Fenrir API blueprint.

    Args:
        engine: SQLAlchemy engine to introspect and query.
        row_limit: Max rows returned by /fenrir/query (default 1000).
    """
    bp = Blueprint("fenrir", __name__, url_prefix="/fenrir")

    # -- GET /fenrir/ ----------------------------------------------------------

    @bp.route("/")
    @_require_auth
    def index():
        md = _read_fenrir_md()
        app_name = _extract_app_name(md, current_app.name)

        # Table list with row counts
        insp = inspect(engine)
        tables = []
        with engine.connect() as conn:
            for table_name in sorted(insp.get_table_names()):
                count = conn.execute(
                    text(f'SELECT COUNT(*) FROM "{table_name}"')
                ).scalar()
                tables.append({"name": table_name, "row_count": count})

        return jsonify({
            "app": app_name,
            "fenrir_md": md,
            "tables": tables,
        })

    # -- GET /fenrir/schema ----------------------------------------------------

    @bp.route("/schema")
    @_require_auth
    def schema():
        insp = inspect(engine)
        tables = {}

        for table_name in sorted(insp.get_table_names()):
            columns = []
            for col in insp.get_columns(table_name):
                columns.append({
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "default": str(col["default"]) if col.get("default") is not None else None,
                })

            pk = insp.get_pk_constraint(table_name)
            fks = [
                {
                    "columns": fk["constrained_columns"],
                    "referred_table": fk["referred_table"],
                    "referred_columns": fk["referred_columns"],
                }
                for fk in insp.get_foreign_keys(table_name)
            ]
            indexes = [
                {
                    "name": idx["name"],
                    "columns": idx["column_names"],
                    "unique": idx["unique"],
                }
                for idx in insp.get_indexes(table_name)
            ]

            tables[table_name] = {
                "columns": columns,
                "primary_key": pk.get("constrained_columns", []) if pk else [],
                "foreign_keys": fks,
                "indexes": indexes,
            }

        return jsonify({"tables": tables})

    # -- POST /fenrir/query ----------------------------------------------------

    @bp.route("/query", methods=["POST"])
    @_require_auth
    def query():
        body = request.get_json(silent=True) or {}
        sql = body.get("sql", "").strip()

        if not sql:
            return jsonify({"error": "missing 'sql' field"}), 400

        if not _READ_ONLY_RE.match(sql):
            return jsonify({"error": "only SELECT (or WITH ... SELECT) allowed"}), 400

        try:
            with engine.connect().execution_options(
                postgresql_readonly=True,      # PostgreSQL
                sqlite_raw_colnames=True,      # harmless on SQLite
            ) as conn:
                conn.begin()
                # SET TRANSACTION READ ONLY works on PostgreSQL.
                # SQLite doesn't support it, so we skip errors silently.
                try:
                    conn.execute(text("SET TRANSACTION READ ONLY"))
                except Exception:
                    pass
                result = conn.execute(text(sql))
                columns = list(result.keys())
                rows = [list(r) for r in result.fetchmany(row_limit)]
                total = len(rows)
                # Check if there were more rows we didn't fetch
                extra = result.fetchone()
                truncated = extra is not None
                conn.rollback()
        except Exception as exc:
            return jsonify({"error": str(exc)}), 422

        return jsonify({
            "columns": columns,
            "rows": rows,
            "row_count": total,
            "truncated": truncated,
            "row_limit": row_limit,
        })

    return bp
