from pipeline.parsing.body import (content_type_implies_attachment, find_attachments,
                                   normalize_for_similarity, split_body)

OUTLOOK_BLOCK = " -----Original Message-----\nFrom: \tX\nSubject:\tY\n\nolder text"
LOTUS_BLOCK = "---------------------- Forwarded by A B/HOU/ECT on 05/04/2001 \n10:18 AM ------\nold"


def test_no_markers():
    assert split_body("  hello\nworld \n") == ("hello\nworld", None, None)


def test_outlook_reply_goes_to_quoted():
    primary, fwd, quoted = split_body("my reply\n\n" + OUTLOOK_BLOCK, "RE: x")
    assert primary == "my reply"
    assert fwd is None
    assert quoted.startswith("-----Original Message-----") and quoted.endswith("older text")


def test_outlook_with_fw_subject_goes_to_forwarded():
    primary, fwd, quoted = split_body("FYI\n" + OUTLOOK_BLOCK, "FW: x")
    assert (primary, quoted) == ("FYI", None)
    assert fwd.startswith("-----Original Message-----")
    assert split_body("FYI\n" + OUTLOOK_BLOCK, "Fwd: x")[1] is not None


def test_lotus_forward():
    primary, fwd, quoted = split_body("see below\n" + LOTUS_BLOCK, "Alroy")
    assert primary == "see below" and quoted is None
    assert fwd.startswith("---------------------- Forwarded by")


def test_first_marker_wins_nested():
    body = "top\n" + OUTLOOK_BLOCK + "\n" + LOTUS_BLOCK
    primary, fwd, quoted = split_body(body, "RE: x")
    assert fwd is None and "Forwarded by" in quoted
    body = "top\n" + LOTUS_BLOCK + "\n" + OUTLOOK_BLOCK
    primary, fwd, quoted = split_body(body, "RE: x")
    assert quoted is None and "Original Message" in fwd


def test_short_dash_lotus_variant():
    assert split_body("x\n----- Forwarded by J T/Houston/Eott on 10/23/2001 -----\ny")[1].startswith("-----")


def test_spaced_outlook_variant():
    assert split_body("x\n----- Original Message -----\nFrom: a", "RE: y")[2].startswith("-----")


def test_gt_lines_before_marker_go_to_quoted():
    primary, fwd, quoted = split_body("Family,\nenjoy\n> line one\n>\n> line two")
    assert primary == "Family,\nenjoy"
    assert quoted == "> line one\n>\n> line two"


def test_marker_only_body_has_empty_primary():
    primary, fwd, _ = split_body(LOTUS_BLOCK)
    assert primary == "" and fwd


def test_attachment_refs_lotus_and_outlook():
    body = "see <<271595.DOC>> and <<271595.WPD>>\n << File: Month End Close -November.doc >> \n<<271595.DOC>>"
    assert find_attachments(body) == ["271595.DOC", "271595.WPD", "Month End Close -November.doc"]


def test_attachment_mailto_and_urls_excluded():
    body = ("<< File: mailto:rickyhood28@hotmail.com >>\n<< File: x@y.com >>\n<<http://a.com/b.htm>>\n"
            " - storm11_0126.JPG << File: storm11_0126.JPG >> ")
    assert find_attachments(body) == ["storm11_0126.JPG"]


def test_attachment_dash_listing():
    body = "Attached is the file.\n - 010981 SCAN-01.jpg\n - API.pdf\n - see www.enron.com\n - not a file"
    assert find_attachments(body) == ["010981 SCAN-01.jpg", "API.pdf"]


def test_no_attachments():
    assert find_attachments("please see attached") == []


def test_content_type_attachment():
    assert content_type_implies_attachment("multipart/mixed; boundary=x")
    assert content_type_implies_attachment('application/pdf; name="a.pdf"')
    assert not content_type_implies_attachment("text/plain; charset=us-ascii")
    assert not content_type_implies_attachment(None)


def test_normalize_for_similarity_cleans_qp_only_there():
    raw = "Sorry=20\nplease note=\n the  attached\n=09=3D"
    assert normalize_for_similarity(raw) == "Sorry please note the attached ="
    assert normalize_for_similarity(None) == ""
