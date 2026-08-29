from __future__ import annotations

from autosub_zh.models import BilingualSubtitleStyle, Segment, Word
from autosub_zh.timing import refine_timing


def make_segment(text: str, timings: list[tuple[str, float, float]]) -> Segment:
    return Segment(
        id=1,
        start=timings[0][1],
        end=timings[-1][2],
        source_text=text,
        words=[Word(word=word, start=start, end=end) for word, start, end in timings],
    )


def test_sentence_boundary_split_uses_short_pause() -> None:
    segment = make_segment(
        "It is late. The city sleeps.",
        [
            ("It", 0.0, 0.1),
            ("is", 0.1, 0.2),
            ("late.", 0.2, 0.6),
            ("The", 0.9, 1.0),
            ("city", 1.0, 1.25),
            ("sleeps.", 1.25, 1.7),
        ],
    )

    refined = refine_timing([segment], style=BilingualSubtitleStyle(en_max_single_line_chars=78))

    assert [item.source_text for item in refined] == ["It is late.", "The city sleeps."]
    assert refined[0].end == 0.6
    assert refined[1].start == 0.9


def test_open_fragment_merges_with_following_sentence_tail() -> None:
    segments = [
        make_segment(
            "The silence is only broken by the mechanical",
            [
                ("The", 3.22, 3.3),
                ("silence", 3.3, 3.78),
                ("is", 3.78, 3.98),
                ("only", 3.98, 4.2),
                ("broken", 4.2, 4.52),
                ("by", 4.52, 4.82),
                ("the", 4.82, 4.96),
                ("mechanical", 4.96, 5.4),
            ],
        ),
        make_segment(
            "clicking of an old typewriter.",
            [
                ("clicking", 5.48, 5.76),
                ("of", 5.76, 6.18),
                ("an", 6.18, 6.32),
                ("old", 6.32, 6.62),
                ("typewriter.", 6.62, 7.34),
            ],
        ),
    ]

    refined = refine_timing(segments, style=BilingualSubtitleStyle(en_max_single_line_chars=78))

    assert [item.source_text for item in refined] == [
        "The silence is only broken by the mechanical clicking of an old typewriter."
    ]
    assert refined[0].start == 3.22
    assert refined[0].end == 7.34


def test_display_limits_do_not_split_readable_complete_sentence() -> None:
    segment = make_segment(
        "Dmitri doesn't know it yet, but it's waiting outside of his apartment.",
        [
            ("Dmitri", 19.08, 19.56),
            ("doesn't", 19.56, 19.98),
            ("know", 19.98, 20.14),
            ("it", 20.14, 20.26),
            ("yet,", 20.26, 20.5),
            ("but", 20.66, 20.74),
            ("it's", 20.74, 20.92),
            ("waiting", 20.92, 21.22),
            ("outside", 21.3, 21.82),
            ("of", 21.82, 22.02),
            ("his", 22.02, 22.14),
            ("apartment.", 22.14, 22.66),
        ],
    )

    refined = refine_timing([segment], style=BilingualSubtitleStyle(en_max_single_line_chars=78))

    assert len(refined) == 1
    assert refined[0].source_text == segment.source_text


def test_terminal_single_word_tail_is_absorbed() -> None:
    segments = [
        make_segment(
            "that was made into an even more famous video game",
            [
                ("that", 97.67, 97.82),
                ("was", 97.82, 98.0),
                ("made", 98.0, 98.22),
                ("into", 98.22, 98.46),
                ("an", 98.46, 98.58),
                ("even", 98.58, 98.86),
                ("more", 98.86, 99.1),
                ("famous", 99.1, 99.46),
                ("video", 99.46, 99.9),
                ("game", 99.9, 100.29),
            ],
        ),
        make_segment(
            "franchise.",
            [
                ("franchise.", 100.37, 102.37),
            ],
        ),
    ]

    refined = refine_timing(segments, style=BilingualSubtitleStyle(en_max_single_line_chars=42))

    assert [item.source_text for item in refined] == [
        "that was made into an even more famous video game franchise."
    ]
    assert refined[0].start == 97.67
    assert refined[0].end == 102.37


def test_terminal_single_word_tail_respects_strong_pause() -> None:
    segments = [
        make_segment(
            "that was made into an even more famous video game",
            [
                ("that", 0.0, 0.15),
                ("was", 0.15, 0.3),
                ("made", 0.3, 0.5),
                ("into", 0.5, 0.7),
                ("an", 0.7, 0.85),
                ("even", 0.85, 1.05),
                ("more", 1.05, 1.2),
                ("famous", 1.2, 1.45),
                ("video", 1.45, 1.8),
                ("game", 1.8, 2.0),
            ],
        ),
        make_segment("franchise.", [("franchise.", 3.31, 3.8)]),
    ]

    refined = refine_timing(segments, style=BilingualSubtitleStyle(en_max_single_line_chars=42))

    assert [item.source_text for item in refined] == [
        "that was made into an even more famous video game",
        "franchise.",
    ]


def test_adjacent_short_complete_sentences_are_not_tail_merged() -> None:
    segments = [
        make_segment("Hello.", [("Hello.", 0.0, 0.7)]),
        make_segment("Goodbye.", [("Goodbye.", 0.85, 1.4)]),
    ]

    refined = refine_timing(segments, style=BilingualSubtitleStyle(en_max_single_line_chars=42))

    assert [item.source_text for item in refined] == ["Hello.", "Goodbye."]


def test_lowercase_tail_after_suspicious_terminal_is_absorbed() -> None:
    segments = [
        make_segment(
            "These are rare and go for a lot of money on the property.",
            [
                ("These", 0.0, 0.15),
                ("are", 0.15, 0.3),
                ("rare", 0.3, 0.55),
                ("and", 0.55, 0.7),
                ("go", 0.7, 0.85),
                ("for", 0.85, 1.0),
                ("a", 1.0, 1.1),
                ("lot", 1.1, 1.25),
                ("of", 1.25, 1.4),
                ("money", 1.4, 1.7),
                ("on", 1.7, 1.85),
                ("the", 1.85, 2.0),
                ("property.", 2.0, 2.25),
            ],
        ),
        make_segment("market.", [("market.", 2.33, 2.8)]),
    ]

    refined = refine_timing(segments, style=BilingualSubtitleStyle(en_max_single_line_chars=42))

    assert [item.source_text for item in refined] == [
        "These are rare and go for a lot of money on the property market."
    ]


def test_standalone_discourse_particle_is_not_tail_merged() -> None:
    segments = [
        make_segment(
            "I don't know.",
            [
                ("I", 0.0, 0.1),
                ("don't", 0.1, 0.35),
                ("know.", 0.35, 0.7),
            ],
        ),
        make_segment("Yeah.", [("Yeah.", 1.0, 1.35)]),
    ]

    refined = refine_timing(segments, style=BilingualSubtitleStyle(en_max_single_line_chars=42))

    assert [item.source_text for item in refined] == ["I don't know.", "Yeah."]


def test_question_response_particle_is_not_tail_merged() -> None:
    segments = [
        make_segment(
            "Are you coming?",
            [
                ("Are", 0.0, 0.12),
                ("you", 0.12, 0.25),
                ("coming?", 0.25, 0.7),
            ],
        ),
        make_segment("No.", [("No.", 1.0, 1.2)]),
    ]

    refined = refine_timing(segments, style=BilingualSubtitleStyle(en_max_single_line_chars=42))

    assert [item.source_text for item in refined] == ["Are you coming?", "No."]


def test_two_word_discourse_particle_is_not_tail_merged() -> None:
    segments = [
        make_segment(
            "I can do it.",
            [
                ("I", 0.0, 0.1),
                ("can", 0.1, 0.22),
                ("do", 0.22, 0.35),
                ("it.", 0.35, 0.6),
            ],
        ),
        make_segment("All right.", [("All", 0.9, 1.05), ("right.", 1.05, 1.25)]),
    ]

    refined = refine_timing(segments, style=BilingualSubtitleStyle(en_max_single_line_chars=42))

    assert [item.source_text for item in refined] == ["I can do it.", "All right."]


def test_particle_word_after_open_fragment_is_absorbed_as_content_tail() -> None:
    segments = [
        make_segment(
            "The answer is",
            [
                ("The", 0.0, 0.1),
                ("answer", 0.1, 0.35),
                ("is", 0.35, 0.55),
            ],
        ),
        make_segment("no.", [("no.", 0.62, 0.82)]),
    ]

    refined = refine_timing(segments, style=BilingualSubtitleStyle(en_max_single_line_chars=42))

    assert [item.source_text for item in refined] == ["The answer is no."]
