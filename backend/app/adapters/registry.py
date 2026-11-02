from app.adapters.base import BankAdapter
from app.adapters.boc import BocAdapter

# One adapter per bank, added one at a time (HNB, Commercial, Sampath later).
ADAPTERS: dict[str, BankAdapter] = {
    adapter.code: adapter for adapter in (BocAdapter(),)
}

IDENTIFY_THRESHOLD = 0.5


def select_adapter(pages: list[str], bank_code: str | None = None) -> BankAdapter | None:
    """A bank chosen by the user wins (manual override). Otherwise the best-scoring
    adapter above the threshold, or None for an unrecognised layout."""
    if bank_code:
        return ADAPTERS.get(bank_code)

    best, best_score = None, 0.0
    for adapter in ADAPTERS.values():
        score = adapter.identify(pages)
        if score > best_score:
            best, best_score = adapter, score
    return best if best_score >= IDENTIFY_THRESHOLD else None
