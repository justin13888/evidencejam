"""calibrator/binned: shrinkage cells + residual PAV, fitted on synthetic rows with known accuracy."""

from __future__ import annotations

import json
import random

import pytest

from camoreasoning import config
from camoreasoning.config import ROOT, Settings
from camoreasoning.contracts import Features
from camoreasoning.evaluate import calibration, load_devsets, run_calibrate
from camoreasoning.registry import get
from camoreasoning.strategies.calibrator import binned as B
from camoreasoning.strategies.calibrator.baseline import CONSTANT

FIXTURE_DEVSET = ROOT / "tests" / "fixtures" / "devset" / "gold_fixture.yaml"
FIXTURE_TAX = ROOT / "tests" / "fixtures" / "taxonomy"

# (status, certainty-or-link_via, n_docs) -> true P(correct). Distinct values so cells are identifiable.
TRUTH = {
    ("answered", "moderate", 5): 0.85,
    ("answered", "moderate", 1): 0.70,
    ("answered", "low", 2): 0.60,
    ("answered", "very_low", 1): 0.35,
    ("no_evidence", "lexical", 0): 0.90,
    ("no_evidence", "none", 0): 0.50,
}
WEIGHTS = {k: w for k, w in zip(TRUTH, (120, 100, 100, 60, 80, 40))}  # 500 rows


def feat(status: str, sub: str, n_docs: int, agreement: float = 1.0) -> Features:
    answered = status == "answered"
    return Features(
        status=status,  # type: ignore[arg-type]
        direction="increase" if answered else None,
        certainty=sub if answered else None,  # type: ignore[arg-type]
        n_docs=n_docs,
        n_edges=n_docs,
        agreement=agreement if answered else 0.0,
        null_share=0.0,
        n_reversed=0,
        link_via="lexical" if answered else sub,  # type: ignore[arg-type]
        link_margin=0.5,
        template_hit=True,
    )


def exact_rows() -> list[tuple[Features, bool]]:
    """Exactly round(p * n) correct per cell, interleaved: the estimator is tested, not sampling luck."""
    rows = []
    for key, n in WEIGHTS.items():
        k = round(TRUTH[key] * n)
        rows += [(feat(*key), i * k // n != (i + 1) * k // n) for i in range(n)]
    return rows


def sampled_rows(n: int, seed: int, agreement_effect: float = 0.0) -> list[tuple[Features, bool]]:
    rng = random.Random(seed)
    keys, weights = list(TRUTH), list(WEIGHTS.values())
    rows = []
    for _ in range(n):
        key = rng.choices(keys, weights)[0]
        a = round(rng.random(), 2)
        p = TRUTH[key] + (agreement_effect * (a - 0.5) if key[0] == "answered" else 0.0)
        rows.append((feat(*key, agreement=a), rng.random() < p))
    return rows


@pytest.fixture
def ctx(make_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path / "calibration")
    return make_ctx()


def test_registered():
    assert get("calibrator", "binned").name == "binned"


def test_well_populated_cells_recover_truth():
    p = B.fit_params(exact_rows())
    assert p["global"]["n"] == 500
    for key, n in WEIGHTS.items():
        cell = p["cells"][B.cell_key(feat(*key))]
        assert cell["n"] == n
        assert abs(cell["estimate"] - TRUTH[key]) <= 0.05, (key, cell)
    assert all(abs(b["offset"]) < 0.01 for b in p["pav"])  # agreement carries no signal here
    for key in TRUTH:  # end to end, through PAV and clip
        assert abs(B.predict(p, feat(*key, agreement=0.5)) - TRUTH[key]) <= 0.05


def test_sparse_cell_shrinks_toward_parent():
    rows = exact_rows() + [(feat("answered", "low", 4), True), (feat("answered", "low", 4), True)]
    p = B.fit_params(rows)
    parent = p["status"]["answered"]["estimate"]
    est = p["cells"]["answered|low|4+"]["estimate"]
    assert est == pytest.approx((2 + B.M * parent) / (2 + B.M), abs=1e-6)
    assert parent < est < 1.0 and est - parent < (1.0 - parent) / 2  # closer to parent than to raw 2/2
    unseen = feat("answered", "high", 7)
    assert B.cell_key(unseen) not in p["cells"]
    assert B.predict(p, unseen) == pytest.approx(B.clip(parent + B._offset(p["pav"], 1.0)))
    # the status level is itself shrunk toward global
    g, s = p["global"]["estimate"], p["status"]["no_evidence"]
    assert s["estimate"] == pytest.approx((s["k"] + B.M * g) / (s["n"] + B.M), abs=1e-6)


def test_output_always_clipped():
    grid = [feat(s, sub, n, a) for s, sub in [("answered", c) for c in ("high", "moderate", "low", "very_low", None)]
            + [("no_evidence", v) for v in ("regex", "lexical", "embedding", "llm", "fallback", "none")]
            for n in (0, 1, 3, 9) for a in (0.0, 0.3, 1.0)]  # fmt: skip
    for outcome in (True, False):
        rows = [(f, outcome) for f in grid] * 30
        p = B.fit_params(rows)
        for f in grid:
            assert B.FLOOR <= B.predict(p, f) <= B.CEIL
        assert all(B.FLOOR <= b["mean_conf"] <= B.CEIL for b in p["reliability"]["bins"] if b["n"])
    p = B.fit_params([(f, True) for f in grid] * 30)
    assert B.predict(p, grid[0]) == B.CEIL


def test_fit_is_deterministic_byte_identical():
    rows = sampled_rows(600, seed=3, agreement_effect=0.4)
    a = json.dumps(B.fit_params(rows), indent=2, sort_keys=True)
    b = json.dumps(B.fit_params(list(rows)), indent=2, sort_keys=True)
    assert a == b


def test_heldout_ece_when_process_matches_cells():
    p = B.fit_params(sampled_rows(2000, seed=1))
    held = sampled_rows(4000, seed=2)
    cal = calibration([B.predict(p, f) for f, _ in held], [y for _, y in held])
    assert cal["ece"] <= 0.05, cal
    assert p["reliability"]["ece"] <= 0.05


def test_pav_learns_agreement_and_is_monotone():
    p = B.fit_params(sampled_rows(2000, seed=1, agreement_effect=0.5))
    offs = [b["offset"] for b in p["pav"]]
    assert len(offs) > 1 and offs == sorted(offs)
    lo, hi = (B.predict(p, feat("answered", "moderate", 5, a)) for a in (0.05, 0.95))
    assert hi - lo > 0.2
    held = sampled_rows(4000, seed=2, agreement_effect=0.5)
    cal = calibration([B.predict(p, f) for f, _ in held], [y for _, y in held])
    flat = {**p, "pav": []}
    cal_flat = calibration([B.predict(flat, f) for f, _ in held], [y for _, y in held])
    assert cal["brier"] < cal_flat["brier"] and cal["ece"] <= 0.05


def test_pav_skipped_below_min_rows():
    rows = [(feat("answered", "low", 2, i / 10), i % 2 == 0) for i in range(B.MIN_PAV_ROWS - 1)]
    assert B.fit_params(rows)["pav"] == []
    assert B.fit_params(rows + rows)["pav"] != []


def test_fit_zero_rows():
    p = B.fit_params([])
    json.dumps(p)
    assert p["global"] == {"n": 0, "k": 0, "estimate": B.PRIOR}
    assert p["cells"] == {} and p["pav"] == [] and p["reliability"]["ece"] is None
    assert B.predict(p, feat("answered", "low", 1)) == B.PRIOR
    assert "| 0.0-0.1 | 0 |" in p["reliability_md"]


def test_missing_params_fall_back_to_baseline(ctx, capsys):
    cal = get("calibrator", "binned")
    for s, sub, n in [("answered", "low", 2), ("no_evidence", "none", 0)] * 3:
        assert cal.confidence(feat(s, sub, n), ctx) == CONSTANT[s]
    assert capsys.readouterr().err.count("calibrator/binned") == 1  # one warning per run


@pytest.mark.parametrize("text", ["{not json", "[]", '{"version": 1}', '{"version": 99, "status": {}}',
                                  json.dumps({**B.fit_params([]), "pav": [{"lo": "x", "offset": 0}]})])  # fmt: skip
def test_corrupt_params_fall_back_to_baseline(ctx, capsys, text):
    config.CALIBRATION_DIR.mkdir(parents=True)
    (config.CALIBRATION_DIR / "binned.json").write_text(text)
    assert get("calibrator", "binned").confidence(feat("answered", "low", 2), ctx) == CONSTANT["answered"]
    assert "baseline constants" in capsys.readouterr().err


def test_round_trip_fit_write_load(ctx, capsys):
    cal = get("calibrator", "binned")
    params = cal.fit(sampled_rows(800, seed=5, agreement_effect=0.4), ctx)
    config.CALIBRATION_DIR.mkdir(parents=True)
    (config.CALIBRATION_DIR / "binned.json").write_text(json.dumps(params, indent=2, sort_keys=True))
    for f, _ in sampled_rows(50, seed=6):
        assert cal.confidence(f, ctx) == B.predict(params, f)
    assert capsys.readouterr().err == ""


def test_write_reliability_script(tmp_path):
    import runpy

    src = tmp_path / "binned.json"
    src.write_text(json.dumps(B.fit_params(exact_rows())))
    mod = runpy.run_path(str(ROOT / "experiments" / "calibration" / "write_reliability.py"))
    assert mod["main"]([str(src)]) == 0
    md = (tmp_path / "reliability.md").read_text()
    assert md.startswith("# Reliability") and md.count("\n| 0.") + md.count("\n| 1.") >= 1
    assert "| answered / moderate / 4+ | 120 | 102 |" in md


def test_calibrate_end_to_end_on_fixture_never_sees_holdout(tmp_path, monkeypatch):
    """run_calibrate on the fixture gold: holdout ids never reach the pipeline or fit; params land in tmp."""
    from camoreasoning.pipeline import Pipeline

    committed = config.CALIBRATION_DIR / "binned.json"
    existed = committed.exists()
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path / "calibration")
    seen, fitted = [], []
    run = Pipeline.run
    monkeypatch.setattr(Pipeline, "run", lambda self, qs: (seen.extend(q.id for q in qs), run(self, qs))[1])
    fit = B.BinnedCalibrator.fit
    monkeypatch.setattr(B.BinnedCalibrator, "fit", lambda self, rows, c: (fitted.extend(rows), fit(self, rows, c))[1])

    settings = Settings(taxonomy_dir=FIXTURE_TAX, strategies={"calibrator": "binned"})
    res = run_calibrate(settings, "dev", [FIXTURE_DEVSET])
    all_items = load_devsets([FIXTURE_DEVSET])
    dev = {g.id for g in all_items if g.split == "dev"}
    holdout = {g.id for g in all_items if g.split == "holdout"}
    assert holdout and dev
    assert set(seen) == dev and not set(seen) & holdout
    assert res["n"] == len(fitted) == len(dev) and res["calibrator"] == "binned"
    params = json.loads((tmp_path / "calibration" / "binned.json").read_text())
    assert params["global"]["n"] == len(dev) and params["version"] == B.VERSION
    assert committed.exists() == existed  # nothing written to the committed experiments/calibration/
    with pytest.raises(SystemExit):
        run_calibrate(settings, "holdout", [FIXTURE_DEVSET])
