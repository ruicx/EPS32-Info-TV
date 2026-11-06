"""Exercise terminal commands against the real API without serial hardware."""

import json
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_api import OfflineTransport

from info_tv_service.app import create_app
from info_tv_service.cli import main
from info_tv_service.config import Settings


def call_cli(api: TestClient, arguments: list[str]) -> None:
    """Forward CLI requests to an application with its lifespan running.

    Parameters
    ----------
    api : TestClient
        Real application client with an offline transport.
    arguments : list[str]
        Terminal arguments without the executable name.
    """
    def forward(request: httpx.Request) -> httpx.Response:
        """Send the original method, path, and JSON bytes to the API.

        Parameters
        ----------
        request : httpx.Request
            Request built by the CLI's HTTP client.

        Returns
        -------
        httpx.Response
            Real route response.
        """
        return api.request(request.method, request.url.raw_path.decode(), content=request.content,
                           headers=dict(request.headers))

    client = httpx.Client(transport=httpx.MockTransport(forward))
    with patch("info_tv_service.cli.httpx.Client", return_value=client):
        main(arguments)


def test_task_lifecycle_and_retry_through_cli(capsys: pytest.CaptureFixture[str]) -> None:
    """Preserve UUID retries, execution ordering, and card-based closure.

    Parameters
    ----------
    capsys : pytest.CaptureFixture[str]
        Terminal output capture.
    """
    event_id = str(uuid4())
    arguments = ["task", "submit", "--event-id", event_id, "--task-id", "build-1",
                 "--sequence", "1", "--state", "running", "--title", "Build",
                 "--progress-percent", "20", "--icon", "build", "--conversation-id", "project",
                 "--conversation-title", "Firmware", "--run-sequence", "1", "--context", "info_tv"]
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as api:
        call_cli(api, arguments)
        accepted = json.loads(capsys.readouterr().out)
        assert accepted["outcome"] == "accepted"
        call_cli(api, arguments)
        assert json.loads(capsys.readouterr().out)["outcome"] == "duplicate"
        call_cli(api, ["task", "list"])
        cards = json.loads(capsys.readouterr().out)
        assert cards[0]["source"] == "cli"
        assert cards[0]["progress_percent"] == 20
        assert cards[0]["conversation_id"] == "project"
        assert cards[0]["icon"] == "build"
        call_cli(api, ["task", "close", str(UUID(accepted["card_id"]))])
        assert json.loads(capsys.readouterr().out)["removed"] is True
        call_cli(api, ["task", "list"])
        assert json.loads(capsys.readouterr().out) == []


def test_weather_alert_brightness_and_status(capsys: pytest.CaptureFixture[str]) -> None:
    """Cover retained values, updater health, and independent alert removal.

    Parameters
    ----------
    capsys : pytest.CaptureFixture[str]
        Terminal output capture.
    """
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as api:
        call_cli(api, ["weather", "set", "--location", "Shanghai", "--temperature-c", "18",
                       "--condition", "cloudy", "--daily-low-c", "12", "--daily-high-c", "20"])
        assert json.loads(capsys.readouterr().out)["temperature_c"] == 18
        call_cli(api, ["weather", "get"])
        assert json.loads(capsys.readouterr().out)["daily_low_c"] == 12
        call_cli(api, ["weather", "updater"])
        assert json.loads(capsys.readouterr().out) == {"enabled": False}
        call_cli(api, ["alert", "set", "--alert-id", str(uuid4()), "--sequence", "1",
                       "--title", "Test rain", "--source", "Demo", "--location", "Shanghai",
                       "--severity", "yellow", "--detail", "Synthetic test", "--valid-for-seconds", "60"])
        assert json.loads(capsys.readouterr().out)["state"] == "active"
        call_cli(api, ["weather", "clear"])
        assert json.loads(capsys.readouterr().out)["state"] == "unavailable"
        call_cli(api, ["alert", "get"])
        assert json.loads(capsys.readouterr().out)["state"] == "active"
        call_cli(api, ["alert", "clear"])
        assert json.loads(capsys.readouterr().out)["state"] == "unavailable"
        call_cli(api, ["brightness", "0"])
        assert json.loads(capsys.readouterr().out)["brightness_percent"] == 0
        call_cli(api, ["brightness"])
        assert json.loads(capsys.readouterr().out)["brightness_percent"] == 0
        call_cli(api, ["status"])
        assert "state" in json.loads(capsys.readouterr().out)


def test_api_rejection_is_stderr_and_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    """Report route validation failures without a traceback or success output.

    Parameters
    ----------
    capsys : pytest.CaptureFixture[str]
        Terminal output capture.
    """
    with TestClient(create_app(Settings("unused"), OfflineTransport())) as api, pytest.raises(SystemExit) as error:
        call_cli(api, ["weather", "set", "--location", "Shanghai", "--temperature-c", "18",
                       "--condition", "clear", "--daily-low-c", "12"])
    assert error.value.code == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "HTTP 422" in output.err
    assert "Supply both" in output.err


@pytest.mark.parametrize("failure", ["connection", "timeout", "invalid_json"])
def test_request_failures_are_nonzero(failure: str, capsys: pytest.CaptureFixture[str]) -> None:
    """Keep network and unexpected response errors suitable for scripts.

    Parameters
    ----------
    failure : str
        Failure to simulate in the HTTP transport.
    capsys : pytest.CaptureFixture[str]
        Terminal output capture.
    """
    def fail(request: httpx.Request) -> httpx.Response:
        """Simulate a connection failure or an invalid service response.

        Parameters
        ----------
        request : httpx.Request
            Outgoing client request.

        Returns
        -------
        httpx.Response
            A successful status containing invalid JSON.

        Raises
        ------
        httpx.RequestError
            For the selected network failure.
        """
        if failure == "connection":
            raise httpx.ConnectError("Host is unavailable", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("Host did not respond", request=request)
        return httpx.Response(200, text="not JSON")

    client = httpx.Client(transport=httpx.MockTransport(fail))
    with patch("info_tv_service.cli.httpx.Client", return_value=client), pytest.raises(SystemExit) as error:
        main(["status"])
    assert error.value.code == 1
    output = capsys.readouterr()
    assert output.out == "" and "Request failed:" in output.err


@pytest.mark.parametrize("arguments", [
    [], ["task"], ["task", "close", "invalid"], ["brightness", "101"],
    ["--timeout", "nan", "status"], ["--timeout", "0", "status"],
    ["serve", "--serial-port", "COM6", "--http-port", "65536"],
])
def test_usage_errors_do_not_open_resources(arguments: list[str]) -> None:
    """Reject incomplete or malformed commands before opening any resources.

    Parameters
    ----------
    arguments : list[str]
        Invalid invocation.
    """
    with (
        patch("info_tv_service.cli.httpx.Client") as client,
        patch("info_tv_service.cli.uvicorn.run") as server,
        pytest.raises(SystemExit) as error,
    ):
        main(arguments)
    assert error.value.code == 2
    client.assert_not_called()
    server.assert_not_called()


def test_explicit_serve_keeps_loopback_binding() -> None:
    """Start the service using the same settings as the legacy invocation."""
    with patch("info_tv_service.cli.create_app") as create, patch("info_tv_service.cli.uvicorn.run") as server:
        main(["serve", "--serial-port", "COM8", "--http-port", "9876"])
    assert create.call_args.args[0] == Settings("COM8", http_port=9876)
    assert server.call_args.kwargs == {"host": "127.0.0.1", "port": 9876, "workers": 1}


def test_client_url_timeout_and_generated_event_id(capsys: pytest.CaptureFixture[str]) -> None:
    """Honor explicit connection options and generate a valid event identity.

    Parameters
    ----------
    capsys : pytest.CaptureFixture[str]
        Terminal output capture.
    """
    with patch("info_tv_service.cli.httpx.Client") as factory:
        client = factory.return_value.__enter__.return_value
        client.request.return_value.json.return_value = {"outcome": "accepted"}
        main(["--url", "http://127.0.0.1:9876/", "--timeout", "3", "task", "submit",
              "--task-id", "run", "--sequence", "1", "--state", "running", "--title", "Build"])
    factory.assert_called_once_with(timeout=3, trust_env=False)
    assert client.request.call_args.args == ("POST", "http://127.0.0.1:9876/v1/task-events")
    assert UUID(client.request.call_args.kwargs["json"]["event_id"]).version == 4
    assert json.loads(capsys.readouterr().out) == {"outcome": "accepted"}
