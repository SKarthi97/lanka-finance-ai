"""Checks on free text written by the local model, before anyone sees it.

The model is used to PHRASE facts that code computed; it must not add facts. Two cheap, strict
checks catch the dangerous kind of invention (a number or an amount):

* every number in the text must already appear in the facts it was given (so it can repeat "down
  18%" but cannot make up "down 25%"), and
* it must not mention money (LKR, Rs, a currency sign), because amounts are written by code.

A text that fails is dropped and the plain code-written version is shown instead.
"""

import re

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_MONEY = re.compile(r"\b(?:lkr|rs\.?|rupees?)\b|[$€£₹]", re.IGNORECASE)


def numbers_in(text: str) -> set[str]:
    return set(_NUMBER.findall(text))


def only_given_numbers(output: str, facts: str) -> bool:
    """True when every number in `output` also appears in `facts`."""
    return numbers_in(output) <= numbers_in(facts)


def mentions_money(output: str) -> bool:
    return _MONEY.search(output) is not None


def clean(output: str | None, facts: str, max_length: int) -> str | None:
    """The text with whitespace tidied, or None if it breaks a rule."""
    if not output:
        return None
    text = " ".join(output.split())
    if not text or len(text) > max_length:
        return None
    if mentions_money(text) or not only_given_numbers(text, facts):
        return None
    if any(mark in text for mark in ("{", "}", "<", ">", "```")):  # a leftover template or markup
        return None
    return text
