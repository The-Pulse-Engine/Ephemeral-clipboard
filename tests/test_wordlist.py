import secrets

import pytest

from eclip import wordlist


def test_wordlist_has_256_unique_lowercase_words() -> None:
    assert len(wordlist.WORDLIST) == 256
    assert len(set(wordlist.WORDLIST)) == 256
    assert all(word.isascii() and word.islower() for word in wordlist.WORDLIST)


def test_generate_code_uses_secrets_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    choices = iter(("guitar", "orbit"))
    calls = 0

    def choose(words: tuple[str, ...]) -> str:
        nonlocal calls
        calls += 1
        assert words is wordlist.WORDLIST
        return next(choices)

    monkeypatch.setattr(secrets, "choice", choose)

    assert wordlist.generate_code("7") == "7-guitar-orbit"
    assert calls == 2


def test_parse_code_returns_nameplate_and_words() -> None:
    assert wordlist.parse_code("7-guitar-orbit") == ("7", "guitar", "orbit")


@pytest.mark.parametrize(
    "code",
    (
        "7-guitar-unknown",
        "guitar-orbit",
        "7-guitar",
        "7-guitar-orbit-extra",
        "7-guitar-orbit ",
        " 7-guitar-orbit",
        "7-Guitar-orbit",
    ),
)
def test_parse_code_rejects_invalid_input(code: str) -> None:
    with pytest.raises(ValueError):
        wordlist.parse_code(code)


@pytest.mark.parametrize("nameplate", ("", "-1", "７", "room"))
def test_generate_code_rejects_non_ascii_numeric_nameplate(nameplate: str) -> None:
    with pytest.raises(ValueError, match="ASCII digits"):
        wordlist.generate_code(nameplate)
