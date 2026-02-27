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

Read the codebase to understand the app's models, business logic, and
domain. Then hit GET /fenrir/schema and POST /fenrir/query to see what
the database actually looks like and sample some data.

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

This file will be maintained alongside the codebase. Keep it concise
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

## License

MIT
