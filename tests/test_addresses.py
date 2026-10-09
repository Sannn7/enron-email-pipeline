import pytest

from pipeline.parsing.addresses import parse_address_list


@pytest.mark.parametrize("value,expected", [
    ("a@enron.com", ["a@enron.com"]),
    ("A.B@Enron.COM, c@x.com", ["a.b@enron.com", "c@x.com"]),
    ('"Lavorato, John" <John.Lavorato@enron.com>, x@y.com', ["john.lavorato@enron.com", "x@y.com"]),
    ("Mark Woita <Mark.Woita@FHLBTopeka.com>", ["mark.woita@fhlbtopeka.com"]),
    ("terry'.'ed@enron.com, camp'.'howard@enron.com", ["terry'.'ed@enron.com", "camp'.'howard@enron.com"]),
    ("'/o=enron/ou=na/cn=recipients/cn=notesaddr/cn=4f62'@enron.com",
     ["'/o=enron/ou=na/cn=recipients/cn=notesaddr/cn=4f62'@enron.com"]),
    ('"beckyp@bammel.org"@ENRON', ['"beckyp@bammel.org"@enron']),
    ("John M Singer/Corp/Enron@ENRON", ["john m singer/corp/enron@enron"]),            # Lotus name
    ("Paul Smith/ENRON_DEVELOPMENT@ENRON_DEVELOPMENT, Paul Quilkey/ENRON_DEVELOPMENT@ENRON_DEVELOPMENT",
     ["paul smith/enron_development@enron_development", "paul quilkey/enron_development@enron_development"]),
    ("undisclosed-recipients:;", []),                                                  # group syntax
    ("", []),
    (" , ,", []),
    ("x@y.com (Some Comment)", ["x@y.com"]),
    ("Empty <>", []),
])
def test_parse(value, expected):
    assert parse_address_list(value) == expected


def test_multiple_header_values_and_order():
    assert parse_address_list(["b@x.com, a@x.com", "c@x.com"]) == ["b@x.com", "a@x.com", "c@x.com"]


def test_none():
    assert parse_address_list(None) == []
