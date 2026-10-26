import pytest

from schoolguard.app import create_app


@pytest.mark.parametrize("key,value", [("K_SERVICE", "lh25-api"), ("LH25_DEPLOYMENT_TARGET", "cloud")])
def test_cloud_startup_refuses_ephemeral_sqlite_and_media(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match="cloud backend is not ready"):
        create_app()
