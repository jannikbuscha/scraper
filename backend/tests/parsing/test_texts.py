"""Document text normalisation, hashing, snippets and sentences (parsing/texts.py)."""

from __future__ import annotations

import hashlib

from mdt.collectors.parsing.texts import (
    clip_quote,
    collapse_whitespace,
    normalize_document_text,
    sentence_spans,
    snippet,
    text_hash,
)


def test_normalize_document_text_applies_every_rule() -> None:
    raw = "  éxample\r\nline two  \t\rline\x00 three\x07\n\n\n\n\nend\t \n  "
    assert normalize_document_text(raw) == "éxample\nline two\nline three\n\nend"


def test_normalize_document_text_keeps_tabs_inside_lines_and_single_blank_lines() -> None:
    assert normalize_document_text("a\tb\n\nc") == "a\tb\n\nc"


def test_text_hash_is_the_sha256_of_the_utf8_bytes() -> None:
    text = "Приклад тексту"
    assert text_hash(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_collapse_whitespace_handles_unicode_spaces_and_line_breaks() -> None:
    assert collapse_whitespace(" a  b\n\n c\t") == "a b c"


def test_snippet_takes_context_on_both_sides_and_collapses_whitespace() -> None:
    text = "x" * 200 + " match\nhere " + "y" * 200
    start = text.index("match")
    result = snippet(text, start, start + 5, context=10)
    # 10 characters on each side: "xxxxxxxxx " before, "\nhere yyyy" after.
    assert result == "xxxxxxxxx match here yyyy"


def test_snippet_at_the_text_edges() -> None:
    assert snippet("match", 0, 5) == "match"


def test_clip_quote_keeps_a_prefix_without_ellipsis() -> None:
    assert clip_quote("abcdef", 3) == "abc"
    assert len(clip_quote("a" * 1500)) == 1000


def _sentences(text: str) -> list[str]:
    return [text[start:end] for start, end in sentence_spans(text)]


def test_sentences_split_at_line_breaks_and_end_punctuation() -> None:
    text = "Перше речення. Друге речення! Третє? Четверте… П'яте\nШосте"
    assert _sentences(text) == [
        "Перше речення.",
        "Друге речення!",
        "Третє?",
        "Четверте…",
        "П'яте",
        "Шосте",
    ]


def test_dots_inside_names_do_not_split() -> None:
    text = "Дія.City запрацювала. Дія.Бізнес теж."
    assert _sentences(text) == ["Дія.City запрацювала.", "Дія.Бізнес теж."]


def test_sentence_offsets_point_into_the_stored_text() -> None:
    text = "  Перше.   Друге  \n\n Третє "
    spans = sentence_spans(text)
    assert [text[start:end] for start, end in spans] == ["Перше.", "Друге", "Третє"]
    assert spans[0] == (2, 8)


def test_repeated_punctuation_and_text_without_a_final_dot() -> None:
    assert _sentences("Що?! Так") == ["Що?!", "Так"]
    assert sentence_spans("") == []
    assert sentence_spans(" \n ") == []
