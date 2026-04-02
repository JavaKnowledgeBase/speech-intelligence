from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_frontend_shell_served_at_root():
    response = client.get('/')
    assert response.status_code == 200
    assert 'TalkBuddy Voice Console' in response.text
    assert '/static/app.js' in response.text


def test_frontend_assets_served():
    response = client.get('/static/app.js')
    assert response.status_code == 200
    assert 'loadBootstrap' in response.text
