import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/instagram-scraper/skills/instagram-scraper/scripts"))

from iglib.frames import est_tokens, patches  # noqa: E402
from iglib.ocr import canonicalize, clean, spans  # noqa: E402
from iglib.videomap import _assign  # noqa: E402
from iglib.segments import segment, split  # noqa: E402


def test_split_uses_first_frame_as_anchor():
    # each step differs by 1 bit from the previous; drift accumulates
    hs = [0, 1, 3, 7, 15, 31]
    assert split(hs, 2) == [(0, 2), (3, 5)]


def test_split_color_cut_with_same_structure():
    hs = [5, 5, 5, 5]
    red, green = (200, 30, 30) * 16, (30, 120, 40) * 16
    assert split(hs, 10) == [(0, 3)]
    assert split(hs, 10, [red, red, green, green]) == [(0, 1), (2, 3)]


def test_split_single_and_empty():
    assert split([], 5) == []
    assert split([42], 5) == [(0, 0)]


def test_segment_caps_count():
    hs = [0, (1 << 64) - 1] * 20  # alternating, max distance
    segs, th = segment(hs, 10, max_segments=5)
    assert len(segs) <= 5 and th >= 64


def _r(*txts, s=0.95):
    return [(t, s) for t in txts]


def test_canonicalize_groups_misreads():
    texts = [_r("WITH BERTIE GREGORY"), _r("MIN BERTIE GREGORT"), _r("WITH BERTIE GREGORY"),
             _r("WIN BERTIE GREGORY"), _r("SALE 5O%"), _r("SALE 50%"), _r("SALE 50%")]
    out, sizes = canonicalize(texts)
    names = {t for lines in out for t, _ in lines}
    assert names == {"WITH BERTIE GREGORY", "SALE 50%"}
    assert sizes["WITH BERTIE GREGORY"] == 4


def test_canonicalize_folds_fragments():
    texts = [_r("WITH BERTIE GREGORY", "Disney+ hulu")] * 5 + [_r("TIE GRECORY", "hulu")] * 2
    out, _ = canonicalize(texts)
    assert {t for lines in out for t, _ in lines} == {"WITH BERTIE GREGORY", "Disney+ hulu"}


def test_spans_tolerate_short_gaps():
    times = [0.0, 0.2, 0.4, 0.6, 0.8]
    texts = [_r("HELLO"), [], _r("HELLO"), [], []]
    sp = spans(times, texts, 0.2, max_gap=2)
    assert [(s["start"], s["end"], s["text"]) for s in sp] == [(0.0, 0.6, "HELLO")]


def test_clean_drops_singleton_noise_and_splits_persistent():
    times = [i * 0.2 for i in range(10)]          # 2 s video sampled at 5 fps
    raw = [_r("LOGO TV") for _ in range(10)]       # on screen the whole time
    raw[3] = raw[3] + [("xq", 0.7)]                # one-off garbage
    raw[5] = raw[5] + _r("CODE REEF50")            # 2-sample flash (0.3 s)
    raw[6] = raw[6] + _r("CODE REEF50")
    res = clean(times, raw, 0.2, duration=2.0)
    assert res["persistent"] == ["LOGO TV"]
    assert [s["text"] for s in res["spans"]] == ["CODE REEF50"]


def test_clean_keeps_confident_single_frame_flash():
    raw = [[], _r("BUY NOW", s=0.97), [], [], []]
    res = clean([0.0, 0.2, 0.4, 0.6, 0.8], raw, 0.2, duration=10.0)
    assert [s["text"] for s in res["spans"]] == ["BUY NOW"]


def test_assign_speech_to_max_overlap():
    speech = [{"start": 0.0, "end": 3.0, "text": "a"}, {"start": 2.5, "end": 4.0, "text": "b"}]
    assert _assign(speech, [(0.0, 1.0), (1.0, 3.5), (3.5, 5.0)]) == [[], ["a", "b"], []]


def test_token_math():
    assert patches(28, 28) == 1
    assert patches(29, 28) == 2
    assert est_tokens(432, 768) == 16 * 28
    assert est_tokens(4000, 4000) == 1568
