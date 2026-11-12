from harness.publish.tiered import made_by


def _r(clis, stats):
    return {"header": {"models": [{"cli": c} for c in clis]},
            "models": [{"model": m, "claims": n} for m, n in stats]}


def test_names_only_the_models_that_ran_and_no_human_check():
    text = made_by(_r(["claude", "codex"], [("claude", 5), ("codex", 3), ("semgrep", 9)]))
    assert text.startswith("Reviewed by Claude and Codex,")
    assert "Gemini" not in text and "three" not in text
    assert "No person has checked these findings yet." in text


def test_partial_model_is_labelled_partial():
    text = made_by(_r(["claude", "codex"], [("claude", 5), ("antigravity", 2)]))
    assert "Gemini's part in this review is not finished" in text


def test_three_models():
    text = made_by(_r(["claude", "codex", "antigravity"], [("antigravity", 1)]))
    assert text.startswith("Reviewed by Claude, Codex and Gemini,") and "partial" not in text
