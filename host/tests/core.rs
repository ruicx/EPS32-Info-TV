//! Regression coverage for contracts, durable state, and cross-language framing.

use std::{path::Path, time::Duration};

use axum::{
    Router,
    body::{Body, to_bytes},
    http::Request,
};
use info_tv::{
    config::{LockAction, Settings},
    http,
    protocol::{self, pb},
    runtime::{Coordinator, Handle, Operation},
    storage::Database,
    tasks::{TaskEvent, TaskState, TaskStore},
    transport,
};
use prost::Message;
use serde_json::{Value, json};
use tempfile::TempDir;
use tokio::sync::{mpsc, watch};
use tower::ServiceExt;
use uuid::Uuid;

/// Return a valid source event that can be overridden in individual regressions.
fn event(task: &str, sequence: i64, state: &str) -> Value {
    json!({"event_id":Uuid::new_v4().simple().to_string(),"source":"test","task_id":task,
        "sequence":sequence,"state":state,"title":"Build"})
}

/// Isolated production coordinator and router, without accessing a physical port.
struct Host {
    handle: Handle,
    router: Router,
    stop: watch::Sender<bool>,
    events: mpsc::Sender<transport::Event>,
    commands: Option<mpsc::Receiver<transport::Command>>,
    actor: tokio::task::JoinHandle<anyhow::Result<()>>,
    worker: std::thread::JoinHandle<()>,
}

impl Host {
    async fn open(path: &Path, settings: Settings) -> Self {
        let (actor, handle, worker) = Coordinator::open(settings, path)
            .await
            .expect("open coordinator");
        let router = http::router(handle.clone());
        let (stop, receive_stop) = watch::channel(false);
        let (events, receive) = mpsc::channel(32);
        let (send, commands) = mpsc::channel(8);
        let actor = tokio::spawn(actor.run(receive, send, receive_stop));
        Self {
            handle,
            router,
            stop,
            events,
            commands: Some(commands),
            actor,
            worker,
        }
    }

    async fn request(&self, method: &str, path: &str, body: Option<Value>) -> (u16, Value) {
        let request = Request::builder()
            .method(method)
            .uri(path)
            .header("content-type", "application/json")
            .body(Body::from(body.map_or_else(String::new, |v| v.to_string())))
            .expect("request");
        let response = self.router.clone().oneshot(request).await.expect("router");
        let status = response.status().as_u16();
        let bytes = to_bytes(response.into_body(), 1_048_576)
            .await
            .expect("body");
        (
            status,
            serde_json::from_slice(&bytes).expect("JSON response"),
        )
    }

    async fn finish(self) {
        self.stop.send(true).expect("signal");
        self.actor
            .await
            .expect("coordinator task")
            .expect("coordinator result");
        tokio::task::spawn_blocking(move || self.worker.join())
            .await
            .expect("worker join")
            .expect("worker");
    }
}

#[test]
fn yaml_discovery_strictness_and_precedence() {
    let directory = TempDir::new().expect("temp");
    let cwd = directory.path();
    assert_eq!(
        Settings::load(None, cwd).expect("defaults").0.http_port,
        8765
    );
    std::fs::write(cwd.join("info-tv.yaml"), "usb_vid: 0x303A\nhttp_port: 9876").expect("write");
    let (settings, path) = Settings::load(None, cwd).expect("discovery");
    assert_eq!((settings.usb_vid, settings.http_port), (0x303a, 9876));
    assert_eq!(path, Some(cwd.join("info-tv.yaml")));
    std::fs::write(cwd.join("explicit.yaml"), "{}").expect("write");
    assert_eq!(
        Settings::load(Some(Path::new("explicit.yaml")), cwd)
            .expect("explicit")
            .0
            .http_port,
        8765
    );
    assert!(Settings::load(Some(Path::new("missing.yaml")), cwd).is_err());
    for invalid in [
        "",
        "[]",
        "null",
        "http_port: true",
        "http_port: '1234'",
        "http_port: 0",
        "usb_vid: 65536",
        "usb_pid: -1",
        "serial_port: 123",
        "serial_port: null",
        "unknown: true",
        "completed_retention_seconds: 0",
        "weather: {location: City, latitude: 91, longitude: 0}",
        "weather: {location: City, latitude: '31', longitude: 0}",
    ] {
        std::fs::write(cwd.join("info-tv.yaml"), invalid).expect("write");
        assert!(
            Settings::load(None, cwd).is_err(),
            "accepted invalid YAML: {invalid}"
        );
    }
}

#[test]
fn lock_action_accepts_only_documented_actions_and_defaults_to_none() {
    let directory = TempDir::new().expect("temp");
    assert_eq!(
        Settings::load(None, directory.path())
            .expect("defaults")
            .0
            .lock_action,
        LockAction::None
    );
    let path = directory.path().join("info-tv.yaml");
    for (name, action) in [
        ("none", LockAction::None),
        ("screen_off", LockAction::ScreenOff),
        ("deep_sleep", LockAction::DeepSleep),
    ] {
        std::fs::write(&path, format!("lock_action: {name}\n")).expect("write");
        assert_eq!(
            Settings::load(None, directory.path())
                .expect("boolean")
                .0
                .lock_action,
            action
        );
    }
    for invalid in ["true", "1", "null", "[]", "shutdown"] {
        std::fs::write(&path, format!("lock_action: {invalid}\n")).expect("write");
        assert!(Settings::load(None, directory.path()).is_err());
    }
}

#[test]
fn unlock_poll_seconds_is_bounded_and_defaults_disabled() {
    let directory = TempDir::new().expect("temp");
    assert_eq!(
        Settings::load(None, directory.path())
            .expect("defaults")
            .0
            .unlock_poll_seconds,
        0
    );
    let path = directory.path().join("info-tv.yaml");
    for seconds in [0, 5, 3600] {
        std::fs::write(
            &path,
            format!("lock_action: deep_sleep\nunlock_poll_seconds: {seconds}\n"),
        )
        .expect("write");
        assert_eq!(
            Settings::load(None, directory.path())
                .expect("interval")
                .0
                .unlock_poll_seconds,
            seconds
        );
    }
    for invalid in ["true", "'5'", "null", "-1", "3601"] {
        std::fs::write(&path, format!("unlock_poll_seconds: {invalid}\n")).expect("write");
        assert!(Settings::load(None, directory.path()).is_err());
    }
}

#[tokio::test]
async fn session_lock_overrides_brightness_without_persisting_zero() {
    let directory = TempDir::new().expect("temp");
    let settings = Settings {
        lock_action: LockAction::ScreenOff,
        ..Settings::default()
    };
    let host = Host::open(directory.path(), settings.clone()).await;
    host.handle
        .request(Operation::Brightness(35))
        .await
        .expect("brightness");
    let locked = host
        .handle
        .request(Operation::SessionLocked(true))
        .await
        .expect("lock");
    assert_eq!(locked["brightness_percent"], 35);
    assert_eq!(locked["effective_brightness_percent"], 0);
    assert_eq!(locked["screen_off_for_lock"], true);
    let changed = host
        .handle
        .request(Operation::Brightness(60))
        .await
        .expect("new target");
    assert_eq!(changed["brightness_percent"], 60);
    assert_eq!(changed["effective_brightness_percent"], 0);
    host.finish().await;

    let host = Host::open(directory.path(), settings).await;
    host.handle
        .request(Operation::SessionLocked(true))
        .await
        .expect("lock after restart");
    let unlocked = host
        .handle
        .request(Operation::SessionLocked(false))
        .await
        .expect("unlock");
    assert_eq!(unlocked["brightness_percent"], 60);
    assert_eq!(unlocked["effective_brightness_percent"], 60);
    host.handle
        .request(Operation::Brightness(0))
        .await
        .expect("manual off");
    host.handle
        .request(Operation::SessionLocked(true))
        .await
        .expect("lock");
    let unlocked = host
        .handle
        .request(Operation::SessionLocked(false))
        .await
        .expect("unlock");
    assert_eq!(unlocked["effective_brightness_percent"], 0);
    host.finish().await;

    let host = Host::open(directory.path(), Settings::default()).await;
    host.handle
        .request(Operation::Brightness(35))
        .await
        .expect("brightness");
    let disabled = host
        .handle
        .request(Operation::SessionLocked(true))
        .await
        .expect("disabled");
    assert_eq!(disabled["effective_brightness_percent"], 35);
    assert_eq!(disabled["screen_off_for_lock"], false);
    host.finish().await;
}

#[tokio::test]
async fn session_closure_retires_durably_without_a_notification() {
    let directory = TempDir::new().expect("temp");
    let settings = Settings::default();
    let host = Host::open(directory.path(), settings.clone()).await;
    let mut start = event("turn", 1, "running");
    start["conversation_id"] = json!("session");
    start["run_sequence"] = json!(1);
    let (_, admitted) = host
        .request("POST", "/v1/task-events", Some(start.clone()))
        .await;
    let mut close = start.clone();
    close["event_id"] = json!(Uuid::new_v4().simple().to_string());
    close["sequence"] = json!(2);
    close["state"] = json!("closed");
    let (status, result) = host
        .request("POST", "/v1/task-events", Some(close.clone()))
        .await;
    assert_eq!(status, 202);
    assert_eq!(result["card_id"], admitted["card_id"]);
    assert_eq!(result["notification"], "none");
    assert_eq!(host.request("GET", "/v1/tasks", None).await.1, json!([]));
    host.finish().await;

    let host = Host::open(directory.path(), settings).await;
    assert_eq!(host.request("GET", "/v1/tasks", None).await.1, json!([]));
    assert_eq!(
        host.request("POST", "/v1/task-events", Some(close)).await.1["outcome"],
        "duplicate"
    );
    start["event_id"] = json!(Uuid::new_v4().simple().to_string());
    start["sequence"] = json!(3);
    assert_eq!(
        host.request("POST", "/v1/task-events", Some(start.clone()))
            .await
            .1["outcome"],
        "closed"
    );
    start["event_id"] = json!(Uuid::new_v4().simple().to_string());
    start["task_id"] = json!("next-turn");
    start["run_sequence"] = json!(2);
    assert_eq!(
        host.request("POST", "/v1/task-events", Some(start)).await.1["outcome"],
        "accepted"
    );
    host.finish().await;
}

#[tokio::test]
async fn agy_session_exit_retires_task_and_removes_from_device() {
    let directory = TempDir::new().expect("temp");
    let settings = Settings::default();
    let host = Host::open(directory.path(), settings.clone()).await;

    let agy_event = json!({
        "event_id": Uuid::new_v4().simple().to_string(),
        "source": "agy",
        "task_id": "agy-task-1",
        "sequence": 1,
        "state": "running",
        "title": "AGY running task",
        "conversation_id": "nonexistent-agy-conv",
        "run_sequence": 1,
    });
    let (status, admitted) = host
        .request("POST", "/v1/task-events", Some(agy_event))
        .await;
    assert_eq!(status, 202);
    assert!(admitted["card_id"].is_string());

    // Upon the next query or expiration tick, inactive agy conversation is retired
    let (_, tasks) = host.request("GET", "/v1/tasks", None).await;
    assert_eq!(tasks, json!([]));

    host.finish().await;

    // After restart, it remains cleanly closed
    let host = Host::open(directory.path(), settings).await;
    assert_eq!(host.request("GET", "/v1/tasks", None).await.1, json!([]));
    host.finish().await;
}

#[test]
fn protocol_vectors_corruption_and_bounds() {
    let hex = include_str!("../../protocol/test_vectors/status_frame.hex").trim();
    let bytes: Vec<u8> = (0..hex.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).expect("hex"))
        .collect();
    let mut decoder = protocol::FrameDecoder::default();
    let mut payloads = Vec::new();
    for chunk in bytes.chunks(3) {
        payloads.extend(decoder.feed(chunk));
    }
    assert_eq!(payloads.len(), 1);
    let message = pb::Envelope::decode(payloads[0].as_slice()).expect("protobuf");
    assert_eq!(message.message_id, "golden");
    assert_eq!(
        protocol::encode_frame(&message.encode_to_vec()).expect("frame"),
        bytes
    );
    let mut corrupt = bytes.clone();
    corrupt[10] ^= 1;
    assert!(decoder.feed(&corrupt).is_empty());
    assert!(decoder.feed(&[1u8; 5000]).is_empty());
    assert_eq!(decoder.feed(&bytes), payloads);
    for value in [
        vec![0u8; 4096],
        vec![255u8; 4096],
        (0..4096).map(|i| i as u8).collect(),
    ] {
        let frame = protocol::encode_frame(&value).expect("max frame");
        assert_eq!(decoder.feed(&frame), vec![value]);
    }
    assert!(protocol::encode_frame(&[]).is_err());
    assert!(protocol::encode_frame(&[1u8; 4097]).is_err());
}

#[test]
fn recent_question_hint_survives_activity_without_renewing_and_clears_at_end() {
    let mut store = TaskStore::default();
    let mut value = event("question-run", 1, "running");
    value["question_id"] = json!("question-1");
    let first: TaskEvent = serde_json::from_value(value.clone()).expect("question event");
    let update = store.prepare(&first, 1000).expect("admit question");
    assert!(!update.notify);
    let status = info_tv::views::card(&update.record, 2000)
        .view
        .expect("view")
        .content
        .expect("status");
    let pb::view::Content::Status(status) = status;
    assert_eq!(status.recent_question_seconds, 29);
    let pb::view::Content::Status(expired) = info_tv::views::card(&update.record, 31_000)
        .view
        .expect("view")
        .content
        .expect("status");
    assert_eq!(expired.recent_question_seconds, 0);
    assert_eq!(
        serde_json::to_value(&update.record).expect("record")["question_expires_at_ms"],
        31_000
    );
    store.commit(&update);
    let duplicate = store.prepare(&first, 5000).expect("duplicate");
    assert_eq!(
        serde_json::to_value(&duplicate.record).expect("record")["question_expires_at_ms"],
        31_000
    );
    for (sequence, state, question, expected) in [
        (2, "running", Value::Null, json!(31_000)),
        (3, "running", json!("question-2"), json!(33_000)),
        (4, "completed", Value::Null, Value::Null),
    ] {
        value["event_id"] = json!(Uuid::new_v4().simple().to_string());
        value["sequence"] = json!(sequence);
        value["state"] = json!(state);
        value["question_id"] = question;
        let incoming: TaskEvent = serde_json::from_value(value.clone()).expect("event");
        let update = store.prepare(&incoming, sequence * 1000).expect("update");
        assert_eq!(
            serde_json::to_value(&update.record).expect("record")["question_expires_at_ms"],
            expected
        );
        store.commit(&update);
    }
}

#[test]
fn domain_ordering_retirement_and_notifications() {
    let mut store = TaskStore::default();
    let mut first: TaskEvent = serde_json::from_value(event("run1", 1, "running")).expect("event");
    first.conversation_id = Some("thread".into());
    first.run_sequence = Some(1);
    first.validate().expect("valid");
    let update = store.prepare(&first, 1000).expect("admit");
    let id = update.record.card_id.clone();
    store.commit(&update);
    assert_eq!(
        store.prepare(&first, 2000).expect("duplicate").outcome,
        "duplicate"
    );
    let mut conflict = first.clone();
    conflict.title = "Different".into();
    assert_eq!(
        store.prepare(&conflict, 2000).expect_err("conflict").status,
        409
    );
    let mut completed = first.clone();
    completed.event_id = Uuid::new_v4().simple().to_string();
    completed.sequence = 2;
    completed.state = TaskState::Completed;
    let update = store.prepare(&completed, 2000).expect("complete");
    assert!(update.notify);
    store.commit(&update);
    completed.sequence = 3;
    completed.event_id = Uuid::new_v4().simple().to_string();
    let update = store.prepare(&completed, 3000).expect("repeat");
    assert!(!update.notify);
    assert_eq!(update.record.completed_at_ms, Some(2000));
    store.commit(&update);
    assert_eq!(store.expire(4000, 2), vec![id]);
    completed.sequence = 4;
    completed.event_id = Uuid::new_v4().simple().to_string();
    assert_eq!(
        store.prepare(&completed, 5000).expect("closed").outcome,
        "closed"
    );
    let mut next = first.clone();
    next.task_id = "run2".into();
    next.run_sequence = Some(2);
    next.event_id = Uuid::new_v4().simple().to_string();
    let update = store.prepare(&next, 5000).expect("next run");
    store.commit(&update);
    assert_eq!(
        store.prepare(&completed, 5000).expect("late run").outcome,
        "stale"
    );
}

#[tokio::test]
async fn http_validation_capacity_and_independent_weather() {
    let directory = TempDir::new().expect("temp");
    let host = Host::open(directory.path(), Settings::default()).await;
    let original = event("run", 1, "running");
    for (field, value) in [
        ("progress_percent", json!(true)),
        ("progress_percent", json!(101)),
        ("sequence", json!(0)),
        ("title", json!("界".repeat(30))),
        ("title", json!("\0bad")),
        ("state", json!("mystery")),
        ("icon", Value::Null),
        ("screen_x", json!(20)),
        ("conversation_id", json!("thread")),
        ("run_sequence", json!(1)),
        ("context", json!("界".repeat(22))),
    ] {
        let mut invalid = original.clone();
        invalid[field] = value;
        assert_eq!(
            host.request("POST", "/v1/task-events", Some(invalid))
                .await
                .0,
            422
        );
    }
    assert_eq!(host.request("GET", "/v1/tasks", None).await.1, json!([]));
    for index in 0..8 {
        assert_eq!(
            host.request(
                "POST",
                "/v1/task-events",
                Some(event(&format!("run{index}"), 1, "running"))
            )
            .await
            .0,
            202
        );
    }
    assert_eq!(
        host.request(
            "POST",
            "/v1/task-events",
            Some(event("overflow", 1, "running"))
        )
        .await
        .0,
        503
    );
    assert_eq!(
        host.request(
            "POST",
            "/v1/task-events",
            Some(event("unseen-closed", 1, "closed"))
        )
        .await
        .0,
        202
    );
    assert_eq!(
        host.request("GET", "/v1/tasks", None)
            .await
            .1
            .as_array()
            .expect("cards")
            .len(),
        8
    );
    assert_eq!(
        host.request("POST", "/v1/task-events", Some(event("run0", 2, "closed")))
            .await
            .0,
        202
    );
    assert_eq!(
        host.request(
            "POST",
            "/v1/task-events",
            Some(event("replacement", 1, "running"))
        )
        .await
        .0,
        202
    );
    assert_eq!(host.request("PUT", "/v1/weather", Some(json!({"location":"Harbin","temperature_c":0,"condition":"snow","daily_low_c":-10,"daily_high_c":0}))).await.0, 202);
    for invalid in [
        json!({}),
        json!({"brightness_percent":true}),
        json!({"brightness_percent":101}),
        json!({"brightness_percent":"30"}),
    ] {
        assert_eq!(
            host.request("PUT", "/v1/device/settings", Some(invalid))
                .await
                .0,
            422
        );
    }
    host.finish().await;
}

#[tokio::test]
async fn restart_restores_tasks_ordering_and_zero_brightness() {
    let directory = TempDir::new().expect("temp");
    let host = Host::open(directory.path(), Settings::default()).await;
    let first = event("active", 1, "running");
    let (_, response) = host
        .request("POST", "/v1/task-events", Some(first.clone()))
        .await;
    let id = response["card_id"].as_str().expect("id").to_owned();
    let closed = event("closed", 1, "completed");
    let (_, response) = host
        .request("POST", "/v1/task-events", Some(closed.clone()))
        .await;
    let closed_id = response["card_id"].as_str().expect("id");
    assert_eq!(
        host.request("DELETE", &format!("/v1/tasks/{closed_id}"), None)
            .await
            .0,
        202
    );
    assert_eq!(
        host.request(
            "PUT",
            "/v1/device/settings",
            Some(json!({"brightness_percent":0}))
        )
        .await
        .0,
        202
    );
    let old_session = host.request("GET", "/v1/device", None).await.1["session_id"].clone();
    host.finish().await;
    let host = Host::open(directory.path(), Settings::default()).await;
    let tasks = host.request("GET", "/v1/tasks", None).await.1;
    assert_eq!(tasks.as_array().expect("tasks").len(), 1);
    assert_eq!(tasks[0]["card_id"], id);
    assert_eq!(tasks[0]["revision"], 1);
    assert_eq!(tasks[0]["delivery"], json!({"state":"pending"}));
    assert_eq!(
        host.request("POST", "/v1/task-events", Some(first)).await.1["outcome"],
        "duplicate"
    );
    let mut late = closed;
    late["sequence"] = json!(2);
    late["event_id"] = json!(Uuid::new_v4().simple().to_string());
    assert_eq!(
        host.request("POST", "/v1/task-events", Some(late)).await.1["outcome"],
        "closed"
    );
    let settings = host.request("GET", "/v1/device/settings", None).await.1;
    assert_eq!(settings["brightness_percent"], 0);
    assert_eq!(settings["applied_brightness_percent"], Value::Null);
    assert_ne!(
        host.request("GET", "/v1/device", None).await.1["session_id"],
        old_session
    );
    host.finish().await;
}

#[tokio::test]
async fn failed_commit_does_not_admit_or_publish() {
    let directory = TempDir::new().expect("temp");
    let host = Host::open(directory.path(), Settings::default()).await;
    let connection =
        rusqlite::Connection::open(directory.path().join("host.sqlite3")).expect("database");
    connection.execute_batch("CREATE TRIGGER reject_write BEFORE UPDATE ON host_state BEGIN SELECT RAISE(FAIL,'injected write failure'); END;").expect("trigger");
    let first = event("run", 1, "completed");
    assert_eq!(
        host.request("POST", "/v1/task-events", Some(first.clone()))
            .await
            .0,
        503
    );
    assert_eq!(host.request("GET", "/v1/tasks", None).await.1, json!([]));
    assert_eq!(
        host.request(
            "PUT",
            "/v1/device/settings",
            Some(json!({"brightness_percent":0}))
        )
        .await
        .0,
        503
    );
    assert_eq!(
        host.request("GET", "/v1/device/settings", None).await.1["brightness_percent"],
        100
    );
    connection
        .execute_batch("DROP TRIGGER reject_write")
        .expect("drop trigger");
    assert_eq!(
        host.request("POST", "/v1/task-events", Some(first)).await.1["outcome"],
        "accepted"
    );
    host.finish().await;
}

#[tokio::test]
async fn producer_bursts_during_a_slow_commit_remain_bounded() {
    let directory = TempDir::new().expect("temp");
    let host = Host::open(directory.path(), Settings::default()).await;
    let mut connection =
        rusqlite::Connection::open(directory.path().join("host.sqlite3")).expect("database");
    let lock = connection
        .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .expect("hold write lock");
    let mut requests = tokio::task::JoinSet::new();
    for index in 0..100 {
        let router = host.router.clone();
        requests.spawn(async move {
            let body = event(&format!("burst-{index}"), 1, "running");
            let request = Request::builder()
                .method("POST")
                .uri("/v1/task-events")
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .expect("request");
            router
                .oneshot(request)
                .await
                .expect("response")
                .status()
                .as_u16()
        });
    }
    tokio::time::sleep(Duration::from_millis(50)).await;
    lock.rollback().expect("release write lock");
    let mut accepted = 0;
    let mut rejected = 0;
    while let Some(status) = requests.join_next().await {
        match status.expect("request task") {
            202 => accepted += 1,
            503 => rejected += 1,
            status => panic!("Unexpected status {status}"),
        }
    }
    assert_eq!(accepted, 8);
    assert_eq!(rejected, 92);
    assert_eq!(
        host.request("GET", "/v1/tasks", None)
            .await
            .1
            .as_array()
            .expect("tasks")
            .len(),
        8
    );
    host.finish().await;
}

#[tokio::test]
async fn recovery_preserves_expiry_and_suppresses_old_notifications() {
    use info_tv::storage::{StoredState, Timed};
    use info_tv::weather::{AlertRequest, WeatherRequest};
    let directory = TempDir::new().expect("temp");
    let now = chrono::Utc::now().timestamp_millis();
    let mut stored = StoredState {
        saved_at_ms: now - 10_000,
        ..Default::default()
    };
    let completed: TaskEvent =
        serde_json::from_value(event("finished", 1, "completed")).expect("event");
    let update = stored
        .tasks
        .prepare(&completed, now - 10_000)
        .expect("admit");
    stored.tasks.commit(&update);
    stored.weather = Some(Timed {
        value: WeatherRequest {
            location: "City".into(),
            temperature_c: 20,
            condition: "clear".into(),
            valid_for_seconds: 1,
            daily_low_c: None,
            daily_high_c: None,
        },
        expires_at_ms: now - 1,
    });
    stored.alert = Some(Timed {
        value: AlertRequest {
            alert_id: Uuid::new_v4().simple().to_string(),
            sequence: 1,
            title: "Rain".into(),
            source: "Test".into(),
            location: "City".into(),
            severity: "yellow".into(),
            detail: String::new(),
            valid_for_seconds: 1,
        },
        expires_at_ms: now - 1,
    });
    let mut database = Database::open(directory.path()).expect("database");
    database.save(&stored).expect("save");
    drop(database);
    let host = Host::open(
        directory.path(),
        Settings {
            completed_retention_seconds: 1,
            ..Default::default()
        },
    )
    .await;
    assert_eq!(host.request("GET", "/v1/tasks", None).await.1, json!([]));
    assert_eq!(
        host.request("GET", "/v1/weather", None).await.1["state"],
        "stale"
    );
    let alert = host.request("GET", "/v1/weather/alert", None).await.1;
    assert_eq!(alert["state"], "expired");
    assert_eq!(alert["notification"], "suppressed");
    assert_eq!(
        host.request(
            "POST",
            "/v1/task-events",
            Some(serde_json::to_value(&completed).expect("event"))
        )
        .await
        .1["outcome"],
        "duplicate"
    );
    host.finish().await;
}

#[test]
fn instance_lock_and_future_schema_are_rejected() {
    let directory = TempDir::new().expect("temp");
    let database = Database::open(directory.path()).expect("open");
    assert!(Database::open(directory.path()).is_err());
    drop(database);
    let connection =
        rusqlite::Connection::open(directory.path().join("host.sqlite3")).expect("database");
    connection
        .pragma_update(None, "user_version", 2)
        .expect("future schema");
    drop(connection);
    assert!(Database::open(directory.path()).is_err());
}

#[tokio::test]
async fn rust_http_to_cpp_firmware_core() {
    let default = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../build/native-tests")
        .join(if cfg!(windows) {
            "Debug/protocol_bridge.exe"
        } else {
            "protocol_bridge"
        });
    let executable = std::env::var_os("INFO_TV_PROTOCOL_BRIDGE")
        .map(std::path::PathBuf::from)
        .unwrap_or(default);
    if !executable.exists() {
        eprintln!("SKIP: build firmware/tests or set INFO_TV_PROTOCOL_BRIDGE");
        return;
    }
    let directory = TempDir::new().expect("temp");
    let mut host = Host::open(
        directory.path(),
        Settings {
            lock_action: LockAction::DeepSleep,
            unlock_poll_seconds: 5,
            ..Settings::default()
        },
    )
    .await;
    let mut child = tokio::process::Command::new(executable)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .expect("bridge");
    let read = child.stdout.take().expect("stdout");
    let write = child.stdin.take().expect("stdin");
    let events = host.events.clone();
    let mut commands = host.commands.take().expect("commands");
    let mut stop = host.stop.subscribe();
    let io = tokio::spawn(async move {
        transport::run_stream(read, write, 1, &events, &mut commands, &mut stop).await
    });
    let wait = |handle: Handle, predicate: fn(&Value) -> bool| async move {
        tokio::time::timeout(Duration::from_secs(5), async {
            loop {
                let value = handle.request(Operation::Status).await.expect("status");
                if predicate(&value) {
                    break value;
                }
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .expect("firmware feedback timeout")
    };
    wait(host.handle.clone(), |v| v["state"] == "online").await;
    assert_eq!(
        host.handle
            .request(Operation::Settings)
            .await
            .expect("settings")["unlock_poll_seconds"],
        5
    );
    assert_eq!(
        host.handle
            .request(Operation::Settings)
            .await
            .expect("settings")["power_delivery"]["applied"],
        true
    );
    assert_eq!(
        host.request(
            "PUT",
            "/v1/device/settings",
            Some(json!({"brightness_percent":0}))
        )
        .await
        .0,
        202
    );
    wait(host.handle.clone(), |v| {
        v["settings"]["applied_brightness_percent"] == 0
    })
    .await;
    let mut running = event("cpp-build", 1, "running");
    running["question_id"] = json!("cpp-question");
    let (_, response) = host
        .request("POST", "/v1/task-events", Some(running.clone()))
        .await;
    assert_eq!(response["outcome"], "accepted");
    wait(host.handle.clone(), |v| {
        v["deliveries"]
            .as_array()
            .expect("deliveries")
            .iter()
            .any(|d| {
                d["message_id"].as_str().is_some_and(|id| id.contains(':')) && d["accepted"] == true
            })
    })
    .await;
    assert_eq!(
        host.request("GET", "/v1/tasks", None).await.1[0]["delivery"]["presented"],
        false
    );
    host.request(
        "PUT",
        "/v1/device/settings",
        Some(json!({"brightness_percent":30})),
    )
    .await;
    wait(host.handle.clone(), |v| {
        v["settings"]["applied_brightness_percent"] == 30
    })
    .await;
    let presented = tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let tasks = host.request("GET", "/v1/tasks", None).await.1;
            if tasks[0]["delivery"]["presented"] == true {
                break tasks;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .expect("Presented feedback");
    assert_eq!(presented[0]["delivery"]["accepted"], true);
    let mut complete = running;
    complete["sequence"] = json!(2);
    complete["state"] = json!("completed");
    complete["event_id"] = json!(Uuid::new_v4().simple().to_string());
    assert_eq!(
        host.request("POST", "/v1/task-events", Some(complete))
            .await
            .1["notification"],
        "queued"
    );
    wait(host.handle.clone(), |v| {
        v["deliveries"]
            .as_array()
            .expect("deliveries")
            .iter()
            .any(|d| {
                d["message_id"].as_str().is_some_and(|id| !id.contains(':'))
                    && d["presented"] == true
            })
    })
    .await;
    host.handle
        .request(Operation::SessionLocked(true))
        .await
        .expect("lock policy");
    wait(host.handle.clone(), |v| {
        v["settings"]["power_delivery"]["applied"] == true
    })
    .await;
    host.handle
        .request(Operation::SessionLocked(false))
        .await
        .expect("unlock policy");
    wait(host.handle.clone(), |v| {
        v["settings"]["power_delivery"]["applied"] == true
    })
    .await;
    host.finish().await;
    io.await.expect("io task").expect("io");
    child.wait().await.expect("bridge exit");
}
