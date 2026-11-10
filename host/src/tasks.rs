//! Ordered, bounded task state independent of HTTP and the device protocol.

use std::collections::VecDeque;

use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub const MAX_TASKS: usize = 8;
pub const EVENT_CACHE_CAPACITY: usize = 256;

/// A rejected admission, carrying the public HTTP status and explanation.
#[derive(Debug, Clone)]
pub struct AdmissionError {
    pub status: u16,
    pub detail: String,
}

impl AdmissionError {
    /// Construct an explicit failure without coupling domain logic to HTTP.
    pub fn new(status: u16, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }
}

impl std::fmt::Display for AdmissionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.detail)
    }
}

impl std::error::Error for AdmissionError {}

/// Source-independent execution state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskState {
    Running,
    WaitingInput,
    Completed,
    Failed,
    Interrupted,
    Closed,
}

impl TaskState {
    /// Return whether this state starts automatic card retirement.
    pub fn terminal(self) -> bool {
        matches!(self, Self::Completed | Self::Interrupted)
    }

    /// Return the stable API spelling.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Running => "running",
            Self::WaitingInput => "waiting_input",
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::Interrupted => "interrupted",
            Self::Closed => "closed",
        }
    }
}

/// Built-in task-purpose icon, independent of execution state.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskIcon {
    #[default]
    Task,
    Code,
    Test,
    Build,
    Review,
    Deploy,
}

/// One immutable producer update; UUIDs are normalized before admission.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskEvent {
    pub event_id: String,
    pub source: String,
    pub task_id: String,
    pub sequence: i64,
    pub state: TaskState,
    pub title: String,
    #[serde(default)]
    pub detail: String,
    #[serde(default)]
    pub progress_percent: Option<u32>,
    #[serde(default)]
    pub conversation_id: Option<String>,
    #[serde(default)]
    pub conversation_title: String,
    #[serde(default)]
    pub context: String,
    #[serde(default)]
    pub run_sequence: Option<i64>,
    #[serde(default)]
    pub icon: TaskIcon,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub question_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub producer_process: Option<crate::process::ProcessIdentity>,
}

/// Check text at its encoded wire boundary, preserving permitted whitespace.
pub fn validate_text(value: &str, limit: usize, required: bool) -> Result<(), AdmissionError> {
    if value.contains('\0') || value.len() > limit || (required && value.is_empty()) {
        return Err(AdmissionError::new(
            422,
            format!("Text must fit {limit} UTF-8 bytes and contain no NUL"),
        ));
    }
    Ok(())
}

/// Match Python's printable-label policy, including Unicode format/separator characters.
pub fn is_printable(character: char) -> bool {
    use unicode_general_category::{GeneralCategory, get_general_category};
    character == ' '
        || !matches!(
            get_general_category(character),
            GeneralCategory::Control
                | GeneralCategory::Format
                | GeneralCategory::Surrogate
                | GeneralCategory::PrivateUse
                | GeneralCategory::Unassigned
                | GeneralCategory::LineSeparator
                | GeneralCategory::ParagraphSeparator
                | GeneralCategory::SpaceSeparator
        )
}

/// Normalize a public UUID to the hex representation used on the device.
pub fn normalize_uuid(value: &str) -> Result<String, AdmissionError> {
    Uuid::parse_str(value)
        .map(|id| id.simple().to_string())
        .map_err(|_| AdmissionError::new(422, "Invalid UUID"))
}

impl TaskEvent {
    /// Validate cross-field constraints and canonicalize event identity.
    pub fn validate(&mut self) -> Result<(), AdmissionError> {
        self.event_id = normalize_uuid(&self.event_id)?;
        for (text, required) in [
            (&self.source, true),
            (&self.task_id, true),
            (&self.title, true),
            (&self.conversation_title, false),
            (&self.context, false),
        ] {
            validate_text(text, 64, required)?;
        }
        validate_text(&self.detail, 160, false)?;
        if let Some(id) = &self.question_id {
            validate_text(id, 64, true)?;
        }
        if let Some(id) = &self.conversation_id {
            validate_text(id, 64, true)?;
        }
        if let Some(process) = self.producer_process
            && (process.pid == 0
                || process.started_at == 0
                || self.source != "agy"
                || self.conversation_id.is_none())
        {
            return Err(AdmissionError::new(
                422,
                "Invalid producer process identity",
            ));
        }
        if self.sequence <= 0
            || self.run_sequence.is_some_and(|n| n <= 0)
            || self.progress_percent.is_some_and(|n| n > 100)
            || self.conversation_id.is_some() != self.run_sequence.is_some()
            || (!self.conversation_title.is_empty() && self.conversation_id.is_none())
        {
            return Err(AdmissionError::new(
                422,
                "Invalid sequence, progress, or conversation fields",
            ));
        }
        Ok(())
    }
}

/// Current card content and durable ordering/transition metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskRecord {
    pub event: TaskEvent,
    /// Last confirmed owner of this execution, separate from immutable event data.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub producer_process: Option<crate::process::ProcessIdentity>,
    pub card_id: String,
    pub revision: u64,
    pub completion_notified: bool,
    pub completed_at_ms: Option<i64>,
    #[serde(default)]
    pub question_expires_at_ms: Option<i64>,
}

/// Result of evaluating an event before persistence or publication.
#[derive(Debug, Clone)]
pub struct TaskUpdate {
    pub outcome: &'static str,
    pub record: TaskRecord,
    pub notify: bool,
}

/// Ordered current cards plus bounded replay protection; owned by the coordinator.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TaskStore {
    pub tasks: Vec<TaskRecord>,
    pub events: VecDeque<TaskEvent>,
    pub retired: VecDeque<TaskRecord>,
}

/// Compare the producer-scoped conversation or standalone task identity.
fn same_key(a: &TaskEvent, b: &TaskEvent) -> bool {
    a.source == b.source
        && match (&a.conversation_id, &b.conversation_id) {
            (Some(a), Some(b)) => a == b,
            (None, None) => a.task_id == b.task_id,
            _ => false,
        }
}

impl TaskStore {
    /// Evaluate ordering and notification intent without mutating accepted state.
    pub fn prepare(&self, event: &TaskEvent, now_ms: i64) -> Result<TaskUpdate, AdmissionError> {
        let active = self.tasks.iter().find(|r| same_key(&r.event, event));
        let previous = active.or_else(|| self.retired.iter().find(|r| same_key(&r.event, event)));
        let unchanged = |outcome| {
            previous
                .cloned()
                .map(|record| TaskUpdate {
                    outcome,
                    record,
                    notify: false,
                })
                .ok_or_else(|| {
                    AdmissionError::new(
                        410,
                        "Event belongs to a retired task outside the retention window",
                    )
                })
        };
        if let Some(seen) = self.events.iter().find(|e| e.event_id == event.event_id) {
            if seen != event {
                return Err(AdmissionError::new(
                    409,
                    "event_id was reused with different content",
                ));
            }
            return unchanged("duplicate");
        }
        for known in self
            .tasks
            .iter()
            .chain(self.retired.iter())
            .map(|r| &r.event)
            .chain(self.events.iter())
        {
            if known.source == event.source
                && known.task_id == event.task_id
                && (known.conversation_id != event.conversation_id
                    || known.run_sequence != event.run_sequence)
            {
                return Err(AdmissionError::new(
                    409,
                    "task_id cannot move between conversations or execution ordinals",
                ));
            }
        }
        let same_run = previous.is_some_and(|r| r.event.task_id == event.task_id);
        if let Some(old) = previous {
            if event.conversation_id.is_some() {
                if event.run_sequence < old.event.run_sequence {
                    return unchanged("stale");
                }
                if (event.run_sequence == old.event.run_sequence) != same_run {
                    return Err(AdmissionError::new(
                        409,
                        "Each conversation execution ordinal must identify one task_id",
                    ));
                }
            }
            if same_run && event.sequence <= old.event.sequence {
                if event.sequence == old.event.sequence && event != &old.event {
                    return Err(AdmissionError::new(
                        409,
                        "sequence was reused with different content",
                    ));
                }
                return unchanged("stale");
            }
            if active.is_none() && same_run {
                return unchanged("closed");
            }
        }
        if active.is_none() && self.tasks.len() >= MAX_TASKS && event.state != TaskState::Closed {
            return Err(AdmissionError::new(503, "Task capacity reached"));
        }
        let completed = previous.is_some_and(|r| same_run && r.completion_notified);
        let terminal = event.state.terminal();
        let notify = (terminal && !completed)
            || (matches!(event.state, TaskState::WaitingInput | TaskState::Failed)
                && (!same_run || previous.is_none_or(|r| r.event.state != event.state)));
        let record = TaskRecord {
            event: event.clone(),
            producer_process: event.producer_process.or_else(|| {
                previous
                    .filter(|_| same_run)
                    .and_then(|r| r.producer_process)
            }),
            card_id: active
                .map(|r| r.card_id.clone())
                .unwrap_or_else(|| Uuid::new_v4().simple().to_string()),
            revision: active.map_or(1, |r| r.revision + 1),
            completion_notified: completed || terminal,
            completed_at_ms: if terminal {
                Some(
                    previous
                        .filter(|_| same_run)
                        .and_then(|r| r.completed_at_ms)
                        .unwrap_or(now_ms),
                )
            } else {
                None
            },
            question_expires_at_ms: if matches!(
                event.state,
                TaskState::Running | TaskState::WaitingInput
            ) {
                if event.question_id.is_some() {
                    Some(now_ms.saturating_add(30_000))
                } else {
                    previous
                        .filter(|_| same_run)
                        .and_then(|r| r.question_expires_at_ms)
                }
            } else {
                None
            },
        };
        Ok(TaskUpdate {
            outcome: "accepted",
            record,
            notify,
        })
    }

    /// Apply an evaluated update to a candidate state before its durable commit.
    pub fn commit(&mut self, update: &TaskUpdate) {
        let event = &update.record.event;
        if let Some(record) = self.tasks.iter_mut().find(|r| same_key(&r.event, event)) {
            *record = update.record.clone();
        } else {
            self.tasks.push(update.record.clone());
        }
        self.retired.retain(|r| !same_key(&r.event, event));
        self.events.push_back(event.clone());
        if self.events.len() > EVENT_CACHE_CAPACITY {
            self.events.pop_front();
        }
        if event.state == TaskState::Closed {
            self.close(&update.record.card_id);
        }
    }

    /// Retire one card and retain bounded late-event protection.
    pub fn close(&mut self, card_id: &str) -> bool {
        let Some(index) = self.tasks.iter().position(|r| r.card_id == card_id) else {
            return false;
        };
        let record = self.tasks.remove(index);
        self.retired
            .retain(|old| !same_key(&old.event, &record.event));
        self.retired.push_back(record);
        if self.retired.len() > EVENT_CACHE_CAPACITY {
            self.retired.pop_front();
        }
        true
    }

    /// Retire expired completed cards; downtime counts toward their original age.
    pub fn expire(&mut self, now_ms: i64, retention_seconds: u64) -> Vec<String> {
        let retention_ms = retention_seconds.saturating_mul(1000).min(i64::MAX as u64) as i64;
        let expired: Vec<_> = self
            .tasks
            .iter()
            .filter(|r| {
                r.completed_at_ms
                    .is_some_and(|time| now_ms.saturating_sub(time) >= retention_ms)
            })
            .map(|r| r.card_id.clone())
            .collect();
        for card_id in &expired {
            self.close(card_id);
        }
        expired
    }
}
