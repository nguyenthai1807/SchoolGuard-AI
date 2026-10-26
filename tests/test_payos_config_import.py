import pytest

from scripts.configure_payos_local import KEYS, save_gmail, save_keys


def test_import_keeps_unrelated_settings_and_backups_previous_file(tmp_path):
    original = "# local settings\nYOLO_DEVICE=cpu\nLH25_PAYOS_ENABLED=false\nLH25_PAYOS_CLIENT_ID=old\n"
    (tmp_path / ".env").write_text(original, encoding="utf-8")
    values = dict(zip(KEYS, ("fake-client-identifier", "a" * 64, "b" * 64)))
    save_keys(values, tmp_path)
    result = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "YOLO_DEVICE=cpu\n" in result and "LH25_PAYOS_ENABLED=false\n" in result
    assert all(result.count(key + "=") == 1 for key in KEYS)
    assert all(key + "=" + value in result for key, value in values.items())
    backups = list((tmp_path / "runtime/backups").glob("env-payos-*.txt"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == original


def test_import_rejects_incomplete_or_multiline_values_without_changing_env(tmp_path):
    (tmp_path / ".env").write_text("UNCHANGED=true\n", encoding="utf-8")
    with pytest.raises(ValueError):
        save_keys({KEYS[0]: "a" * 32}, tmp_path)
    values = {key: "a" * 32 for key in KEYS}
    values[KEYS[1]] = "a" * 32 + "\nLH25_PAYOS_ENABLED=true"
    with pytest.raises(ValueError):
        save_keys(values, tmp_path)
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "UNCHANGED=true\n"


def test_gmail_import_preserves_payment_flags_and_rejects_sender_mismatch(tmp_path):
    original = "LH25_PAYOS_ENABLED=false\nLH25_PAYOS_API_KEY=preserved\n"
    (tmp_path / ".env").write_text(original, encoding="utf-8")
    values = {"SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "465", "SMTP_USER": "owner@gmail.com",
              "SMTP_FROM": "owner@gmail.com", "SMTP_PASSWORD": "abcd efgh ijkl mnop"}
    save_gmail(values, tmp_path)
    result = (tmp_path / ".env").read_text(encoding="utf-8")
    assert original in result and "SMTP_PASSWORD=abcdefghijklmnop\n" in result
    with pytest.raises(ValueError):
        save_gmail({**values, "SMTP_FROM": "other@gmail.com"}, tmp_path)
    assert (tmp_path / ".env").read_text(encoding="utf-8") == result
