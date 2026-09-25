import pytest

from main import main


def test_main_exits_with_code_2_on_invalid_configuration(monkeypatch, capsys):
    # given
    monkeypatch.setenv("PROXY_PORT", "abc")
    # when / then
    with pytest.raises(SystemExit) as exec_info:
        main()

    assert exec_info.value.code == 2
    captured = capsys.readouterr()
    assert (
        "invalid configuration: PROXY_PORT must be an integer, got: 'abc'"
        in captured.err
    )
