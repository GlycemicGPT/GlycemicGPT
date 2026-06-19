"""End-to-end harness tests with mocked HTTP.

These never touch the network: ``harness._post_chat`` is monkeypatched to return
queued, deterministic model responses, so the whole sampling -> parse -> variance
pipeline is exercised on fixtures (CI-safe; the live model run is operational and
out of CI by design). Images are tiny temp files, so the gitignored real dataset
images are not required.
"""

import argparse
import json
import sys
from pathlib import Path

import harness
import pytest

_FAKE_JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def _estimate(low, high, desc="a banana", conf="high"):
    return json.dumps(
        {
            "food_description": desc,
            "carbs_grams_low": low,
            "carbs_grams_high": high,
            "confidence": conf,
        }
    )


class _Responder:
    """Return queued responses in order (cycling); ``None`` -> request failure."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, base_url, api_key, body, timeout, max_attempts=4):
        response = self.responses[self.calls % len(self.responses)]
        self.calls += 1
        if response is None:
            raise RuntimeError("simulated request failure")
        return response


def _manifest(tmp_path, items, *, set_name="easy", name="manifest.json"):
    images = tmp_path / "images"
    images.mkdir(exist_ok=True)
    for item in items:
        image = item.get("image")
        # Only materialize a real, in-tree image; traversal/missing cases must not.
        if image and image == image.rsplit("/", 1)[-1] and ".." not in image:
            (images / image).write_bytes(_FAKE_JPEG)
    path = tmp_path / name
    path.write_text(json.dumps({"set": set_name, "items": items}))
    return path


def _ns(tmp_path, manifest, **overrides):
    args = {
        "manifest": [str(m) for m in manifest],
        "images_dir": None,
        "base_url": "http://test",
        "model": "test-model",
        "max_tokens": 64,
        "timeout": 5.0,
        "repeats": 1,
        "sweep": None,
        "illustrative_icr": 10.0,
        "limit": 0,
        "out_dir": str(tmp_path / "out"),
        "no_auth": True,
        "enforce_pass_bar": False,
    }
    args.update(overrides)
    return argparse.Namespace(**args)


def _read(args):
    return json.loads((Path(args.out_dir) / "results.json").read_text())


# --- single-shot path ---------------------------------------------------------


def test_single_shot_is_default_and_unchanged_shape(tmp_path, monkeypatch):
    m = _manifest(
        tmp_path,
        [
            {
                "id": "banana",
                "known_carbs_grams": 27,
                "image": "b.jpg",
                "expected_identity": ["banana"],
            }
        ],
    )
    monkeypatch.setattr(harness, "_post_chat", _Responder([_estimate(24, 30)]))
    args = _ns(tmp_path, [m], repeats=1)
    assert harness.run(args) == 0
    report = _read(args)
    assert report["mode"] == "single_shot"
    assert "variance_aggregate" not in report
    assert report["aggregate"]["mae_grams"] == 0.0  # midpoint 27 == truth 27


def test_out_of_bounds_sample_dropped_identically_in_single_shot_and_variance(
    tmp_path, monkeypatch
):
    # A parseable but out-of-absolute-bounds (> 1000 g) estimate must be a
    # non-scored miss in BOTH paths, so single-shot MAE == variance(N=1) MAE on
    # identical model output (single-shot parity). One in-bounds + one out-of-bounds.
    items = [
        {
            "id": "banana",
            "known_carbs_grams": 27,
            "image": "b.jpg",
            "expected_identity": ["banana"],
        },
        {
            "id": "huge",
            "known_carbs_grams": 50,
            "image": "h.jpg",
            "expected_identity": ["mystery"],
        },
    ]
    responses = [_estimate(24, 30, "banana"), _estimate(1200, 1500, "mystery")]

    m1 = _manifest(tmp_path, items, name="ss.json")
    monkeypatch.setattr(harness, "_post_chat", _Responder(responses))
    single = _ns(tmp_path, [m1], repeats=1, out_dir=str(tmp_path / "ss"))
    harness.run(single)
    ss = _read(single)

    # The variance scorer at N=1 is reached via --sweep 1 (this is the exact path
    # the MEDIUM was about: --sweep 1 vs a standalone single-shot run).
    m2 = _manifest(tmp_path, items, name="var.json")
    monkeypatch.setattr(harness, "_post_chat", _Responder(responses))
    a2 = _ns(tmp_path, [m2], sweep=[1], out_dir=str(tmp_path / "var"))
    harness.run(a2)
    sweep_n1 = _read(a2)["sweep_curve"][0]

    # Only the in-bounds banana is scored in each: MAE 0 in both, and equal.
    assert ss["aggregate"]["mae_grams"] == 0.0
    assert sweep_n1["mae_grams"] == 0.0
    assert ss["aggregate"]["mae_grams"] == sweep_n1["mae_grams"]
    # The out-of-bounds item is recorded but not scored in the single-shot path.
    huge = next(r for r in ss["items"] if r.get("id") == "huge")
    assert huge["abs_error"] is None


# --- --repeats variance -------------------------------------------------------


def test_repeats_aggregates_n_samples_per_image(tmp_path, monkeypatch):
    m = _manifest(
        tmp_path,
        [
            {
                "id": "banana",
                "known_carbs_grams": 27,
                "image": "b.jpg",
                "expected_identity": ["banana"],
            }
        ],
    )
    # midpoints: 27, 30, 24 -> spread 6
    monkeypatch.setattr(
        harness,
        "_post_chat",
        _Responder([_estimate(24, 30), _estimate(26, 34), _estimate(20, 28)]),
    )
    args = _ns(tmp_path, [m], repeats=3)
    assert harness.run(args) == 0
    report = _read(args)
    assert report["mode"] == "variance"
    agg = report["variance_aggregate"]
    assert agg["n_with_samples"] == 1
    assert agg["samples_ok_total"] == 3
    assert agg["max_spread_g"] == 6.0


def test_identity_error_tracked_end_to_end(tmp_path, monkeypatch):
    m = _manifest(
        tmp_path,
        [
            {
                "id": "crema",
                "known_carbs_grams": 30,
                "image": "c.jpg",
                "expected_identity": ["crema catalana"],
            }
        ],
        set_name="adversarial",
    )
    monkeypatch.setattr(
        harness,
        "_post_chat",
        _Responder([_estimate(28, 32, "creme brulee")] * 3),
    )
    args = _ns(tmp_path, [m], repeats=3)
    harness.run(args)
    report = _read(args)
    assert report["variance_aggregate"]["identity_error_rate"] == 1.0


def test_partial_failure_flagged_end_to_end(tmp_path, monkeypatch):
    m = _manifest(
        tmp_path,
        [
            {
                "id": "banana",
                "known_carbs_grams": 27,
                "image": "b.jpg",
                "expected_identity": ["banana"],
            }
        ],
    )
    monkeypatch.setattr(
        harness,
        "_post_chat",
        _Responder([_estimate(24, 30), None, _estimate(20, 28)]),
    )
    args = _ns(tmp_path, [m], repeats=3)
    harness.run(args)
    report = _read(args)
    agg = report["variance_aggregate"]
    assert agg["n_partial_failures"] == 1
    assert agg["samples_ok_total"] == 2
    assert agg["samples_requested_total"] == 3
    assert report["items"][0]["partial_failure"] is True


def test_ambiguous_item_skips_mae_end_to_end(tmp_path, monkeypatch):
    m = _manifest(
        tmp_path,
        [
            {
                "id": "plate",
                "ambiguous": True,
                "image": "p.jpg",
                "expected_identity": ["mixed plate"],
            }
        ],
        set_name="adversarial",
    )
    monkeypatch.setattr(
        harness,
        "_post_chat",
        _Responder(
            [_estimate(40, 60, "mixed plate"), _estimate(50, 90, "mixed plate")]
        ),
    )
    args = _ns(tmp_path, [m], repeats=2)
    harness.run(args)
    item = _read(args)["items"][0]
    assert item["ambiguous"] is True
    assert item["mae_grams"] is None
    assert item["spread_g"] is not None
    assert item["identity_error"] is None  # ambiguous: identity not scored


def test_dosing_language_surfaced_as_safety_violation(tmp_path, monkeypatch):
    m = _manifest(
        tmp_path,
        [
            {
                "id": "banana",
                "known_carbs_grams": 27,
                "image": "b.jpg",
                "expected_identity": ["banana"],
            }
        ],
    )
    bad = _estimate(24, 30)[:-1] + ', "note": "take 4 units of insulin"}'
    monkeypatch.setattr(
        harness,
        "_post_chat",
        _Responder([bad, _estimate(26, 34), _estimate(20, 28)]),
    )
    args = _ns(tmp_path, [m], repeats=3)
    harness.run(args)
    assert _read(args)["safety"]["dosing_violation_count"] == 1


def test_dosing_violation_returns_nonzero_exit(tmp_path, monkeypatch):
    # The "must be 0" safety check is enforced: a dosing violation exits non-zero
    # so a scripted/CI run fails rather than silently printing the count.
    m = _manifest(
        tmp_path,
        [
            {
                "id": "banana",
                "known_carbs_grams": 27,
                "image": "b.jpg",
                "expected_identity": ["banana"],
            }
        ],
    )
    bad = _estimate(24, 30)[:-1] + ', "note": "take 4 units of insulin"}'
    monkeypatch.setattr(
        harness,
        "_post_chat",
        _Responder([bad, _estimate(26, 34), _estimate(20, 28)]),
    )
    args = _ns(tmp_path, [m], repeats=3)
    assert harness.run(args) == harness._DOSING_VIOLATION_EXIT
    assert harness.run(args) != 0


def test_manifest_path_resolves_relative_to_script():
    # A documented repo-root path (dataset/manifest.json) resolves via the
    # script-relative fallback even when cwd has no such file.
    resolved = harness._resolve_manifest_path("dataset/manifest.json")
    assert resolved.is_file()
    assert resolved.name == "manifest.json"


def test_multi_manifest_reports_per_set(tmp_path, monkeypatch):
    easy = _manifest(
        tmp_path,
        [
            {
                "id": "banana",
                "known_carbs_grams": 27,
                "image": "b.jpg",
                "expected_identity": ["banana"],
            }
        ],
        set_name="easy",
        name="easy.json",
    )
    adv = _manifest(
        tmp_path,
        [
            {
                "id": "crema",
                "known_carbs_grams": 30,
                "image": "c.jpg",
                "expected_identity": ["crema catalana"],
            }
        ],
        set_name="adversarial",
        name="adv.json",
    )
    monkeypatch.setattr(
        harness,
        "_post_chat",
        _Responder(
            [_estimate(24, 30, "banana")] * 3 + [_estimate(28, 32, "creme brulee")] * 3
        ),
    )
    args = _ns(tmp_path, [easy, adv], repeats=3)
    harness.run(args)
    report = _read(args)
    assert set(report["by_set"]) == {"easy", "adversarial"}
    assert report["by_set"]["adversarial"]["identity_error_rate"] == 1.0
    assert report["by_set"]["easy"]["identity_error_rate"] == 0.0


# --- --sweep ------------------------------------------------------------------


def test_sweep_scores_each_n_from_one_sampling(tmp_path, monkeypatch):
    m = _manifest(
        tmp_path,
        [
            {
                "id": "banana",
                "known_carbs_grams": 27,
                "image": "b.jpg",
                "expected_identity": ["banana"],
            }
        ],
    )
    monkeypatch.setattr(
        harness,
        "_post_chat",
        _Responder(
            [
                _estimate(24, 30),
                _estimate(26, 34),
                _estimate(20, 28),
                _estimate(22, 32),
                _estimate(25, 41),
            ]
        ),
    )
    args = _ns(tmp_path, [m], sweep=[1, 3, 5])
    assert harness.run(args) == 0
    report = _read(args)
    assert report["mode"] == "sweep"
    rows = {row["n"]: row for row in report["sweep_curve"]}
    assert set(rows) == {1, 3, 5}
    assert rows[1]["max_cv"] is None  # N=1 cannot surface variance
    assert rows[3]["max_cv"] is not None
    # spread is non-decreasing as the prefix grows (min/max only widen)
    assert rows[5]["max_spread_g"] >= rows[3]["max_spread_g"]


def test_sweep_does_not_double_count_dosing_violations(tmp_path, monkeypatch):
    # A dosing phrase in one sample must be counted once, not once per swept N.
    m = _manifest(
        tmp_path,
        [
            {
                "id": "banana",
                "known_carbs_grams": 27,
                "image": "b.jpg",
                "expected_identity": ["banana"],
            }
        ],
    )
    bad = _estimate(24, 30)[:-1] + ', "note": "take 4 units of insulin"}'
    monkeypatch.setattr(
        harness,
        "_post_chat",
        _Responder(
            [
                bad,
                _estimate(26, 34),
                _estimate(20, 28),
                _estimate(22, 32),
                _estimate(25, 41),
            ]
        ),
    )
    args = _ns(tmp_path, [m], sweep=[1, 3, 5])
    harness.run(args)
    assert _read(args)["safety"]["dosing_violation_count"] == 1


def test_sweep_samples_image_only_once_at_max_n(tmp_path, monkeypatch):
    m = _manifest(
        tmp_path,
        [
            {
                "id": "banana",
                "known_carbs_grams": 27,
                "image": "b.jpg",
                "expected_identity": ["banana"],
            }
        ],
    )
    responder = _Responder([_estimate(24, 30)])
    monkeypatch.setattr(harness, "_post_chat", responder)
    args = _ns(tmp_path, [m], sweep=[1, 3, 5])
    harness.run(args)
    # One image sampled once at max N=5 -> exactly 5 requests, not 1+3+5.
    assert responder.calls == 5


# --- safety / robustness ------------------------------------------------------


def test_path_traversal_image_is_rejected_and_not_sampled(tmp_path, monkeypatch):
    m = _manifest(
        tmp_path,
        [
            {
                "id": "evil",
                "known_carbs_grams": 10,
                "image": "../secret.txt",
                "expected_identity": ["x"],
            }
        ],
    )
    calls = {"n": 0}

    def spy(*a, **k):
        calls["n"] += 1
        return _estimate(10, 20)

    monkeypatch.setattr(harness, "_post_chat", spy)
    args = _ns(tmp_path, [m], repeats=3)
    harness.run(args)
    report = _read(args)
    assert calls["n"] == 0  # the unsafe image was never read or sent
    assert "error" in report["items"][0]
    assert "bare filename" in report["items"][0]["error"]


def test_missing_image_recorded_not_crashed(tmp_path, monkeypatch):
    path = tmp_path / "m.json"
    path.write_text(
        json.dumps(
            {
                "set": "easy",
                "items": [
                    {
                        "id": "ghost",
                        "known_carbs_grams": 10,
                        "image": "nope.jpg",
                        "expected_identity": ["x"],
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(harness, "_post_chat", _Responder([_estimate(10, 20)]))
    args = _ns(tmp_path, [path], repeats=3)
    assert harness.run(args) == 0
    assert "error" in _read(args)["items"][0]


def test_empty_manifest_returns_2(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"items": []}))
    args = _ns(tmp_path, [path])
    assert harness.run(args) == 2


def test_determinism_same_inputs_same_metrics(tmp_path, monkeypatch):
    items = [
        {
            "id": "banana",
            "known_carbs_grams": 27,
            "image": "b.jpg",
            "expected_identity": ["banana"],
        }
    ]
    responses = [_estimate(24, 30), _estimate(26, 34), _estimate(20, 28)]

    def run_once(tag):
        m = _manifest(tmp_path, items, name=f"{tag}.json")
        monkeypatch.setattr(harness, "_post_chat", _Responder(responses))
        args = _ns(tmp_path, [m], repeats=3, out_dir=str(tmp_path / tag))
        harness.run(args)
        return json.loads((tmp_path / tag / "results.json").read_text())[
            "variance_aggregate"
        ]

    assert run_once("a") == run_once("b")


# --- pass-bar (local-model certification gate) --------------------------------


def _easy_item(item_id="banana", carbs=27, image="b.jpg", identity=None):
    return {
        "id": item_id,
        "known_carbs_grams": carbs,
        "image": image,
        "expected_identity": identity or ["banana"],
    }


def test_variance_report_carries_pass_bar_verdict(tmp_path, monkeypatch):
    # A clean, reproducible easy-set run at the certification N clears the bar.
    m = _manifest(tmp_path, [_easy_item()])
    monkeypatch.setattr(harness, "_post_chat", _Responder([_estimate(24, 30)]))
    args = _ns(tmp_path, [m], repeats=5)
    assert harness.run(args) == 0
    report = _read(args)
    assert report["pass_bar"]["verdict"] == "pass"
    assert report["pass_bar"]["repeats"] == 5
    names = {c["name"] for c in report["pass_bar"]["criteria"]}
    assert {
        "vision_available",
        "dosing_violations",
        "easy_identity_error_rate",
        "easy_max_cv",
        "easy_max_spread_g",
        "easy_mae_g",
    } <= names


def test_enforce_pass_bar_passing_model_exits_zero(tmp_path, monkeypatch):
    m = _manifest(tmp_path, [_easy_item()])
    monkeypatch.setattr(harness, "_post_chat", _Responder([_estimate(24, 30)]))
    args = _ns(tmp_path, [m], repeats=5, enforce_pass_bar=True)
    assert harness.run(args) == 0
    assert _read(args)["pass_bar"]["verdict"] == "pass"


def test_enforce_pass_bar_low_n_is_insufficient_and_gated(tmp_path, monkeypatch):
    # All metrics fine, but N=3 < the certification N: cannot certify -> non-zero
    # under enforcement so a benchmark script does not bless an under-sampled run.
    m = _manifest(tmp_path, [_easy_item()])
    monkeypatch.setattr(harness, "_post_chat", _Responder([_estimate(24, 30)]))
    args = _ns(tmp_path, [m], repeats=3, enforce_pass_bar=True)
    assert harness.run(args) == harness._PASS_BAR_FAIL_EXIT
    assert _read(args)["pass_bar"]["verdict"] == "insufficient_data"


def test_enforce_pass_bar_high_variance_model_fails(tmp_path, monkeypatch):
    # Accurate-on-average (midpoint ~27) but wildly variable photo-to-photo ->
    # FAIL on variance, exit non-zero under enforcement. Variance is the bar.
    m = _manifest(tmp_path, [_easy_item()])
    monkeypatch.setattr(
        harness,
        "_post_chat",
        _Responder(
            [
                _estimate(2, 12),  # mid 7
                _estimate(40, 60),  # mid 50
                _estimate(5, 15),  # mid 10
                _estimate(38, 50),  # mid 44
                _estimate(20, 30),  # mid 25
            ]
        ),
    )
    args = _ns(tmp_path, [m], repeats=5, enforce_pass_bar=True)
    assert harness.run(args) == harness._PASS_BAR_FAIL_EXIT
    report = _read(args)
    assert report["pass_bar"]["verdict"] == "fail"
    assert "easy_max_cv" in report["pass_bar"]["failures"]


def test_pass_bar_is_informational_without_enforcement(tmp_path, monkeypatch):
    # The same high-variance model does NOT change the exit code when the bar is
    # not enforced -- existing/cloud runs are unaffected (verdict still recorded).
    m = _manifest(tmp_path, [_easy_item()])
    monkeypatch.setattr(
        harness, "_post_chat", _Responder([_estimate(2, 12), _estimate(40, 60)])
    )
    args = _ns(tmp_path, [m], repeats=5)  # enforce_pass_bar defaults False
    assert harness.run(args) == 0
    assert _read(args)["pass_bar"]["verdict"] == "fail"


def test_metric_comparability_local_and_cloud_score_identically(tmp_path, monkeypatch):
    # The crux of the local-model benchmark: identical model responses scored
    # through the harness must yield identical metrics + pass-bar whether the
    # endpoint is "cloud" or "local". Metrics are a pure function of the responses,
    # not the transport -- so the cloud reference run and local numbers are
    # directly comparable.
    responses = [_estimate(24, 30), _estimate(22, 32), _estimate(25, 29)]

    def run_endpoint(base_url, model, no_auth, out_name):
        m = _manifest(tmp_path, [_easy_item()], name=f"{out_name}.json")
        monkeypatch.setattr(harness, "_post_chat", _Responder(list(responses)))
        args = _ns(
            tmp_path,
            [m],
            repeats=5,
            base_url=base_url,
            model=model,
            no_auth=no_auth,
            out_dir=str(tmp_path / out_name),
        )
        assert harness.run(args) == 0
        return _read(args)

    cloud = run_endpoint("http://localhost:3456", "claude-sonnet-4-5", False, "cloud")
    local = run_endpoint("http://localhost:11434", "llava:13b", True, "local")

    assert cloud["variance_aggregate"] == local["variance_aggregate"]
    assert cloud["pass_bar"]["criteria"] == local["pass_bar"]["criteria"]
    assert cloud["pass_bar"]["verdict"] == local["pass_bar"]["verdict"]


# --- CLI argument handling ----------------------------------------------------


def test_parse_sweep_sorts_and_dedupes():
    assert harness._parse_sweep("5,1,3,3") == [1, 3, 5]


@pytest.mark.parametrize("spec", ["1,oops,3", "0,2", "", "-1"])
def test_parse_sweep_rejects_bad_specs(spec):
    with pytest.raises(ValueError):
        harness._parse_sweep(spec)


def test_main_bad_sweep_exits_cleanly(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["harness.py", "--sweep", "1,bad,3"])
    with pytest.raises(SystemExit) as exc:
        harness.main()
    assert exc.value.code == 2  # argparse usage error, not a traceback


def test_main_bad_icr_exits_cleanly(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["harness.py", "--illustrative-icr", "0"])
    with pytest.raises(SystemExit) as exc:
        harness.main()
    assert exc.value.code == 2


def test_enforce_pass_bar_in_single_shot_is_a_clean_error(monkeypatch):
    # The pass-bar is only computed in variance mode; enforcing it in single-shot
    # (the default --repeats 1) must fail loud, not silently exit 0 (which would
    # bless an unverified model). argparse usage error, not a traceback.
    monkeypatch.setattr(sys, "argv", ["harness.py", "--enforce-pass-bar"])
    with pytest.raises(SystemExit) as exc:
        harness.main()
    assert exc.value.code == 2


def test_enforce_pass_bar_with_sweep_is_a_clean_error(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["harness.py", "--sweep", "1,3,5", "--enforce-pass-bar"]
    )
    with pytest.raises(SystemExit) as exc:
        harness.main()
    assert exc.value.code == 2
