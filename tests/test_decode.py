from pipeline.parsing.decode import decode_bytes


def test_ascii():
    assert decode_bytes(b"Subject: hi\r\n\r\nbody") == "Subject: hi\r\n\r\nbody"


def test_utf8():
    assert decode_bytes("café".encode("utf-8")) == "café"


def test_cp1252_smart_quote():
    assert decode_bytes(b"it\x92s") == "it’s"


def test_invalid_bytes_never_raise():
    # 0x81 is undefined in cp1252 -> falls through to latin-1
    assert decode_bytes(b"a\x81b") == "a\x81b"
