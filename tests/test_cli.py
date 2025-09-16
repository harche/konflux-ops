from typer.testing import CliRunner

from konflux_automation.cli import app


runner = CliRunner()


def test_top_level_tenant_group_present() -> None:
    result = runner.invoke(app, ["tenant", "--help"])
    assert result.exit_code == 0
    assert "create" in result.stdout
    assert "configure" in result.stdout


def test_tenant_configure_subcommands() -> None:
    result = runner.invoke(app, ["tenant", "configure", "--help"])
    assert result.exit_code == 0
    for command in ("component", "release", "secret", "wizard"):
        assert command in result.stdout
