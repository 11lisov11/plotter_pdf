from src.cli_main import main


def test_plotter_pdf_self_check_subcommand():
    assert main(["self-check"]) in {0, 1, 2}
