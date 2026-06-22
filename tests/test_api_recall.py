from core.settings import load_settings, save_settings

def test_pidx_settings_defaults_and_patch():
    s = load_settings()
    for k in ("pidx_enabled", "pidx_mail", "pidx_note", "pidx_journal", "pidx_contact", "pidx_read", "pidx_book"):
        assert s.get(k) is True
    save_settings({"pidx_mail": False})
    assert load_settings().get("pidx_mail") is False
    save_settings({"pidx_mail": True})  # restore
