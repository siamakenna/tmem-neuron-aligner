from __future__ import annotations

from click.testing import CliRunner

from tmem_align.cli import main


def test_register_well_is_guarded():
    result = CliRunner().invoke(main, ["register-well", "config.yaml", "--plate", "P1", "--well", "A01"])
    assert result.exit_code != 0
    assert "not safe" in result.output
