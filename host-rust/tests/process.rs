//! Real executable tests for crash recovery, YAML lookup, and hook outbox delivery.

use std::{
    path::Path,
    process::{Child, Command, Stdio},
    time::{Duration, Instant},
};

use serde_json::{Value, json};
use tempfile::TempDir;
use uuid::Uuid;

/// Always terminate test children, including when an assertion fails.
struct Process(Child);

impl Drop for Process {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

/// Start the real release-shaped CLI using a private database and an absent port.
fn start(directory: &Path, state: &Path) -> Process {
    Process(
        Command::new(env!("CARGO_BIN_EXE_info-tv"))
            .args(["serve", "--state-dir"])
            .arg(state)
            .current_dir(directory)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("start service"),
    )
}

fn wait_online(client: &reqwest::blocking::Client, url: &str, process: &mut Process) -> Value {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        assert!(
            process.0.try_wait().expect("process status").is_none(),
            "service exited during startup"
        );
        if let Ok(response) = client.get(format!("{url}/v1/device")).send()
            && response.status().is_success()
        {
            return response.json().expect("JSON status");
        }
        assert!(Instant::now() < deadline, "service startup timeout");
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// Allocate an ephemeral loopback port for a private process test.
fn free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .expect("port")
        .local_addr()
        .expect("address")
        .port()
}

#[test]
fn forced_termination_recovers_acknowledged_state_and_hook_ledger() {
    let directory = tempfile::Builder::new()
        .prefix("info tv ")
        .tempdir()
        .expect("temp");
    let state = directory.path().join("state");
    let port = free_port();
    let url = format!("http://127.0.0.1:{port}");
    std::fs::write(
        directory.path().join("info-tv.yaml"),
        format!("serial_port: info-tv-absent-test-port\nhttp_port: {port}\n"),
    )
    .expect("config");
    let client = reqwest::blocking::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(2))
        .build()
        .expect("client");
    let mut process = start(directory.path(), &state);
    let original_session = wait_online(&client, &url, &mut process)["session_id"].clone();
    let event = json!({"event_id":Uuid::new_v4().simple().to_string(),"source":"test","task_id":"crash",
        "sequence":1,"state":"running","title":"Survive forced termination"});
    let response: Value = client
        .post(format!("{url}/v1/task-events"))
        .json(&event)
        .send()
        .expect("submit")
        .error_for_status()
        .expect("accepted")
        .json()
        .expect("JSON");
    let card_id = response["card_id"].clone();
    client
        .put(format!("{url}/v1/device/settings"))
        .json(&json!({"brightness_percent":0}))
        .send()
        .expect("settings")
        .error_for_status()
        .expect("accepted");
    drop(process); // Kill without allowing the service's shutdown handler to save.
    let mut process = start(directory.path(), &state);
    assert_ne!(
        wait_online(&client, &url, &mut process)["session_id"],
        original_session
    );
    let tasks: Value = client
        .get(format!("{url}/v1/tasks"))
        .send()
        .expect("tasks")
        .json()
        .expect("JSON");
    assert_eq!(tasks[0]["card_id"], card_id);
    assert_eq!(tasks[0]["delivery"], json!({"state":"pending"}));
    let settings: Value = client
        .get(format!("{url}/v1/device/settings"))
        .send()
        .expect("settings")
        .json()
        .expect("JSON");
    assert_eq!(settings["brightness_percent"], 0);
    let retry: Value = client
        .post(format!("{url}/v1/task-events"))
        .json(&event)
        .send()
        .expect("retry")
        .json()
        .expect("JSON");
    assert_eq!(retry["outcome"], "duplicate");

    let outbox = directory.path().join("codex.sqlite3");
    // Capture with the service deliberately unavailable. Runtime failure is neutral.
    let mut hook = Command::new(env!("CARGO_BIN_EXE_info-tv"))
        .args([
            "hook",
            "codex",
            "--url",
            "http://127.0.0.1:1",
            "--state-file",
        ])
        .arg(&outbox)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("hook");
    use std::io::Write;
    hook.stdin
        .take()
        .expect("stdin")
        .write_all(
            json!({"hook_event_name":"UserPromptSubmit","session_id":"hook-session",
        "turn_id":"hook-turn","prompt":"Hook task"})
            .to_string()
            .as_bytes(),
        )
        .expect("payload");
    let output = hook.wait_with_output().expect("hook result");
    assert!(output.status.success());
    assert_eq!(String::from_utf8_lossy(&output.stdout).trim(), "{}");
    let connection = rusqlite::Connection::open(&outbox).expect("ledger");
    let before: i64 = connection
        .query_row("SELECT COUNT(*) FROM outbox", [], |r| r.get(0))
        .expect("pending");
    assert_eq!(before, 1);
    let output = Command::new(env!("CARGO_BIN_EXE_info-tv-hook"))
        .args(["codex", "--flush", "--url", &url, "--state-file"])
        .arg(&outbox)
        .output()
        .expect("compatibility hook");
    assert!(output.status.success());
    let after: i64 = connection
        .query_row("SELECT COUNT(*) FROM outbox", [], |r| r.get(0))
        .expect("flushed");
    assert_eq!(after, 0);
    let tasks: Value = client
        .get(format!("{url}/v1/tasks"))
        .send()
        .expect("tasks")
        .json()
        .expect("JSON");
    assert_eq!(tasks.as_array().expect("array").len(), 2);
}

#[test]
fn cli_configuration_and_usage_failures_have_distinct_exit_codes() {
    let directory = TempDir::new().expect("temp");
    for args in [
        vec!["serve", "--config", "missing.yaml"],
        vec!["--timeout", "NaN", "status"],
        vec!["brightness", "101"],
    ] {
        let output = Command::new(env!("CARGO_BIN_EXE_info-tv"))
            .args(&args)
            .current_dir(directory.path())
            .output()
            .expect("CLI");
        assert_eq!(output.status.code(), Some(2), "args={args:?}");
    }
    std::fs::write(directory.path().join("info-tv.yaml"), "unknown: true").expect("bad config");
    let output = Command::new(env!("CARGO_BIN_EXE_info-tv"))
        .args(["serve", "--state-dir"])
        .arg(directory.path().join("state"))
        .current_dir(directory.path())
        .output()
        .expect("CLI");
    assert_eq!(output.status.code(), Some(2));
    // Client commands must ignore an unrelated working-directory server YAML.
    let output = Command::new(env!("CARGO_BIN_EXE_info-tv"))
        .args(["--url", "http://127.0.0.1:1", "status"])
        .current_dir(directory.path())
        .output()
        .expect("client");
    assert_eq!(output.status.code(), Some(1));
}
