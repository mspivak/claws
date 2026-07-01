from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from claws.main import app


runner = CliRunner()


def _ok_response(payload: bytes = b'{"data":{}}'):
    resp = MagicMock()
    resp.status = 200
    resp.read.return_value = payload
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda s, *a: False
    return resp


def test_wizard_command_is_registered():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "setup" in result.output


def test_wizard_explains_each_credential_purpose():
    from claws.commands import setup_wizard

    text = setup_wizard.EXPLANATIONS["anthropic"] + setup_wizard.EXPLANATIONS["github"] + setup_wizard.EXPLANATIONS["telegram"] + setup_wizard.EXPLANATIONS["project"]
    assert "Anthropic" in text
    assert "GitHub" in text
    assert "Telegram" in text
    assert "project" in text.lower()


def test_validate_anthropic_key_hits_models_endpoint():
    from claws.commands import setup_wizard

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        return _ok_response(b'{"data":[]}')

    with patch("claws.commands.setup_wizard.urllib.request.urlopen", side_effect=fake_urlopen):
        ok = setup_wizard._validate_anthropic_key("sk-ant-test")

    assert ok is True
    assert "api.anthropic.com" in captured["url"]
    assert captured["headers"]["X-api-key"] == "sk-ant-test"


def test_validate_anthropic_key_returns_false_on_http_error():
    import urllib.error
    from claws.commands import setup_wizard

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    with patch("claws.commands.setup_wizard.urllib.request.urlopen", side_effect=fake_urlopen):
        ok = setup_wizard._validate_anthropic_key("sk-bad")

    assert ok is False


def test_validate_telegram_token_calls_get_me():
    from claws.commands import setup_wizard

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return _ok_response(b'{"ok":true,"result":{"id":1,"username":"mybot"}}')

    with patch("claws.commands.setup_wizard.urllib.request.urlopen", side_effect=fake_urlopen):
        info = setup_wizard._validate_telegram_token("123:abc")

    assert info["username"] == "mybot"
    assert "123:abc" in captured["url"]
    assert "/getMe" in captured["url"]


def test_validate_telegram_token_returns_none_on_failure():
    import urllib.error
    from claws.commands import setup_wizard

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    with patch("claws.commands.setup_wizard.urllib.request.urlopen", side_effect=fake_urlopen):
        info = setup_wizard._validate_telegram_token("bad")

    assert info is None


def test_wizard_uses_env_anthropic_key_when_user_confirms():
    from claws.commands import setup_wizard

    answers = iter([
        True,
        True,
        "manual",
        "ghp_manualtoken",
        "myorg",
        "myorg/myrepo",
        "use_existing",
        1,
        "manual",
        "111:abc",
        "12345",
    ])
    confirms = iter([True, True, True, True, True])

    def fake_prompt(*args, **kwargs):
        return next(answers)

    def fake_confirm(*args, **kwargs):
        return next(confirms)

    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-fromenv"}),
        patch("claws.commands.setup_wizard._validate_anthropic_key", return_value=True) as mock_anth,
        patch("claws.commands.setup_wizard._validate_telegram_token", return_value={"username": "bot", "id": 1}),
        patch("claws.commands.setup_wizard._validate_github_token", return_value={"login": "myorg"}),
        patch("claws.commands.setup_wizard._select_or_create_project", return_value={"id": "PVT_x", "number": 1, "title": "Existing"}),
        patch("claws.commands.setup_wizard._invoke_setup_anthropic") as mock_run_anth,
        patch("claws.commands.setup_wizard._invoke_setup_github") as mock_run_gh,
        patch("claws.commands.setup_wizard._invoke_setup_telegram") as mock_run_tg,
        patch("claws.commands.setup_wizard.Prompt.ask", side_effect=fake_prompt),
        patch("claws.commands.setup_wizard.IntPrompt.ask", side_effect=fake_prompt),
        patch("claws.commands.setup_wizard.Confirm.ask", side_effect=fake_confirm),
        patch("claws.config.resolve", return_value=("myproj", "us-east-1")),
    ):
        result = runner.invoke(app, ["setup", "--project", "myproj", "--region", "us-east-1"])

    assert result.exit_code == 0, result.output
    mock_anth.assert_called_with("sk-ant-fromenv")
    mock_run_anth.assert_called_once()
    mock_run_gh.assert_called_once()
    mock_run_tg.assert_called_once()


def test_wizard_aborts_when_anthropic_key_invalid_repeatedly():
    from claws.commands import setup_wizard

    answers = iter(["sk-bad1", "sk-bad2", "sk-bad3"])
    confirms = iter([False])

    with (
        patch.dict("os.environ", {}, clear=True),
        patch("claws.commands.setup_wizard._validate_anthropic_key", return_value=False),
        patch("claws.commands.setup_wizard.Prompt.ask", side_effect=answers),
        patch("claws.commands.setup_wizard.Confirm.ask", side_effect=confirms),
        patch("claws.config.resolve", return_value=("myproj", "us-east-1")),
    ):
        result = runner.invoke(app, ["setup", "--project", "myproj", "--region", "us-east-1"])

    assert result.exit_code != 0


def test_create_project_uses_create_project_v2_mutation():
    from claws.commands import setup_wizard

    captured = []

    def fake_graphql(query, variables, env):
        captured.append((query, variables))
        if "createProjectV2" in query:
            return {"data": {"createProjectV2": {"projectV2": {"id": "PVT_new", "number": 42, "title": variables["title"]}}}}
        if "repositoryOwner" in query:
            return {"data": {"repositoryOwner": {"__typename": "User", "id": "U_xyz"}}}
        return {"data": {}}

    with patch("claws.commands.setup_wizard._graphql", side_effect=fake_graphql):
        proj = setup_wizard._create_project("myuser", "My Board", {"GH_TOKEN": "ghp_x"})

    assert proj["id"] == "PVT_new"
    assert proj["number"] == 42
    assert any("createProjectV2" in q for q, _ in captured)
