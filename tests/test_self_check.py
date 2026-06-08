from src.plotter_backend.jobs.self_check import format_report, run_self_check


def test_self_check_returns_report():
    code, report = run_self_check()
    assert code in {0, 1, 2}
    assert "core" in report and "safety" in report
    assert "Plotter PDF self-check" in format_report(report)
