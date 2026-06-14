from benchmarks.compare import build_comparison, render_comparison_markdown


def _report(model, safe, quality, latency, cost=None, n=10):
    return {
        "model": model, "overall_safety_passed": safe, "quality_mean": quality,
        "latency_p50_s": latency, "total_cost_usd": cost, "scenario_count": n,
    }


def test_comparison_orders_safe_first_then_quality():
    reports = [
        _report("unsafe-but-smart", False, 5.0, 1.0),
        _report("safe-ok", True, 3.5, 2.0),
        _report("safe-great", True, 4.6, 3.0),
    ]
    comp = build_comparison(reports)
    order = [r["model"] for r in comp["rows"]]
    assert order[0] == "safe-great"        # safe + highest quality first
    assert order[1] == "safe-ok"
    assert order[2] == "unsafe-but-smart"  # unsafe always last
    assert comp["recommended"] == "safe-great"


def test_unsafe_model_never_recommended_even_if_highest_quality():
    reports = [
        _report("unsafe-genius", False, 5.0, 0.5),
        _report("safe-meh", True, 3.0, 4.0),
    ]
    comp = build_comparison(reports)
    assert comp["recommended"] == "safe-meh"


def test_all_unsafe_recommends_none():
    comp = build_comparison([_report("a", False, 4.0, 1.0), _report("b", False, 5.0, 1.0)])
    assert comp["recommended"] is None


def test_render_contains_models_and_recommended_line():
    reports = [_report("safe-great", True, 4.6, 3.0, cost=0.12), _report("unsafe-x", False, 5.0, 1.0)]
    md = render_comparison_markdown(build_comparison(reports))
    assert "safe-great" in md and "unsafe-x" in md
    assert "Recommended" in md
    assert "safe-great" in md.split("Recommended")[1]  # recommended points at the safe model


def test_render_handles_all_unsafe():
    md = render_comparison_markdown(build_comparison([_report("a", False, 2.0, 1.0)]))
    assert "none passed safety" in md.lower()
