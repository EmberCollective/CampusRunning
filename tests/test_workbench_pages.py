"""The default app stays independent of experimental BLE dependencies."""
from pathlib import Path

import pytest

from web import routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(routes.paths, "get_config_dir", lambda: str(tmp_path))
    return routes.create_app().test_client()


@pytest.mark.parametrize("url,initial", [("/", "generate"), ("/track-editor", "tracks")])
def test_shared_workspace_and_real_assets(client, url, initial):
    page = client.get(url)
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert f'page: "{initial}"' in text
    assert 'data-nav="watch"' not in text
    assert '<option value="b5">' not in text
    assert '/static/js/watch.js' not in text
    assert 'frontend-draft' not in text and 'campus-map' not in text
    assert client.get('/static/js/workbench.js').status_code == 200
    assert client.get('/static/vendor/leaflet/leaflet.js').status_code == 200


def test_approved_stylesheet_is_preserved():
    root = Path(__file__).resolve().parents[1]
    assert (root / "web/static/css/style.css").read_text(encoding="utf-8") == (
        root / "docs/design/frontend-draft.css").read_text(encoding="utf-8")
