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
