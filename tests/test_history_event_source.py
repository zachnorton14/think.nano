from dev.history_event.config import PAPER_DECADE_COUNTS, PAPER_DECADES
from dev.history_event.source import (
    FOUR_DIGIT_RE,
    compare_to_paper,
    parse_page,
    visible_text,
)
from dev.history_event.io import iter_jsonl
from dev.history_event.config import PipelinePaths
from dev.history_event import source


WIKI_18 = """
==[[1700s (decade)|1700s]]==
* [[1700]]–[[1702]]: A first event.<ref>citation</ref>
* 1701: A ''second'' [[Event|event]].
* Malformed bullet without a year.
==See also==
* 1702: Not chronological.
"""

WIKI_20 = """
==[[1900s]]==
===[[1901]]===
* [[January 1]]: The first event.<ref name="x" />
* [[March 2]]–[[March 3|3]]: A two-day event.
* Parent event.
** Supporting detail, not a separate event.
* [[April 4]]:
** Nested event.
===1902–1903===
* 1902–1904: A ranged description.
==References==
* Not an event.
"""


def test_18th_century_uses_leading_year_and_range_start():
    rows = parse_page(WIKI_18, century=18, profile="top_level")
    assert [(row["event_year"], row["event_description"]) for row in rows] == [
        (1700, "A first event"),
        (1701, "A second event"),
    ]


def test_later_pages_use_heading_year_strip_dates_and_handle_nested_lists():
    top = parse_page(WIKI_20, century=20, profile="top_level")
    events = parse_page(WIKI_20, century=20, profile="event_bullets")
    nested = parse_page(WIKI_20, century=20, profile="all_event_bullets")
    assert [row["event_year"] for row in top] == [1901, 1901, 1901, 1902]
    assert top[0]["event_description"] == "The first event"
    assert top[1]["event_description"] == "A two-day event"
    assert top[-1]["event_description"] == "1902–1904: A ranged description"
    assert len(events) == len(top) + 1
    assert len(nested) == len(events) + 1
    assert events[-2]["event_description"] == "Nested event"


def test_18th_century_excludes_decade_only_dates_and_keeps_boundary_heading():
    wiki = """
==1790s==
* 1790s: A decade-wide trend.
* 1799: A precise event.
==1800==
* A boundary event.
"""
    rows = parse_page(wiki, century=18, profile="event_bullets")
    assert [(row["event_year"], row["event_description"]) for row in rows] == [
        (1799, "A precise event"),
        (1800, "A boundary event"),
    ]


def test_visible_text_removes_markup_and_citations():
    assert visible_text("[[Target|Shown]] {{small|hidden}} <ref>x</ref> &amp; ''plain''") == "Shown & plain"


def test_four_digit_filter_has_digit_boundaries():
    assert FOUR_DIGIT_RE.findall("Treaty signed in 1901; code 12001 is not a year") == ["1901"]
    assert FOUR_DIGIT_RE.findall("There were 999 objects") == []


def test_figure_four_vector_is_fixed_and_discrepancies_are_exact():
    assert len(PAPER_DECADES) == len(PAPER_DECADE_COUNTS) == 33
    assert sum(PAPER_DECADE_COUNTS) == 2344
    rows = [{"event_year": decade} for decade, count in zip(PAPER_DECADES, PAPER_DECADE_COUNTS) for _ in range(count)]
    report = compare_to_paper(rows)
    assert report["exact_match"] is True
    rows.pop()
    report = compare_to_paper(rows)
    assert report["row_count_difference"] == -1
    assert report["decade_differences"]["2020"] == -1


def test_prepare_has_stable_order_ids_and_source_hashes(tmp_path, monkeypatch):
    pages = (
        {"century": 18, "title": "Eighteenth", "revision": 1},
        {"century": 19, "title": "Nineteenth", "revision": 2},
    )
    paths = PipelinePaths(tmp_path)
    paths.raw_dir.mkdir(parents=True)
    (paths.raw_dir / "timeline-18-oldid-1.wiki").write_text(
        "==1700s==\n* 1701: Earlier.\n* 1702: Later.\n", encoding="utf-8"
    )
    (paths.raw_dir / "timeline-19-oldid-2.wiki").write_text(
        "==1800s==\n===1801===\n* Last.\n", encoding="utf-8"
    )
    monkeypatch.setattr(source, "SOURCE_PAGES", pages)
    source.prepare(paths)
    first = list(iter_jsonl(paths.events))
    source.prepare(paths)
    second = list(iter_jsonl(paths.events))
    assert first == second
    assert [row["id"] for row in first] == [
        "history-event-000000", "history-event-000001", "history-event-000002"
    ]
    assert len({row["source_hash"] for row in first}) == 3
