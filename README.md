# fenrir-api

Drop-in Flask API for LLM agent access to SQLModel web apps. One install, two lines of code, one env var.

## Install

```bash
uv add fenrir-api
```

## Usage

```python
from fenrir_api import create_fenrir_bp

app.register_blueprint(create_fenrir_bp(engine))
```

```bash
dokku config:set myapp FENRIR_API_KEY=$(openssl rand -hex 32)
```

That's it.

## What it does

Registers a `/fenrir/` blueprint with four endpoints, all behind bearer token auth:

| Endpoint | Method | Description |
|---|---|---|
| `/fenrir/` | GET | App info, FENRIR.md contents, table list with row counts |
| `/fenrir/schema` | GET | Full schema introspection (columns, types, PKs, FKs, indexes) |
| `/fenrir/query` | POST | Read-only SQL (`SELECT` / `WITH ... SELECT`), returns rows as JSON |
| `/fenrir/execute` | POST | Write SQL (`INSERT` / `UPDATE` / `DELETE`), returns affected row count |

### Authentication

Every request requires `Authorization: Bearer <key>` where the key matches the `FENRIR_API_KEY` environment variable. If the env var isn't set, all requests return 401 (fail closed).

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

If the app is running locally with fenrir-api enabled, you can have an LLM generate the file. Run this prompt from the app's project root:

```
This app has fenrir-api enabled at http://localhost:5000/fenrir/.
The API key is in the FENRIR_API_KEY env var.

Hit GET /fenrir/schema to get the full schema, then run
SELECT * FROM <table> LIMIT 5 via POST /fenrir/query for each table
to see sample data.

Based on what you find, write a FENRIR.md in the project root with:
- A heading with the app name and a one-line description
- A "Domain concepts" section explaining each table, what the key fields
  mean, and any non-obvious values (enums, flags, special states)
- A "Relationships" section describing how tables connect
- A "Useful queries" section with 5-10 common queries an operator might run
- A "Gotchas" section noting anything weird (nullable fields that shouldn't
  be, implicit conventions, fields that mean something different than their
  name suggests)

Be concise. This file is read by an LLM at runtime, not humans.
```

### Row limit

By default, `/fenrir/query` caps results at 1000 rows. Override it:

```python
app.register_blueprint(create_fenrir_bp(engine, row_limit=500))
```

## Dependencies

Just Flask (≥3.0) and SQLAlchemy (≥2.0). Works with any Flask + SQLAlchemy app — SQLModel not required at runtime.

## License

MIT
