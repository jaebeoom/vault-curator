from vault_curator import local_client


def test_extract_message_text_accepts_string_content() -> None:
    assert local_client._extract_message_text('{"ok": true}') == '{"ok": true}'


def test_extract_message_text_accepts_dict_content() -> None:
    assert (
        local_client._extract_message_text({"text": '{"ok": true}'})
        == '{"ok": true}'
    )


def test_extract_message_text_accepts_list_variants() -> None:
    content = [
        {"type": "output_text", "text": '{"ok": '},
        {"content": "true}"},
    ]

    assert local_client._extract_message_text(content) == '{"ok": true}'
