# flask-fenrir

Drop-in Flask API for LLM agent access to SQLModel web apps. One install, two lines of code, one env var.

## Install

```bash
uv add flask-fenrir
```

## Usage

```python
from flask_fenrir import create_fenrir_bp

app.register_blueprint(create_fenrir_bp(engine))
```

```python
from flask_fenrir import secure_app

secure_app(app)  # optional — adds basic auth to the whole app
```

```bash
dokku config:set myapp FENRIR_API_KEY=$(openssl rand -hex 32)
```

That's it. One env var for everything — bearer token for LLM agents, basic auth password for browser access.

## What it does

Registers a `/fenrir/` blueprint with four endpoints, all behind bearer token auth:

| Endpoint | Method | Description |
|---|---|---|
| `/fenrir/` | GET | App info, FENRIR.md contents, table list with row counts |
| `/fenrir/schema` | GET | Full schema introspection (columns, types, PKs, FKs, indexes) |
| `/fenrir/query` | POST | Read-only SQL (`SELECT` / `WITH ... SELECT`), returns rows as JSON |

### Authentication

`FENRIR_API_KEY` is the single secret for your app.

**Fenrir endpoints** (`/fenrir/*`) require `Authorization: Bearer <key>`.

**`secure_app(app)`** (optional) adds basic auth to all other routes — any username, password must match `FENRIR_API_KEY`. This replaces Dokku's `http-auth` so everything is managed in one place.

Both are skipped when `FLASK_DEBUG` is on. If the env var isn't set, everything returns 401/503 (fail closed).

```python
# Options:
secure_app(app)                                        # basic auth on all routes
secure_app(app, skip_paths=["/health", "/webhook"])     # skip specific paths
secure_app(app, api_key_auth={                          # also accept a separate API key
    "header": "X-API-Key",
    "secret": os.getenv("API_KEY"),
})
```

### FENRIR.md

Write a `FENRIR.md` at your project root with domain context for the LLM:

```markdown
# My App

A brief description of what this app does.

## Domain concepts

- **Widget** — the core thing users create. Has a `status` field: draft, active, archived.
- **Team** — groups of users. The `owner_id` is always a user, not another team.

## Useful queries

- Active widgets by team: `SELECT t.name, COUNT(*) FROM widget w JOIN team t ON ...`
```

The `/fenrir/` endpoint serves this content so the LLM can understand your app before querying it.

#### Generating FENRIR.md with an LLM

If the app is running locally with flask-fenrir enabled, you can have an LLM generate the file. Run this prompt from the app's project root:

```
This app uses flask-fenrir — a small Flask blueprint that exposes the
database to LLM agents via REST (schema introspection, read/write SQL).
It serves a FENRIR.md file at GET /fenrir/ to give the LLM domain
context it can't infer from the schema alone. That's the file you're
writing now.

The API is at /fenrir/.

Read the codebase to understand the app's models, business logic, and
domain. Then hit GET /fenrir/schema and POST /fenrir/query to see what
the database actually looks like from Fenrir POV.

Compare what you learned from the code with what the schema and data
show. Write a FENRIR.md that bridges the gap — focus on things an LLM
querying the database blind would NOT be able to figure out from the
schema alone:
- What the app actually does (one-liner)
- What each table/field means in business terms
- Non-obvious values: enums, flags, status codes, soft deletes, fields
  whose names are misleading
- How tables relate to each other (especially implicit relationships
  not captured by foreign keys)
- Common useful queries for an operator
- Gotchas and edge cases

Don't repeat what's already obvious from column names and types.
An LLM can read a schema — FENRIR.md should add the context it can't
infer.

Ask me questions if anything in the code or data is unclear. Don't
guess at business logic — it's better to ask than to document something
wrong.

This file will need to be maintained alongside the codebase. Keep it concise
and structured so it's easy to update when models change. If a section
would go stale quickly, leave it out or note what to watch for.
```

### Row limit

By default, `/fenrir/query` caps results at 1000 rows. Override it:

```python
app.register_blueprint(create_fenrir_bp(engine, row_limit=500))
```

## Dependencies

Just Flask (≥3.0) and SQLAlchemy (≥2.0). Works with any Flask + SQLAlchemy app — SQLModel not required at runtime.

## Release

```bash
# 1. Bump version
uv version --bump minor   # or --bump patch / --bump major

# 2. Clean old artifacts and build
rm -rf dist/*
uv build

# 3. Publish to PyPI
uv publish dist/* --token "$PYPI_TOKEN"
```

## License

MIT
