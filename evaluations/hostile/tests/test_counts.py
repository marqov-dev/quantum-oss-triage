from qhost.counts import most_likely


def test_most_likely():
    assert most_likely({"00": 3, "11": 9}) == "11"
