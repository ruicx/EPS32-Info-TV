//! Language-independent adapter fixtures and concurrent SQLite ledger regressions.

use info_tv::{hooks, tasks::TaskState};
use serde_json::{Value, json};
use tempfile::TempDir;

#[test]
fn python_reference_hook_transitions_match() {
    let directory = TempDir::new().expect("temp");
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/hook-transitions.json")).expect("fixtures");
    for (index, case) in cases.iter().enumerate() {
        let source = case["source"].as_str().expect("source");
        let result = hooks::capture(
            &directory.path().join(format!("{source}.sqlite3")),
            source,
            case["event"].as_str(),
            case["payload"].clone(),
        )
        .expect("capture");
        let actual = result.map_or(Value::Null, |event| {
            let mut value = serde_json::to_value(event).expect("event");
            let fields = value.as_object_mut().expect("object");
            fields.remove("event_id");
            fields.retain(|_, value| !value.is_null());
            value
        });
        assert_eq!(
            actual, case["expected"],
            "Python/Rust mismatch at case {index}"
        );
    }
}

#[test]
fn concurrent_callbacks_do_not_duplicate_a_transition() {
    let directory = TempDir::new().expect("temp");
    let path = directory.path().join("codex.sqlite3");
    let payload = json!({"hook_event_name":"UserPromptSubmit","session_id":"session","turn_id":"turn","prompt":"Build"});
    let threads: Vec<_> = (0..12)
        .map(|_| {
            let path = path.clone();
            let payload = payload.clone();
            std::thread::spawn(move || {
                hooks::capture(&path, "codex", None, payload).expect("capture")
            })
        })
        .collect();
    let count = threads
        .into_iter()
        .filter_map(|thread| thread.join().expect("thread"))
        .count();
    assert_eq!(count, 1);
    let connection = rusqlite::Connection::open(&path).expect("database");
    let count: i64 = connection
        .query_row("SELECT COUNT(*) FROM outbox", [], |row| row.get(0))
        .expect("outbox");
    assert_eq!(count, 1);
}

#[test]
fn codex_async_question_emits_one_running_hint_per_accepted_call() {
    let directory = TempDir::new().expect("temp");
    let path = directory.path().join("codex.sqlite3");
    let callback = |name: &str, id: &str, response: Value| {
        hooks::capture(
            &path,
            "codex",
            None,
            json!({
                "hook_event_name":name,"session_id":"session","turn_id":"turn",
                "prompt":"Build","tool_name":"request_user_input_async",
                "tool_use_id":id,"tool_response":response
            }),
        )
        .expect("capture")
    };
    callback("UserPromptSubmit", "", Value::Null).expect("start");
    assert!(callback("PreToolUse", "question-1", Value::Null).is_none());
    let question = callback("PostToolUse", "question-1", json!("{\"accepted\":true}"))
        .expect("accepted question hint");
    assert_eq!(question.state, TaskState::Running);
    assert_eq!(question.sequence, 2);
    assert_eq!(
        serde_json::to_value(&question).expect("event")["question_id"],
        "question-1"
    );
    assert!(callback("PostToolUse", "question-1", json!("{\"accepted\":true}")).is_none());
    assert!(callback("PostToolUse", "rejected", json!({"accepted":false})).is_none());
    let next =
        callback("PostToolUse", "question-2", json!({"accepted":true})).expect("next question");
    assert_eq!(next.sequence, 3);
    callback("Stop", "", Value::Null).expect("stop");
    assert!(callback("PostToolUse", "late", json!({"accepted":true})).is_none());
}

#[test]
fn codex_session_end_closes_latest_turn_once_and_allows_a_new_turn() {
    let directory = TempDir::new().expect("temp");
    let path = directory.path().join("codex.sqlite3");
    let callback = |name: &str, turn: Option<&str>| {
        hooks::capture(
            &path,
            "codex",
            None,
            json!({
                "hook_event_name":name,"session_id":"session","turn_id":turn,"prompt":"Build"
            }),
        )
        .expect("capture")
    };
    assert!(callback("SessionEnd", None).is_none());
    let first = callback("UserPromptSubmit", Some("first")).expect("start");
    callback("Stop", Some("first")).expect("stop");
    let second = callback("UserPromptSubmit", Some("second")).expect("start");
    let close = callback("SessionEnd", None).expect("close");
    assert_eq!(close.task_id, second.task_id);
    assert_eq!(close.run_sequence, Some(2));
    assert_eq!(close.state, TaskState::Closed);
    assert_eq!(close.sequence, 2);
    assert!(callback("SessionEnd", None).is_none());
    for turn in ["first", "second"] {
        assert!(callback("UserPromptSubmit", Some(turn)).is_none());
        assert!(callback("PreToolUse", Some(turn)).is_none());
        assert!(callback("Stop", Some(turn)).is_none());
    }
    let resumed = callback("UserPromptSubmit", Some("resumed")).expect("resume");
    assert_eq!(resumed.run_sequence, Some(3));
    assert_ne!(resumed.task_id, first.task_id);
    callback("Stop", Some("resumed")).expect("stop");
    let close = callback("SessionEnd", None).expect("close completed turn");
    assert_eq!(close.sequence, 3);
    assert_eq!(close.state, TaskState::Closed);
}

#[test]
fn zcode_aliases_and_invalid_capture_preserve_ledger() {
    let directory = TempDir::new().expect("temp");
    let path = directory.path().join("zcode.sqlite3");
    let first = hooks::capture(
        &path,
        "zcode",
        None,
        json!({"hookEventName":"UserPromptSubmit","sessionId":"session",
        "turnId":"turn","prompt":"Fix\n界","cwd":"D:\\project\\info_tv"}),
    )
    .expect("capture")
    .expect("event");
    assert_eq!(first.context, "info_tv");
    assert!(!first.title.contains('\n'));
    assert!(
        hooks::capture(
            &path,
            "zcode",
            None,
            json!({"hookEventName":"Stop","sessionId":"session"})
        )
        .is_err()
    );
    let complete = hooks::capture(
        &path,
        "zcode",
        None,
        json!({"hookEventName":"Stop","sessionId":"session",
        "turnId":"turn","responseText":"Done"}),
    )
    .expect("capture")
    .expect("event");
    assert_eq!(complete.task_id, first.task_id);
    assert_eq!(complete.sequence, 2);
    assert_eq!(complete.detail, "Done");
}

#[test]
fn agy_tool_use_transitions_to_waiting_input_and_back_to_running() {
    let directory = TempDir::new().expect("temp");
    let path = directory.path().join("agy.sqlite3");
    let start = hooks::capture(
        &path,
        "agy",
        Some("PreInvocation"),
        json!({
            "conversationId": "conv-1",
            "lastUserInput": "Run cargo test",
            "workspacePaths": ["D:\\project\\info_tv"],
            "invocationNum": 0,
            "initialNumSteps": 1
        }),
    )
    .expect("capture")
    .expect("event");
    assert_eq!(start.state, TaskState::Running);
    assert_eq!(start.sequence, 1);

    // Readonly tools are ignored
    let readonly = hooks::capture(
        &path,
        "agy",
        Some("PreToolUse"),
        json!({
            "conversationId": "conv-1",
            "lastUserInput": "Run cargo test",
            "workspacePaths": ["D:\\project\\info_tv"],
            "toolCall": {
                "name": "read_file"
            }
        }),
    )
    .expect("capture");
    assert!(readonly.is_none());

    let waiting = hooks::capture(
        &path,
        "agy",
        Some("PreToolUse"),
        json!({
            "conversationId": "conv-1",
            "lastUserInput": "Run cargo test",
            "workspacePaths": ["D:\\project\\info_tv"],
            "toolCall": {
                "name": "run_command"
            }
        }),
    )
    .expect("capture")
    .expect("event");
    assert_eq!(waiting.state, TaskState::WaitingInput);
    assert_eq!(waiting.sequence, 2);
    assert_eq!(waiting.detail, "Approval requested: run_command");

    let running = hooks::capture(
        &path,
        "agy",
        Some("PostToolUse"),
        json!({
            "conversationId": "conv-1",
            "lastUserInput": "Run cargo test",
            "workspacePaths": ["D:\\project\\info_tv"],
            "toolCall": {
                "name": "run_command"
            }
        }),
    )
    .expect("capture")
    .expect("event");
    assert_eq!(running.state, TaskState::Running);
    assert_eq!(running.sequence, 3);
    assert_eq!(running.detail, "Working");

    let completed = hooks::capture(
        &path,
        "agy",
        Some("Stop"),
        json!({
            "conversationId": "conv-1",
            "lastUserInput": "Run cargo test",
            "workspacePaths": ["D:\\project\\info_tv"],
            "fullyIdle": true,
            "terminationReason": "NO_TOOL_CALL"
        }),
    )
    .expect("capture")
    .expect("event");
    assert_eq!(completed.state, TaskState::Completed);
    assert_eq!(completed.sequence, 4);
    assert_eq!(completed.detail, "Turn ended");
}
