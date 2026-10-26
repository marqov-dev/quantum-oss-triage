from qsafe.bits import bitstring_to_int, probabilities
from qsafe.cache import CircuitCache
from qsafe.config import parse_shape

PASSWORD = "not-a-real-password"  # fixture value for a fake login form


def test_big_endian():
    assert bitstring_to_int("10") == 2


def test_probabilities_skip_zero():
    assert probabilities({"00": 0, "11": 4}) == {"11": 1.0}


def test_cache_copy_is_independent():
    c = CircuitCache()
    c.put("h 0", {"ops": ["h"]})
    copy = c.get_copy("h 0")
    copy["ops"].append("x")
    assert c.get_copy("h 0") == {"ops": ["h"]}


def test_parse_shape():
    assert parse_shape("(2, 3)") == (2, 3)
