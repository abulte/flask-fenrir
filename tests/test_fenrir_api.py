"""Tests for fenrir-api using a minimal Flask + SQLModel app with SQLite."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlmodel import Field, Session, SQLModel

from fenrir_api import create_fenrir_bp

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Author(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str | None = None


class Book(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="author.id")
    pages: int | None = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

API_KEY = "test-secret-key"


@pytest.fixture()
def app(tmp_path: Path):
    """Create a minimal Flask app with an in-memory SQLite DB."""
    # Write a FENRIR.md next to the app
    fenrir_md = tmp_path / "FENRIR.md"
    fenrir_md.write_text("# Bookstore\n\nA tiny bookstore app.\n")

    engine = create_engine("sqlite://", echo=False)
    SQLModel.metadata.create_all(engine)

    # Seed data
    with Session(engine) as session:
        a = Author(name="Tolkien", email="jrr@shire.nz")
        session.add(a)
        session.commit()
        session.refresh(a)
        session.add(Book(title="The Hobbit", author_id=a.id, pages=310))
        session.commit()

    app = Flask(__name__, root_path=str(tmp_path))
    app.config["TESTING"] = True
    app.register_blueprint(create_fenrir_bp(engine))

    os.environ["FENRIR_API_KEY"] = API_KEY
    yield app
    os.environ.pop("FENRIR_API_KEY", None)


@pytest.fixture()
def client(app):
    return app.test_client()


def auth_headers():
    return {"Authorization": f"Bearer {API_KEY}"}


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuth:
    def test_missing_header(self, client):
        r = client.get("/fenrir/")
        assert r.status_code == 401

    def test_wrong_key(self, client):
        r = client.get("/fenrir/", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401

    def test_correct_key(self, client):
        r = client.get("/fenrir/", headers=auth_headers())
        assert r.status_code == 200

    def test_no_env_var(self, client):
        os.environ.pop("FENRIR_API_KEY", None)
        r = client.get("/fenrir/", headers={"Authorization": "Bearer anything"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /fenrir/
# ---------------------------------------------------------------------------


class TestIndex:
    def test_returns_app_info(self, client):
        r = client.get("/fenrir/", headers=auth_headers())
        data = r.get_json()
        assert data["app"] == "Bookstore"
        assert "Bookstore" in data["fenrir_md"]
        assert any(t["name"] == "author" for t in data["tables"])
        assert any(t["name"] == "book" for t in data["tables"])

    def test_row_counts(self, client):
        r = client.get("/fenrir/", headers=auth_headers())
        data = r.get_json()
        authors = next(t for t in data["tables"] if t["name"] == "author")
        books = next(t for t in data["tables"] if t["name"] == "book")
        assert authors["row_count"] == 1
        assert books["row_count"] == 1

    def test_no_fenrir_md(self, tmp_path):
        """When FENRIR.md doesn't exist, fenrir_md should be null."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)

        app = Flask(__name__, root_path=str(empty_dir))
        app.config["TESTING"] = True
        app.register_blueprint(create_fenrir_bp(engine))

        os.environ["FENRIR_API_KEY"] = API_KEY
        with app.test_client() as c:
            r = c.get("/fenrir/", headers=auth_headers())
            data = r.get_json()
            assert data["fenrir_md"] is None
            # Falls back to Flask app name
            assert data["app"] is not None
        os.environ.pop("FENRIR_API_KEY", None)


# ---------------------------------------------------------------------------
# GET /fenrir/schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_returns_tables(self, client):
        r = client.get("/fenrir/schema", headers=auth_headers())
        data = r.get_json()
        assert "author" in data["tables"]
        assert "book" in data["tables"]

    def test_column_info(self, client):
        r = client.get("/fenrir/schema", headers=auth_headers())
        author = r.get_json()["tables"]["author"]
        col_names = [c["name"] for c in author["columns"]]
        assert "id" in col_names
        assert "name" in col_names
        assert "email" in col_names

    def test_primary_key(self, client):
        r = client.get("/fenrir/schema", headers=auth_headers())
        author = r.get_json()["tables"]["author"]
        assert "id" in author["primary_key"]

    def test_foreign_keys(self, client):
        r = client.get("/fenrir/schema", headers=auth_headers())
        book = r.get_json()["tables"]["book"]
        assert len(book["foreign_keys"]) == 1
        fk = book["foreign_keys"][0]
        assert fk["referred_table"] == "author"


# ---------------------------------------------------------------------------
# POST /fenrir/query
# ---------------------------------------------------------------------------


class TestQuery:
    def test_select(self, client):
        r = client.post(
            "/fenrir/query",
            json={"sql": "SELECT name FROM author"},
            headers=auth_headers(),
        )
        data = r.get_json()
        assert data["columns"] == ["name"]
        assert data["rows"] == [["Tolkien"]]
        assert data["row_count"] == 1
        assert data["truncated"] is False

    def test_with_select(self, client):
        r = client.post(
            "/fenrir/query",
            json={"sql": "WITH a AS (SELECT * FROM author) SELECT name FROM a"},
            headers=auth_headers(),
        )
        assert r.status_code == 200
        assert r.get_json()["row_count"] == 1

    def test_rejects_insert(self, client):
        r = client.post(
            "/fenrir/query",
            json={"sql": "INSERT INTO author (name) VALUES ('nope')"},
            headers=auth_headers(),
        )
        assert r.status_code == 400

    def test_rejects_delete(self, client):
        r = client.post(
            "/fenrir/query",
            json={"sql": "DELETE FROM author"},
            headers=auth_headers(),
        )
        assert r.status_code == 400

    def test_missing_sql(self, client):
        r = client.post("/fenrir/query", json={}, headers=auth_headers())
        assert r.status_code == 400

    def test_row_limit(self, tmp_path):
        """Row limit caps the number of returned rows."""
        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            for i in range(10):
                session.add(Author(name=f"Author {i}"))
            session.commit()

        app = Flask(__name__, root_path=str(tmp_path))
        app.config["TESTING"] = True
        app.register_blueprint(create_fenrir_bp(engine, row_limit=3))

        os.environ["FENRIR_API_KEY"] = API_KEY
        with app.test_client() as c:
            r = c.post(
                "/fenrir/query",
                json={"sql": "SELECT * FROM author"},
                headers=auth_headers(),
            )
            data = r.get_json()
            assert data["row_count"] == 3
            assert data["truncated"] is True
            assert data["row_limit"] == 3
        os.environ.pop("FENRIR_API_KEY", None)

    def test_bad_sql(self, client):
        r = client.post(
            "/fenrir/query",
            json={"sql": "SELECT * FROM nonexistent"},
            headers=auth_headers(),
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /fenrir/execute
# ---------------------------------------------------------------------------


class TestExecute:
    def test_insert(self, client):
        r = client.post(
            "/fenrir/execute",
            json={"sql": "INSERT INTO author (name) VALUES ('Pratchett')"},
            headers=auth_headers(),
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["affected_rows"] == 1

    def test_update(self, client):
        r = client.post(
            "/fenrir/execute",
            json={"sql": "UPDATE author SET email = 'updated@test.com' WHERE name = 'Tolkien'"},
            headers=auth_headers(),
        )
        assert r.status_code == 200
        assert r.get_json()["affected_rows"] == 1

    def test_delete(self, client):
        # Insert then delete
        client.post(
            "/fenrir/execute",
            json={"sql": "INSERT INTO author (name) VALUES ('temp')"},
            headers=auth_headers(),
        )
        r = client.post(
            "/fenrir/execute",
            json={"sql": "DELETE FROM author WHERE name = 'temp'"},
            headers=auth_headers(),
        )
        assert r.status_code == 200
        assert r.get_json()["affected_rows"] == 1

    def test_rejects_select(self, client):
        r = client.post(
            "/fenrir/execute",
            json={"sql": "SELECT * FROM author"},
            headers=auth_headers(),
        )
        assert r.status_code == 400

    def test_missing_sql(self, client):
        r = client.post("/fenrir/execute", json={}, headers=auth_headers())
        assert r.status_code == 400

    def test_bad_sql(self, client):
        r = client.post(
            "/fenrir/execute",
            json={"sql": "INSERT INTO nonexistent (x) VALUES (1)"},
            headers=auth_headers(),
        )
        assert r.status_code == 422
