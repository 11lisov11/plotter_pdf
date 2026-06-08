from src.plotter_backend.machine.safe_shutdown import build_safe_park_release_commands


def test_safe_release_contains_z_up_m5_release():
    cmds = build_safe_park_release_commands(release=True, home=True, sleep=False)
    joined = "\n".join(cmds)
    assert "M5" in joined
    assert "$1=0" in joined
    assert "G0 Z" in joined
