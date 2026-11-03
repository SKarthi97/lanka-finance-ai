from app.services.categorizer import CATEGORIES, description_stem
from app.tools.eval_categorizer import load_cases


def test_eval_set_is_valid_and_synthetic():
    cases = load_cases()
    names = {name for name, _ in CATEGORIES}
    assert len(cases) >= 30
    assert all(category in names for _, category in cases)
    assert len({description for description, _ in cases}) == len(cases)  # no duplicates
    # descriptions are plain words (no digits), so they double as stems
    assert all(not any(ch.isdigit() for ch in d) for d, _ in cases)
    assert all(description_stem(d) for d, _ in cases)
