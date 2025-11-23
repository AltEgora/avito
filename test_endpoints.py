import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server import Base, app, get_db

TEST_DATABASE_URL = "postgresql://pr_user:secret@localhost:5432/pr_test_db"


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(setup_test_db):
    engine = create_engine(TEST_DATABASE_URL)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    yield db
    app.dependency_overrides.clear()
    db.close()


@pytest.fixture
def client(db_session):
    with TestClient(app) as c:
        yield c


def test_create_and_get_team(client):
    """Тест успешного создания и получения команды."""
    team_payload = {
        "team_name": "backend",
        "members": [
            {"user_id": "u1", "username": "Alice", "is_active": True},
            {"user_id": "u2", "username": "Bob", "is_active": True},
        ],
    }

    response = client.post("/team/add", json=team_payload)
    assert response.status_code == 201
    assert response.json()["team"]["team_name"] == "backend"
    assert len(response.json()["team"]["members"]) == 2

    response = client.get("/team/get?team_name=backend")
    assert response.status_code == 200
    assert response.json()["team_name"] == "backend"
    assert response.json()["members"][0]["username"] == "Alice"


def test_create_team_conflict(client):
    """Тест попытки создать уже существующую команду."""
    team_payload = {"team_name": "payments", "members": []}
    client.post("/team/add", json=team_payload)

    response = client.post("/team/add", json=team_payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TEAM_EXISTS"


def test_get_non_existent_team(client):
    """Тест получения несуществующей команды."""
    response = client.get("/team/get?team_name=nonexistent")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_set_user_activity(client):
    """Тест установки флага активности пользователя."""

    client.post(
        "/team/add",
        json={
            "team_name": "qa",
            "members": [{"user_id": "u_qa", "username": "Tester", "is_active": True}],
        },
    )

    response = client.post(
        "/users/setIsActive", json={"user_id": "u_qa", "is_active": False}
    )
    assert response.status_code == 200
    assert response.json()["user"]["is_active"] is False


def test_set_activity_for_non_existent_user(client):
    """Тест установки активности для несуществующего пользователя."""
    response = client.post(
        "/users/setIsActive", json={"user_id": "ghost", "is_active": True}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_create_pr_with_few_candidates(client):
    """Тест создания PR, когда в команде мало активных участников."""
    client.post(
        "/team/add",
        json={
            "team_name": "solo",
            "members": [
                {"user_id": "author_solo", "username": "SoloAuthor", "is_active": True},
                {"user_id": "rev_solo", "username": "SoloRev", "is_active": True},
            ],
        },
    )
    pr_payload = {
        "pull_request_id": "pr-2",
        "pull_request_name": "Solo work",
        "author_id": "author_solo",
    }
    response = client.post("/pullRequest/create", json=pr_payload)

    assert response.status_code == 201
    assert response.json()["pr"]["assigned_reviewers"] == ["rev_solo"]


def test_create_pr_conflict(client):
    """Тест создания PR с уже существующим ID."""
    client.post(
        "/team/add",
        json={
            "team_name": "conflict",
            "members": [{"user_id": "u_c", "username": "User", "is_active": True}],
        },
    )
    pr_payload = {
        "pull_request_id": "pr-dup",
        "pull_request_name": "Dup",
        "author_id": "u_c",
    }
    client.post("/pullRequest/create", json=pr_payload)

    response = client.post("/pullRequest/create", json=pr_payload)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PR_EXISTS"


def test_merge_pr_idempotency(client):
    """Тест идемпотентности операции слияния PR."""
    client.post(
        "/team/add",
        json={
            "team_name": "merge",
            "members": [{"user_id": "u_m", "username": "Merger", "is_active": True}],
        },
    )
    client.post(
        "/pullRequest/create",
        json={
            "pull_request_id": "pr-merge",
            "pull_request_name": "To merge",
            "author_id": "u_m",
        },
    )

    response = client.post("/pullRequest/merge", json={"pull_request_id": "pr-merge"})
    assert response.status_code == 200
    assert response.json()["pr"]["status"] == "MERGED"
    assert response.json()["pr"]["mergedAt"] is not None

    response = client.post("/pullRequest/merge", json={"pull_request_id": "pr-merge"})
    assert response.status_code == 200
    assert response.json()["pr"]["status"] == "MERGED"

    first_merge_time = response.json()["pr"]["mergedAt"]
    response = client.post("/pullRequest/merge", json={"pull_request_id": "pr-merge"})
    assert response.json()["pr"]["mergedAt"] == first_merge_time


def test_reassign_on_merged_pr(client):
    """Тест переназначения на уже слитом PR."""
    client.post(
        "/team/add",
        json={
            "team_name": "merged_reassign",
            "members": [{"user_id": "u_mr", "username": "UserMR", "is_active": True}],
        },
    )
    client.post(
        "/pullRequest/create",
        json={
            "pull_request_id": "pr-merged",
            "pull_request_name": "Merged PR",
            "author_id": "u_mr",
        },
    )
    client.post("/pullRequest/merge", json={"pull_request_id": "pr-merged"})

    response = client.post(
        "/pullRequest/reassign",
        json={"pull_request_id": "pr-merged", "old_reviewer_id": "u_mr"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PR_MERGED"


def test_reassign_non_assigned_reviewer(client):
    """Тест переназначения пользователя, который не является ревьюером."""
    client.post(
        "/team/add",
        json={
            "team_name": "not_assigned",
            "members": [
                {"user_id": "u_na1", "username": "UserNA1", "is_active": True},
                {"user_id": "u_na2", "username": "UserNA2", "is_active": True},
            ],
        },
    )
    client.post(
        "/pullRequest/create",
        json={
            "pull_request_id": "pr-na",
            "pull_request_name": "Not Assigned",
            "author_id": "u_na1",
        },
    )

    response = client.post(
        "/pullRequest/reassign",
        json={"pull_request_id": "pr-na", "old_reviewer_id": "u_na1"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NOT_ASSIGNED"


def test_get_user_reviews(client):
    """Тест получения PR, где пользователь является ревьюером."""
    client.post(
        "/team/add",
        json={
            "team_name": "reviews",
            "members": [
                {"user_id": "u_rev1", "username": "Rev1", "is_active": True},
                {"user_id": "u_rev2", "username": "Rev2", "is_active": True},
            ],
        },
    )
    client.post(
        "/pullRequest/create",
        json={
            "pull_request_id": "pr-for-rev1",
            "pull_request_name": "For Rev1",
            "author_id": "u_rev1",
        },
    )
    client.post(
        "/pullRequest/create",
        json={
            "pull_request_id": "pr-for-rev2",
            "pull_request_name": "For Rev2",
            "author_id": "u_rev2",
        },
    )

    response = client.get("/users/getReview?user_id=u_rev1")
    assert response.status_code == 200
    assert response.json()["user_id"] == "u_rev1"
    assert len(response.json()["pull_requests"]) == 1
    assert response.json()["pull_requests"][0]["pull_request_id"] == "pr-for-rev2"


def test_get_reviews_for_non_existent_user(client):
    """Тест получения ревью для несуществующего пользователя."""
    response = client.get("/users/getReview?user_id=ghost_user")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_user_assignment_stats(client):
    """Тест получения статистики назначения PR по пользователям."""
    client.post(
        "/team/add",
        json={
            "team_name": "stat_team",
            "members": [
                {"user_id": "u_s1", "username": "S1", "is_active": True},
                {"user_id": "u_s2", "username": "S2", "is_active": True},
            ],
        },
    )
    client.post(
        "/pullRequest/create",
        json={
            "pull_request_id": "pr-s1",
            "pull_request_name": "Stat1",
            "author_id": "u_s1",
        },
    )
    client.post(
        "/pullRequest/create",
        json={
            "pull_request_id": "pr-s2",
            "pull_request_name": "Stat2",
            "author_id": "u_s2",
        },
    )
    response = client.get("/stats/user_assignments")
    stats = {s["user_id"]: s["assignments_count"] for s in response.json()["stats"]}
    assert "u_s1" in stats or "u_s2" in stats


def test_mass_deactivation(client):
    """Тест массовой деактивации участников команды."""
    client.post(
        "/team/add",
        json={
            "team_name": "deact_team",
            "members": [
                {"user_id": "u_da1", "username": "DA1", "is_active": True},
                {"user_id": "u_da2", "username": "DA2", "is_active": True},
            ],
        },
    )
    client.post(
        "/pullRequest/create",
        json={
            "pull_request_id": "pr-da",
            "pull_request_name": "DA PR",
            "author_id": "u_da1",
        },
    )
    response = client.post("/team/deactivate_members?team_name=deact_team")
    data = response.json()
    assert data["deactivated_count"] == 2
