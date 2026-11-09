//! Native hook adapters with Python-compatible SQLite ledgers and immutable retries.

use std::{
    io::Read,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

use anyhow::{Context, Result, bail};
use clap::Args;
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::{
    config,
    tasks::{TaskEvent, TaskIcon, TaskState},
    weather::validate_label,
};

/// Callback command options for the hook subcommand.
#[derive(Debug, Args)]
pub struct HookArgs {
    #[arg(value_parser = ["codex", "agy", "zcode"])]
    pub source: String,
    #[arg(value_parser = ["PreInvocation", "PreToolUse", "PostToolUse", "Stop"])]
    pub event: Option<String>,
    #[arg(long, default_value = "http://127.0.0.1:8765")]
    pub url: String,
    #[arg(long)]
    pub state_file: Option<PathBuf>,
    #[arg(long, default_value = "0.5")]
    pub timeout: f64,
    #[arg(long)]
    pub flush: bool,
}

/// Collapse controls/whitespace and truncate at a UTF-8 character boundary.
pub fn display_text(value: &str, limit: usize) -> String {
    let clean: String = value
        .chars()
        .map(|c| {
            if crate::tasks::is_printable(c) {
                c
            } else {
                ' '
            }
        })
        .collect();
    let clean = clean.split_whitespace().collect::<Vec<_>>().join(" ");
    let mut end = clean.len().min(limit);
    while !clean.is_char_boundary(end) {
        end -= 1;
    }
    clean[..end].trim().into()
}

fn labels(prompt: &str, cwd: &str, fallback: &str) -> (String, String) {
    let title = display_text(prompt, 64);
    let title = if title.is_empty() {
        fallback.into()
    } else {
        title
    };
    let context = display_text(
        cwd.trim_end_matches(['/', '\\'])
            .rsplit(['/', '\\'])
            .next()
            .unwrap_or(""),
        64,
    );
    (title, context)
}

/// Native callback fields shared by Codex and ZCode, with public ZCode aliases.
#[derive(Deserialize)]
struct TurnHook {
    #[serde(alias = "hookEventName")]
    hook_event_name: String,
    #[serde(alias = "sessionId")]
    session_id: String,
    #[serde(default, alias = "turnId")]
    turn_id: Option<String>,
    #[serde(default)]
    prompt: String,
    #[serde(default)]
    cwd: String,
    #[serde(default, alias = "toolName")]
    tool_name: String,
    #[serde(default, alias = "responseText")]
    last_assistant_message: Option<String>,
}

#[derive(Deserialize)]
struct AgyToolCall {
    #[serde(default)]
    name: String,
}

/// The native agy callback uses invocation counters instead of a turn identity.
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct AgyHook {
    conversation_id: String,
    last_user_input: String,
    #[serde(default)]
    workspace_paths: Vec<String>,
    #[serde(default)]
    invocation_num: Option<i64>,
    #[serde(default)]
    initial_num_steps: Option<i64>,
    #[serde(default)]
    fully_idle: Option<bool>,
    #[serde(default)]
    termination_reason: Option<String>,
    #[serde(default)]
    tool_call: Option<AgyToolCall>,
}

/// Persisted per-execution ordering data, matching existing Python columns.
struct Run {
    ordinal: i64,
    sequence: i64,
    title: String,
    conversation_title: String,
    context: String,
    state: String,
}

fn turn_state(source: &str, event: &str) -> Option<TaskState> {
    match event {
        "UserPromptSubmit" | "PreToolUse" | "PostToolUse" => Some(TaskState::Running),
        "PostToolUseFailure" if source == "zcode" => Some(TaskState::Running),
        "PermissionRequest" => Some(TaskState::WaitingInput),
        "Stop" => Some(TaskState::Completed),
        "Interrupt" if source == "codex" => Some(TaskState::Interrupted),
        _ => None,
    }
}

fn turn_detail(hook: &TurnHook) -> String {
    match hook.hook_event_name.as_str() {
        "PermissionRequest" => display_text(
            &format!(
                "Approval requested: {}",
                if hook.tool_name.is_empty() {
                    "tool"
                } else {
                    &hook.tool_name
                }
            ),
            160,
        ),
        "Stop" => display_text(
            hook.last_assistant_message
                .as_deref()
                .filter(|s| !s.is_empty())
                .unwrap_or("Turn ended"),
            160,
        ),
        "Interrupt" => "Turn interrupted".into(),
        "PostToolUseFailure" => "Tool failed; agent may recover".into(),
        _ => "Working".into(),
    }
}

/// Open a source ledger while retaining the schema used by the Python hooks.
fn open(path: &Path, source: &str) -> Result<Connection> {
    if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    let connection = Connection::open(path)?;
    connection.busy_timeout(Duration::from_secs(1))?;
    connection.execute_batch("CREATE TABLE IF NOT EXISTS outbox (
        position INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL UNIQUE,payload TEXT NOT NULL);")?;
    match source {
        "codex" | "zcode" => {
            let table = if source == "codex" { "runs" } else { "zcode_runs" };
            connection.execute_batch(&format!("CREATE TABLE IF NOT EXISTS {table} (
                session_id TEXT NOT NULL,turn_id TEXT NOT NULL,run_sequence INTEGER NOT NULL,sequence INTEGER NOT NULL,
                title TEXT NOT NULL,conversation_title TEXT NOT NULL,context TEXT NOT NULL,state TEXT NOT NULL,
                PRIMARY KEY(session_id,turn_id));"))?;
        }
        "agy" => connection.execute_batch("CREATE TABLE IF NOT EXISTS agy_conversations (
            conversation_id TEXT PRIMARY KEY,start_step INTEGER NOT NULL,run_sequence INTEGER NOT NULL,sequence INTEGER NOT NULL,
            title TEXT NOT NULL,conversation_title TEXT NOT NULL,context TEXT NOT NULL,state TEXT NOT NULL,prompt_hash TEXT NOT NULL);")?,
        _ => bail!("Unknown hook source"),
    }
    Ok(connection)
}

fn enqueue(connection: &Connection, event: &mut TaskEvent) -> Result<()> {
    event.validate()?;
    let mut payload = serde_json::to_value(&event)?;
    payload
        .as_object_mut()
        .context("Task payload must be an object")?
        .retain(|_, value| !value.is_null());
    connection.execute(
        "INSERT INTO outbox(event_id,payload) VALUES(?1,?2)",
        params![event.event_id, serde_json::to_string(&payload)?],
    )?;
    Ok(())
}

/// Capture an event atomically; unsupported or duplicate transitions enqueue nothing.
pub fn capture(
    path: &Path,
    source: &str,
    event_name: Option<&str>,
    payload: Value,
) -> Result<Option<TaskEvent>> {
    let mut connection = open(path, source)?;
    let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let submission = if source == "agy" {
        capture_agy(
            &transaction,
            event_name.context("agy requires PreInvocation, PreToolUse, PostToolUse, or Stop")?,
            payload,
        )?
    } else {
        anyhow::ensure!(
            event_name.is_none(),
            "This source reads its event name from stdin"
        );
        capture_turn(&transaction, source, payload)?
    };
    transaction.commit()?;
    Ok(submission)
}

fn capture_turn(
    connection: &Connection,
    source: &str,
    payload: Value,
) -> Result<Option<TaskEvent>> {
    let hook: TurnHook = serde_json::from_value(payload)?;
    validate_label(&hook.session_id, 64, true)?;
    if let Some(id) = &hook.turn_id {
        validate_label(id, 64, true)?;
    }
    let Some(state) = turn_state(source, &hook.hook_event_name) else {
        return Ok(None);
    };
    let turn = hook
        .turn_id
        .as_deref()
        .context("A supported callback requires turn_id")?;
    let table = if source == "codex" {
        "runs"
    } else {
        "zcode_runs"
    };
    let mut run = connection
        .query_row(
            &format!(
                "SELECT run_sequence,sequence,title,conversation_title,context,state FROM {table}
        WHERE session_id=?1 AND turn_id=?2"
            ),
            params![hook.session_id, turn],
            |row| {
                Ok(Run {
                    ordinal: row.get(0)?,
                    sequence: row.get(1)?,
                    title: row.get(2)?,
                    conversation_title: row.get(3)?,
                    context: row.get(4)?,
                    state: row.get(5)?,
                })
            },
        )
        .optional()?;
    if run.is_none() {
        if hook.hook_event_name != "UserPromptSubmit" {
            if state.terminal() {
                connection.execute(
                    &format!("INSERT INTO {table} VALUES(?1,?2,0,0,'','','',?3)"),
                    params![hook.session_id, turn, state.as_str()],
                )?;
            }
            return Ok(None);
        }
        let ordinal: i64 = connection.query_row(
            &format!("SELECT COALESCE(MAX(run_sequence),0)+1 FROM {table} WHERE session_id=?1"),
            [&hook.session_id],
            |r| r.get(0),
        )?;
        let (title, context) = labels(
            &hook.prompt,
            &hook.cwd,
            if source == "codex" {
                "Codex task"
            } else {
                "ZCode task"
            },
        );
        let conversation_title = connection
            .query_row(
                &format!(
                    "SELECT conversation_title FROM {table}
            WHERE session_id=?1 AND run_sequence>0 ORDER BY run_sequence LIMIT 1"
                ),
                [&hook.session_id],
                |r| r.get(0),
            )
            .optional()?
            .unwrap_or_else(|| title.clone());
        connection.execute(
            &format!("INSERT INTO {table} VALUES(?1,?2,?3,0,?4,?5,?6,'')"),
            params![
                hook.session_id,
                turn,
                ordinal,
                title,
                conversation_title,
                context
            ],
        )?;
        run = Some(Run {
            ordinal,
            sequence: 0,
            title,
            conversation_title,
            context,
            state: String::new(),
        });
    } else if hook.hook_event_name == "UserPromptSubmit"
        || run.as_ref().is_some_and(|r| {
            r.state == state.as_str()
                || r.state == "completed"
                || (source == "codex" && r.state == "interrupted")
        })
    {
        return Ok(None);
    }
    let run = run.context("Execution ledger was not initialized")?;
    let task_id = if source == "codex" {
        turn.into()
    } else {
        Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!("info-tv:zcode:{}:{turn}", hook.session_id).as_bytes(),
        )
        .simple()
        .to_string()
    };
    let mut event = TaskEvent {
        event_id: Uuid::new_v4().simple().to_string(),
        source: source.into(),
        task_id,
        sequence: run
            .sequence
            .checked_add(1)
            .context("Hook sequence exhausted")?,
        state,
        title: run.title,
        detail: turn_detail(&hook),
        progress_percent: None,
        conversation_id: Some(hook.session_id.clone()),
        conversation_title: run.conversation_title,
        context: run.context,
        run_sequence: Some(run.ordinal),
        icon: TaskIcon::Code,
    };
    connection.execute(
        &format!("UPDATE {table} SET sequence=?1,state=?2 WHERE session_id=?3 AND turn_id=?4"),
        params![event.sequence, state.as_str(), hook.session_id, turn],
    )?;
    enqueue(connection, &mut event)?;
    Ok(Some(event))
}

fn capture_agy(
    connection: &Connection,
    event_name: &str,
    payload: Value,
) -> Result<Option<TaskEvent>> {
    let hook: AgyHook = serde_json::from_value(payload)?;
    validate_label(&hook.conversation_id, 64, true)?;
    anyhow::ensure!(
        hook.invocation_num.is_none_or(|n| n >= 0) && hook.initial_num_steps.is_none_or(|n| n > 0),
        "Invalid invocation counters"
    );
    let reason = hook.termination_reason.as_deref().unwrap_or("");
    let (state, detail) = match event_name {
        "PreInvocation" => {
            let invocation = hook.invocation_num.context("Missing invocationNum")?;
            let step = hook.initial_num_steps.context("Missing initialNumSteps")?;
            anyhow::ensure!(invocation >= 0 && step > 0, "Invalid invocation counters");
            if invocation != 0 {
                return Ok(None);
            }
            (TaskState::Running, "Working".to_string())
        }
        "PreToolUse" => {
            let tool_name = hook
                .tool_call
                .as_ref()
                .map(|t| t.name.as_str())
                .unwrap_or("");
            if matches!(
                tool_name,
                "read_file"
                    | "view_file"
                    | "search_web"
                    | "manage_task"
                    | "manage_subagents"
                    | "schedule"
                    | "send_message"
            ) {
                return Ok(None);
            }
            (
                TaskState::WaitingInput,
                display_text(
                    &format!(
                        "Approval requested: {}",
                        if tool_name.is_empty() {
                            "tool"
                        } else {
                            tool_name
                        }
                    ),
                    160,
                ),
            )
        }
        "PostToolUse" => (TaskState::Running, "Working".to_string()),
        "Stop" => {
            anyhow::ensure!(
                hook.fully_idle.is_some() && hook.termination_reason.is_some(),
                "Stop requires fullyIdle and terminationReason"
            );
            if hook.fully_idle != Some(true) {
                return Ok(None);
            }
            match reason {
                "NO_TOOL_CALL" => (TaskState::Completed, "Turn ended".to_string()),
                "ERROR" => (TaskState::Failed, "Execution error".to_string()),
                "MAX_INVOCATIONS" => (TaskState::Failed, "Invocation limit reached".to_string()),
                "MAX_FORCED_INVOCATIONS" => {
                    (TaskState::Failed, "Continuation limit reached".to_string())
                }
                "MAX_TOKEN_BUDGET_EXCEEDED" => {
                    (TaskState::Failed, "Token budget exceeded".to_string())
                }
                "USER_CANCELED" => (TaskState::Interrupted, "Turn interrupted".to_string()),
                _ => return Ok(None),
            }
        }
        _ => bail!("Invalid agy event"),
    };
    let hash = format!("{:x}", Sha256::digest(hook.last_user_input.as_bytes()));
    let old: Option<(i64, Run, String)> = connection.query_row("SELECT start_step,run_sequence,sequence,title,conversation_title,context,state,prompt_hash
        FROM agy_conversations WHERE conversation_id=?1", [&hook.conversation_id], |r| Ok((r.get(0)?, Run {
            ordinal: r.get(1)?, sequence: r.get(2)?, title: r.get(3)?, conversation_title: r.get(4)?, context: r.get(5)?, state: r.get(6)?,
        }, r.get(7)?))).optional()?;
    let (step, run) = if event_name == "PreInvocation" {
        let step = hook.initial_num_steps.context("Missing start step")?;
        if old.as_ref().is_some_and(|(start, _, _)| step <= *start) {
            return Ok(None);
        }
        let (title, context) = labels(
            &hook.last_user_input,
            hook.workspace_paths.first().map_or("", String::as_str),
            "AGY task",
        );
        let conversation_title = old
            .as_ref()
            .map_or_else(|| title.clone(), |(_, r, _)| r.conversation_title.clone());
        let ordinal = old.as_ref().map_or(1, |(_, r, _)| r.ordinal + 1);
        connection.execute(
            "INSERT OR REPLACE INTO agy_conversations VALUES(?1,?2,?3,0,?4,?5,?6,'',?7)",
            params![
                hook.conversation_id,
                step,
                ordinal,
                title,
                conversation_title,
                context,
                hash
            ],
        )?;
        (
            step,
            Run {
                ordinal,
                sequence: 0,
                title,
                conversation_title,
                context,
                state: String::new(),
            },
        )
    } else {
        let Some((step, run, previous_hash)) = old else {
            return Ok(None);
        };
        if (run.state != "running" && run.state != "waiting_input")
            || run.state == state.as_str()
            || previous_hash != hash
        {
            return Ok(None);
        }
        (step, run)
    };
    let task_id = Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("info-tv:agy:{}:{step}", hook.conversation_id).as_bytes(),
    )
    .simple()
    .to_string();
    let mut event = TaskEvent {
        event_id: Uuid::new_v4().simple().to_string(),
        source: "agy".into(),
        task_id,
        sequence: run
            .sequence
            .checked_add(1)
            .context("Hook sequence exhausted")?,
        state,
        title: run.title,
        detail,
        progress_percent: None,
        conversation_id: Some(hook.conversation_id.clone()),
        conversation_title: run.conversation_title,
        context: run.context,
        run_sequence: Some(run.ordinal),
        icon: TaskIcon::Code,
    };
    connection.execute(
        "UPDATE agy_conversations SET sequence=?1,state=?2 WHERE conversation_id=?3",
        params![event.sequence, state.as_str(), hook.conversation_id],
    )?;
    enqueue(connection, &mut event)?;
    Ok(Some(event))
}

/// Retry immutable events without holding a database lock during HTTP.
pub fn flush(path: &Path, source: &str, url: &str, timeout: f64) -> Result<()> {
    anyhow::ensure!(
        timeout.is_finite() && timeout > 0.0 && Duration::try_from_secs_f64(timeout).is_ok(),
        "--timeout must be finite and positive"
    );
    let connection = open(path, source)?;
    let client = reqwest::blocking::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs_f64(timeout))
        .build()?;
    let deadline = Instant::now() + Duration::from_secs(1);
    while Instant::now() < deadline {
        let pending: Option<(String, String)> = connection
            .query_row(
                "SELECT event_id,payload FROM outbox ORDER BY position LIMIT 1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        let Some((event_id, payload)) = pending else {
            break;
        };
        let response = client
            .post(format!("{}/v1/task-events", url.trim_end_matches('/')))
            .header("Content-Type", "application/json")
            .body(payload)
            .send()?
            .error_for_status()?;
        anyhow::ensure!(
            response.status().as_u16() == 202,
            "Host did not acknowledge task admission"
        );
        let result: Value = response.json()?;
        anyhow::ensure!(
            matches!(
                result["outcome"].as_str(),
                Some("accepted" | "duplicate" | "stale" | "closed")
            ),
            "Invalid admission acknowledgment"
        );
        connection.execute("DELETE FROM outbox WHERE event_id=?1", [&event_id])?;
    }
    Ok(())
}

/// Handle one callback without blocking the source agent on runtime failures.
pub fn run(args: HookArgs) {
    let attempt = || -> Result<()> {
        anyhow::ensure!(
            args.timeout.is_finite() && args.timeout > 0.0,
            "--timeout must be finite and positive"
        );
        let path = args.state_file.clone().unwrap_or_else(|| {
            config::state_directory().join(format!("{}-hooks.sqlite3", args.source))
        });
        if !args.flush {
            let mut bytes = Vec::new();
            std::io::stdin().take(1_048_577).read_to_end(&mut bytes)?;
            anyhow::ensure!(bytes.len() <= 1_048_576, "Hook input exceeds 1 MiB");
            capture(
                &path,
                &args.source,
                args.event.as_deref(),
                serde_json::from_slice(&bytes)?,
            )?;
        }
        flush(&path, &args.source, &args.url, args.timeout)
    };
    if let Err(error) = attempt() {
        eprintln!("info-tv hook: {error:#}");
    }
    if args.event.as_deref() == Some("PreToolUse") {
        println!("{{\"decision\":\"allow\"}}");
    } else {
        println!("{{}}");
    }
}
