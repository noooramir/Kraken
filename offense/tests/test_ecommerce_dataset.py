"""Checks that the e-commerce dataset is well formed and that the attack is actually retrievable.
No LLM, no network. Needs offense/datasets/ (built by `python -m offense.prepare_ecommerce`)."""
import json

import pytest

from offense import prepare_ecommerce as pe
from offense import ragpoison as rp


def test_parse_lines_reads_labels_and_ignores_unlabelled():
    lines = ["[t]great camera", "picture quality[+3]##the picture quality is superb .",
             "battery life[-2],use[+1]##battery life is short but it is easy to use",
             "##no label on this sentence", "size[+2][u]##tiny", "*** comment line"]
    got = pe.parse_lines(lines)
    assert ("picture quality", 3, "the picture quality is superb .") in got
    assert ("battery life", -2, "battery life is short but it is easy to use") in got
    assert ("use", 1, "battery life is short but it is easy to use") in got
    assert ("size", 2, "tiny") in got
    assert len(got) == 4


def test_tidy_only_fixes_spacing():
    assert pe.tidy("it 's great , really ( very ) good !") == "It's great, really (very) good!"


def _rows(feat, signs):
    return [(feat, s, f"the {feat} was really quite something number {i} here") for i, s in enumerate(signs)]


def test_build_targets_requires_agreement_and_volume():
    prods = {"Acme phone": _rows("battery", [2] * 7 + [-1])           # 7/8 agree -> kept
             + _rows("screen", [2, -2, 2, -2, 2, -2, 2, -2])          # 50/50 -> ambiguous, dropped
             + _rows("antenna", [1, 1])}                              # too few -> dropped
    t, ids, texts = pe.build_targets(prods)
    feats = {v["feature"] for v in t.values()}
    assert feats == {"battery"}
    q = next(iter(t.values()))
    assert q["correct answer"] == "positive" and q["incorrect answer"] == "negative"
    assert len(q["adv_texts"]) == 5 and all(a.startswith(q["question"]) for a in q["adv_texts"])
    assert len(ids[q["id"]]) == 5


DATA = rp.DATA
pytestmark_data = pytest.mark.skipif(not (DATA / "ecom.json").exists(), reason="run python -m offense.prepare_ecommerce first")


@pytestmark_data
def test_dataset_schema_and_ground_truth():
    d = rp.load_dataset("ecom")
    assert len(d) >= 50
    for q in d:
        assert q["correct"] in ("positive", "negative") and q["incorrect"] in ("positive", "negative")
        assert q["correct"] != q["incorrect"]
        assert len(q["clean_texts"]) == 5 and len(q["adv_texts"]) == 5
        assert all(a.startswith(q["question"]) for a in q["adv_texts"])
        assert all(q["incorrect"] in a.lower() for a in q["adv_texts"])        # poison states the target answer
        assert q["correct"] not in " ".join(q["adv_texts"]).lower().replace(q["question"].lower(), "")


@pytestmark_data
def test_every_question_has_real_evidence():
    t = json.loads((DATA / "ecom.json").read_text(encoding="utf-8"))
    for v in t.values():
        assert v["evidence"]["labelled_sentences"] >= pe.MIN_MENTIONS
        assert v["evidence"]["agree_share"] >= pe.MIN_AGREE


@pytestmark_data
def test_poison_is_retrievable_but_not_trivially_everything():
    d = rp.load_dataset("ecom")
    hit = 0
    for q in d:
        pool = [(t, False) for t in q["clean_texts"]] + [(t, True) for t in q["adv_texts"]]
        hit += any(p for _, p in rp.retrieve(q["question"], pool, 5))
    assert hit / len(d) > 0.9, "poison must reach the LLM, otherwise the benchmark only measures retrieval"
