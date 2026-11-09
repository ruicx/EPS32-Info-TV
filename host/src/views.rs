//! Convert business records into the existing firmware's structured display types.

use crate::{
    protocol::pb,
    storage::StoredState,
    tasks::{TaskIcon, TaskRecord, TaskState},
};

/// Build one source-independent card without layout coordinates.
pub fn card(record: &TaskRecord, now_ms: i64) -> pb::Card {
    let event = &record.event;
    let tone = match event.state {
        TaskState::Running | TaskState::Interrupted | TaskState::Closed => 1,
        TaskState::WaitingInput => 2,
        TaskState::Completed => 3,
        TaskState::Failed => 4,
    };
    let icon = match event.icon {
        TaskIcon::Task => 0,
        TaskIcon::Code => 1,
        TaskIcon::Test => 2,
        TaskIcon::Build => 3,
        TaskIcon::Review => 4,
        TaskIcon::Deploy => 5,
    };
    pb::Card {
        card_id: record.card_id.clone(),
        revision: record.revision,
        view: Some(pb::View {
            title: if event.conversation_title.is_empty() {
                event.title.clone()
            } else {
                event.conversation_title.clone()
            },
            source: event.source.clone(),
            context: event.context.clone(),
            icon,
            content: Some(pb::view::Content::Status(pb::StatusView {
                text: event.state.as_str().replace('_', " "),
                tone,
                detail: if event.detail.is_empty() && event.conversation_id.is_some() {
                    event.title.clone()
                } else {
                    event.detail.clone()
                },
                progress_percent: event.progress_percent,
                recent_question_seconds: record.question_expires_at_ms.map_or(0, |expiry| {
                    (expiry.saturating_sub(now_ms).clamp(0, 30_000) as u32).div_ceil(1000)
                }),
            })),
        }),
    }
}

/// Build a transient notification for one admitted state transition.
pub fn notification(record: &TaskRecord, now_ms: i64) -> pb::Notification {
    pb::Notification {
        notification_id: record.event.event_id.clone(),
        priority: if record.event.state.terminal() { 1 } else { 2 },
        display_duration_ms: None,
        valid_for_ms: 30_000,
        view: card(record, now_ms).view,
        card_id: record.card_id.clone(),
    }
}

/// Include only weather whose original expiry has not passed.
pub fn weather(state: &StoredState, now_ms: i64) -> pb::Weather {
    let Some(timed) = &state.weather else {
        return pb::Weather::default();
    };
    let remaining = timed.remaining(now_ms);
    if remaining == 0 {
        return pb::Weather::default();
    }
    let value = &timed.value;
    let condition = match value.condition.as_str() {
        "clear" => 1,
        "cloudy" => 2,
        "rain" => 3,
        "snow" => 4,
        "storm" => 5,
        "fog" => 6,
        _ => 0,
    };
    pb::Weather {
        location: value.location.clone(),
        temperature_c: Some(value.temperature_c),
        condition,
        valid_for_ms: remaining,
        daily_low_c: value.daily_low_c,
        daily_high_c: value.daily_high_c,
    }
}

/// Rebuild a retained alert marker, enabling a notification only for a new live transition.
pub fn alert(state: &StoredState, now_ms: i64, notify: bool) -> pb::WeatherAlert {
    let Some(timed) = &state.alert else {
        return pb::WeatherAlert::default();
    };
    let remaining = timed.remaining(now_ms);
    if remaining == 0 {
        return pb::WeatherAlert::default();
    }
    let value = &timed.value;
    pb::WeatherAlert {
        alert_id: value.alert_id.clone(),
        title: value.title.clone(),
        source: value.source.clone(),
        location: value.location.clone(),
        severity: value.severity_value(),
        detail: value.detail.clone(),
        valid_for_ms: remaining,
        notify,
    }
}

/// Rebuild the authoritative overview for connection or card-removal synchronization.
pub fn snapshot(state: &StoredState, now_ms: i64) -> pb::Snapshot {
    pb::Snapshot {
        cards: state
            .tasks
            .tasks
            .iter()
            .map(|record| card(record, now_ms))
            .collect(),
        weather: Some(weather(state, now_ms)),
    }
}
