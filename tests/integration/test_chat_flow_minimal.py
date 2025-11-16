from app.handlers.chat import _enforce_plaintext_ukrainian, _safe_html_payload


def test_chat_flow_plaintext_payload_generation():
    # Simulate model output with markdown and HTML mixed
    model_output = "<b>Привіт</b>, **світ**! `code`"
    cleaned = _enforce_plaintext_ukrainian(model_output)
    payload = _safe_html_payload(cleaned, already_html=False)
    assert "<b>" not in payload and "**" not in payload and "`" not in payload
    # Ensure non-empty and contains Ukrainian text
    assert "Привіт, світ!" in payload


