//! Real executable tests for crash recovery, YAML lookup, and hook outbox delivery.

use std::{
    io::{Read, Write},
    path::Path,
    process::{Child, Command, Stdio},
    time::{Duration, Instant},
};

use info_tv::{process as producer, tasks::TaskEvent};
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
            .args(["serve", "--config"])
            .arg(directory.join("info-tv.yaml"))
            .arg("--state-dir")
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

/// Run only as a copied AGY-named child, preserving a real hook ancestry chain.
#[test]
#[ignore = "subprocess helper invoked by producer lifecycle tests"]
fn agy_parent_process() {
    let directory = std::env::var_os("INFO_TV_TEST_PRODUCER").expect("producer directory");
    let directory = Path::new(&directory);
    let payload = json!({
        "conversationId":"producer-session", "lastUserInput":"Lifecycle regression",
        "invocationNum":0, "initialNumSteps":1
    });
    let mut hook = Command::new(env!("CARGO_BIN_EXE_info-tv"))
        .args(["hook", "agy", "PreInvocation", "--state-file"])
        .arg(directory.join("hooks.sqlite3"))
        .args(["--url", "http://127.0.0.1:1"])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .expect("native hook child");
    hook.stdin
        .take()
        .expect("stdin")
        .write_all(payload.to_string().as_bytes())
        .expect("payload");
    assert!(hook.wait().expect("hook exit").success());
    std::fs::write(directory.join("ready"), "ready").expect("ready");
    // Closing our parent's stdin permits normal process exit without a timer.
    let _ = std::io::stdin().read(&mut [0]);
}

/// Start a live producer with an offline hook event already persisted in its outbox.
fn start_producer(directory: &Path) -> (Process, TaskEvent) {
    let executable = directory.join(if cfg!(windows) { "agy.exe" } else { "agy" });
    std::fs::copy(
        std::env::current_exe().expect("test executable"),
        &executable,
    )
    .expect("copy producer");
    let mut command = Command::new(executable);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    let mut process = Process(
        command
            .args(["--exact", "agy_parent_process", "--ignored"])
            .env("INFO_TV_TEST_PRODUCER", directory)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("producer"),
    );
    let deadline = Instant::now() + Duration::from_secs(10);
    while !directory.join("ready").exists() {
        assert!(process.0.try_wait().expect("producer status").is_none());
        assert!(Instant::now() < deadline, "producer hook startup timeout");
        std::thread::sleep(Duration::from_millis(20));
    }
    let connection = rusqlite::Connection::open(directory.join("hooks.sqlite3")).expect("ledger");
    let payload: String = connection
        .query_row("SELECT payload FROM outbox", [], |row| row.get(0))
        .expect("outbox");
    let event: TaskEvent = serde_json::from_str(&payload).expect("immutable task event");
    assert_eq!(event.producer_process, producer::identify(process.0.id()));
    assert!(event.producer_process.is_some());
    (process, event)
}

/// Retry from a different process without replacing the captured producer identity.
fn flush_producer(directory: &Path, url: &str) {
    let output = Command::new(env!("CARGO_BIN_EXE_info-tv"))
        .args(["hook", "agy", "--flush", "--state-file"])
        .arg(directory.join("hooks.sqlite3"))
        .args(["--url", url])
        .output()
        .expect("flush");
    assert!(output.status.success());
    assert!(output.stderr.is_empty(), "flush error: {:?}", output.stderr);
}

#[test]
fn agy_owner_exit_retires_cards_and_preserves_a_new_execution() {
    let directory = TempDir::new().expect("temp");
    let port = free_port();
    std::fs::write(
        directory.path().join("info-tv.yaml"),
        format!("serial_port: info-tv-absent-test-port\nhttp_port: {port}\n"),
    )
    .expect("config");
    let state = directory.path().join("state");
    let url = format!("http://127.0.0.1:{port}");
    let client = reqwest::blocking::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(3))
        .build()
        .expect("client");
    let (mut owner, event) = start_producer(directory.path());
    let identity = event.producer_process.expect("owner");
    assert!(producer::exited(&[identity]).is_empty());
    let mut host = start(directory.path(), &state);
    wait_online(&client, &url, &mut host);
    flush_producer(directory.path(), &url);
    drop(host);
    let mut host = start(directory.path(), &state);
    wait_online(&client, &url, &mut host);
    let tasks: Value = client
        .get(format!("{url}/v1/tasks"))
        .send()
        .expect("tasks")
        .json()
        .expect("JSON");
    assert_eq!(
        tasks[0]["producer_process"],
        serde_json::to_value(identity).expect("identity")
    );

    // The old process also owns an independent card, which must disappear on exit.
    let mut other = event.clone();
    other.event_id = Uuid::new_v4().simple().to_string();
    other.task_id = "other-turn".into();
    other.conversation_id = Some("other-session".into());
    client
        .post(format!("{url}/v1/task-events"))
        .json(&other)
        .send()
        .expect("other")
        .error_for_status()
        .expect("admit other");

    // A transiently unreadable callback must preserve the registered owner.
    other.event_id = Uuid::new_v4().simple().to_string();
    other.sequence = 2;
    other.producer_process = None;
    client
        .post(format!("{url}/v1/task-events"))
        .json(&other)
        .send()
        .expect("unreadable owner update")
        .error_for_status()
        .expect("admit update");

    let mut resumed = event.clone();
    resumed.event_id = Uuid::new_v4().simple().to_string();
    resumed.task_id = "new-turn".into();
    resumed.run_sequence = Some(2);
    resumed.producer_process = producer::identify(std::process::id());
    client
        .post(format!("{url}/v1/task-events"))
        .json(&resumed)
        .send()
        .expect("resume")
        .error_for_status()
        .expect("admit resume");

    // Forced termination has no exit callback and leaves any producer files intact.
    owner.0.kill().expect("terminate producer");
    owner.0.wait().expect("reap producer");
    assert_eq!(producer::exited(&[identity]), vec![identity]);
    // Observe the durable database, rather than triggering cleanup through a GET.
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        let connection = rusqlite::Connection::open(state.join("host.sqlite3")).expect("database");
        let payload: String = connection
            .query_row("SELECT payload FROM host_state WHERE id=1", [], |row| {
                row.get(0)
            })
            .expect("state");
        let stored: Value = serde_json::from_str(&payload).expect("stored state");
        if stored["tasks"]["tasks"].as_array().expect("cards").len() == 1 {
            assert_eq!(stored["tasks"]["tasks"][0]["event"]["task_id"], "new-turn");
            break;
        }
        assert!(
            Instant::now() < deadline,
            "maintenance did not retire exited producer"
        );
        std::thread::sleep(Duration::from_millis(20));
    }
    other.event_id = Uuid::new_v4().simple().to_string();
    other.sequence = 3;
    let late: Value = client
        .post(format!("{url}/v1/task-events"))
        .json(&other)
        .send()
        .expect("late event")
        .json()
        .expect("JSON");
    assert_eq!(late["outcome"], "closed");
    drop(host);
}

#[test]
fn agy_normal_exit_during_service_downtime_is_retired_on_restart() {
    let directory = TempDir::new().expect("temp");
    let port = free_port();
    std::fs::write(
        directory.path().join("info-tv.yaml"),
        format!("serial_port: info-tv-absent-test-port\nhttp_port: {port}\n"),
    )
    .expect("config");
    let state = directory.path().join("state");
    let url = format!("http://127.0.0.1:{port}");
    let client = reqwest::blocking::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(3))
        .build()
        .expect("client");
    let (mut owner, _) = start_producer(directory.path());
    let mut host = start(directory.path(), &state);
    wait_online(&client, &url, &mut host);
    flush_producer(directory.path(), &url);
    drop(host);
    drop(owner.0.stdin.take());
    assert!(owner.0.wait().expect("normal producer exit").success());
    let mut host = start(directory.path(), &state);
    wait_online(&client, &url, &mut host);
    let tasks: Value = client
        .get(format!("{url}/v1/tasks"))
        .send()
        .expect("tasks")
        .json()
        .expect("JSON");
    assert_eq!(tasks, json!([]));
    drop(host);
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
    assert!(state.join("host.sqlite3").is_file());
    assert!(state.join("logs").is_dir());
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
    let output = Command::new(env!("CARGO_BIN_EXE_info-tv"))
        .args(["hook", "codex", "--flush", "--url", &url, "--state-file"])
        .arg(&outbox)
        .output()
        .expect("hook flush");
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
        .args(["serve", "--config", "info-tv.yaml", "--state-dir"])
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

/// Portable defaults follow the executable across working directories and moves.
#[test]
fn portable_defaults_keep_configuration_state_and_hooks_beside_the_binary() {
    let directory = TempDir::new().expect("temp");
    let installation = directory.path().join("info tv portable");
    let workspace = directory.path().join("unrelated workspace");
    let profile = directory.path().join("unused profile");
    std::fs::create_dir(&installation).expect("installation");
    std::fs::create_dir(&workspace).expect("workspace");
    std::fs::write(workspace.join("info-tv.yaml"), "unknown: true").expect("unrelated config");
    let binary_name = if cfg!(windows) {
        "info-tv.exe"
    } else {
        "info-tv"
    };
    let executable = installation.join(binary_name);
    std::fs::copy(env!("CARGO_BIN_EXE_info-tv"), &executable).expect("copy executable");
    let port = free_port();
    std::fs::write(
        installation.join("info-tv.yaml"),
        format!("serial_port: info-tv-absent-test-port\nhttp_port: {port}\n"),
    )
    .expect("portable config");
    let client = reqwest::blocking::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(2))
        .build()
        .expect("client");
    let url = format!("http://127.0.0.1:{port}");
    let launch = |executable: &Path| {
        Process(
            Command::new(executable)
                .arg("serve")
                .current_dir(&workspace)
                .env("LOCALAPPDATA", &profile)
                .env("HOME", &profile)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .expect("portable service"),
        )
    };
    let mut host = launch(&executable);
    wait_online(&client, &url, &mut host);
    client
        .put(format!("{url}/v1/device/settings"))
        .json(&json!({"brightness_percent":37}))
        .send()
        .expect("settings")
        .error_for_status()
        .expect("accepted");
    assert!(installation.join("data/host.sqlite3").is_file());
    assert!(installation.join("logs").is_dir());
    assert!(!installation.join("data/logs").exists());
    for source in ["codex", "agy", "zcode"] {
        let output = Command::new(&executable)
            .args(["hook", source, "--flush", "--url", "http://127.0.0.1:1"])
            .current_dir(&workspace)
            .env("LOCALAPPDATA", &profile)
            .env("HOME", &profile)
            .output()
            .expect("hook flush");
        assert!(output.status.success());
        assert!(output.stderr.is_empty(), "{:?}", output.stderr);
        assert!(
            installation
                .join(format!("data/{source}-hooks.sqlite3"))
                .is_file()
        );
    }
    drop(host);
    let relocated = directory.path().join("relocated info tv");
    std::fs::rename(&installation, &relocated).expect("move portable installation");
    let mut host = launch(&relocated.join(binary_name));
    wait_online(&client, &url, &mut host);
    let settings: Value = client
        .get(format!("{url}/v1/device/settings"))
        .send()
        .expect("restored settings")
        .json()
        .expect("JSON");
    assert_eq!(settings["brightness_percent"], 37);
    assert!(!workspace.join("data").exists());
    assert!(!workspace.join("logs").exists());
    assert!(!profile.exists());
}
