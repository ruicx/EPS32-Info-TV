//! Device state-machine regressions independent of timing or physical hardware.

use info_tv::{
    device::DeviceSession,
    protocol::{
        self,
        pb::{self, envelope::Body},
    },
    storage::{StoredState, Timed},
    tasks::{TaskEvent, TaskStore},
    weather::WeatherRequest,
};
use serde_json::json;
use uuid::Uuid;

fn feedback(device: &DeviceSession, body: Body) -> pb::Envelope {
    protocol::envelope(&device.session_id, body)
}

fn ack(device: &DeviceSession, id: &str, stage: i32, brightness: Option<u32>) -> pb::Envelope {
    feedback(
        device,
        Body::Acknowledgment(pb::Acknowledgment {
            in_reply_to: id.into(),
            stage,
            brightness_percent: brightness,
            ..Default::default()
        }),
    )
}

/// Complete the actual handshake with correlated acknowledgments.
fn online(stored: &StoredState) -> DeviceSession {
    let mut device = DeviceSession::default();
    let hello = device.connected(1, 0);
    assert!(hello.session_id.is_empty());
    let reply = feedback(
        &device,
        Body::Hello(pb::Hello {
            boot_id: 123,
            max_cards: 8,
            task_icons: true,
            brightness_control: true,
            weather: true,
            weather_details: true,
        }),
    );
    device.feedback(reply, stored, 1).expect("hello");
    let snapshot = device
        .poll(stored, 1)
        .expect("snapshot")
        .pop()
        .expect("command");
    assert!(matches!(snapshot.body, Some(Body::Snapshot(_))));
    device
        .feedback(ack(&device, &snapshot.message_id, 1, None), stored, 2)
        .expect("snapshot accepted");
    let brightness = device
        .poll(stored, 2)
        .expect("brightness")
        .pop()
        .expect("command");
    device
        .feedback(
            ack(
                &device,
                &brightness.message_id,
                3,
                Some(stored.brightness_percent),
            ),
            stored,
            3,
        )
        .expect("applied");
    assert!(device.online());
    // Finish initial alert-marker synchronization.
    let alert = device
        .poll(stored, 3)
        .expect("alert")
        .pop()
        .expect("command");
    device
        .feedback(ack(&device, &alert.message_id, 1, None), stored, 4)
        .expect("alert accepted");
    device
}

#[test]
fn brightness_requires_correlated_applied_feedback() {
    let mut stored = StoredState::default();
    let mut device = online(&stored);
    stored.brightness_percent = 0;
    device.brightness_changed();
    let command = device
        .poll(&stored, 10)
        .expect("poll")
        .pop()
        .expect("command");
    device
        .feedback(ack(&device, &command.message_id, 1, None), &stored, 11)
        .expect("accepted ignored");
    assert_eq!(device.applied_brightness, Some(100));
    device
        .feedback(ack(&device, &command.message_id, 3, Some(30)), &stored, 12)
        .expect("mismatch ignored");
    device
        .feedback(ack(&device, "wrong-command", 3, Some(0)), &stored, 13)
        .expect("wrong id ignored");
    assert_eq!(device.applied_brightness, Some(100));
    device
        .feedback(ack(&device, &command.message_id, 3, Some(0)), &stored, 14)
        .expect("applied off");
    assert_eq!(device.applied_brightness, Some(0));
    device.disconnected("unplugged");
    assert_eq!(device.applied_brightness, None);
    assert_eq!(
        device.settings_status(&stored)["delivery"],
        json!({"state":"pending"})
    );
}

#[test]
fn weather_retry_keeps_identity_and_shortens_validity() {
    let mut stored = StoredState::default();
    let mut device = online(&stored);
    stored.weather = Some(Timed {
        value: WeatherRequest {
            location: "Harbin".into(),
            temperature_c: 0,
            condition: "snow".into(),
            valid_for_seconds: 2,
            daily_low_c: None,
            daily_high_c: None,
        },
        expires_at_ms: 1510,
    });
    device.weather_changed();
    let first = device
        .poll(&stored, 10)
        .expect("weather")
        .pop()
        .expect("command");
    let retry = device
        .poll(&stored, 1010)
        .expect("retry")
        .pop()
        .expect("command");
    assert_eq!(first.message_id, retry.message_id);
    assert!(matches!(
        first.body,
        Some(Body::Weather(pb::Weather {
            valid_for_ms: 1500,
            ..
        }))
    ));
    assert!(matches!(
        retry.body,
        Some(Body::Weather(pb::Weather {
            valid_for_ms: 500,
            ..
        }))
    ));
    let retry = device
        .poll(&stored, 2010)
        .expect("retry")
        .pop()
        .expect("command");
    assert_eq!(first.message_id, retry.message_id);
    assert!(matches!(
        retry.body,
        Some(Body::Weather(pb::Weather {
            temperature_c: None,
            ..
        }))
    ));
}

#[test]
fn bounded_notifications_are_cleared_on_disconnect() {
    let stored = StoredState::default();
    let mut device = online(&stored);
    let mut store = TaskStore::default();
    for index in 0..8 {
        let event: TaskEvent = serde_json::from_value(
            json!({"event_id":Uuid::new_v4().simple().to_string(),"source":"test",
            "task_id":index.to_string(),"sequence":1,"state":"completed","title":"Build"}),
        )
        .expect("event");
        let update = store.prepare(&event, 10).expect("admit");
        store.commit(&update);
        device.publish(&update.record, true, 10);
    }
    assert!(!device.can_notify(20));
    assert!(device.can_notify(30_011));
    device.disconnected("device unplugged");
    assert!(device.can_notify(30_012));
    assert!(device.deadline().is_none());
}

#[test]
fn card_presentation_requires_acceptance_and_matching_revision() {
    let mut stored = StoredState::default();
    let mut device = online(&stored);
    let event: TaskEvent = serde_json::from_value(
        json!({"event_id":Uuid::new_v4().simple().to_string(),"source":"test",
        "task_id":"build","sequence":1,"state":"running","title":"Build"}),
    )
    .expect("event");
    let update = stored.tasks.prepare(&event, 10).expect("admit");
    stored.tasks.commit(&update);
    device.publish(&update.record, false, 10);
    let command = device
        .poll(&stored, 10)
        .expect("poll")
        .pop()
        .expect("command");
    let presented = |revision| {
        feedback(
            &device,
            Body::Acknowledgment(pb::Acknowledgment {
                in_reply_to: command.message_id.clone(),
                stage: 2,
                card_id: update.record.card_id.clone(),
                revision,
                ..Default::default()
            }),
        )
    };
    let early = presented(1);
    let wrong = presented(2);
    let right = presented(1);
    device.feedback(early, &stored, 11).expect("early");
    assert_eq!(
        device.card_status(&update.record.card_id)["presented"],
        false
    );
    device
        .feedback(ack(&device, &command.message_id, 1, None), &stored, 12)
        .expect("accepted");
    device.feedback(wrong, &stored, 13).expect("wrong revision");
    assert_eq!(
        device.card_status(&update.record.card_id)["presented"],
        false
    );
    device.feedback(right, &stored, 14).expect("presented");
    assert_eq!(
        device.card_status(&update.record.card_id)["presented"],
        true
    );
}

#[test]
fn unsupported_firmware_and_dead_connections_are_rejected() {
    let stored = StoredState::default();
    let mut device = DeviceSession::default();
    device.connected(1, 0);
    let hello = feedback(
        &device,
        Body::Hello(pb::Hello {
            boot_id: 123,
            ..Default::default()
        }),
    );
    assert!(device.feedback(hello, &stored, 1).is_err());
    assert!(device.poll(&stored, 3000).is_err());
    let mut device = online(&stored);
    assert!(device.poll(&stored, 3004).is_err());
}

#[test]
fn current_settings_feedback_survives_recent_history_eviction() {
    let mut stored = StoredState::default();
    let mut device = online(&stored);
    let event: TaskEvent = serde_json::from_value(
        json!({"event_id":Uuid::new_v4().simple().to_string(),"source":"test",
        "task_id":"build","sequence":1,"state":"running","title":"Build"}),
    )
    .expect("event");
    let mut record = stored.tasks.prepare(&event, 10).expect("admit").record;
    for revision in 1..=300 {
        record.revision = revision;
        device.publish(&record, false, 10 + revision as i64);
        let command = device
            .poll(&stored, 10 + revision as i64)
            .expect("poll")
            .pop()
            .expect("command");
        device
            .feedback(
                ack(&device, &command.message_id, 1, None),
                &stored,
                11 + revision as i64,
            )
            .expect("accepted");
    }
    assert_eq!(device.settings_status(&stored)["delivery"]["applied"], true);
    assert!(
        device.status(&stored, 400)["deliveries"]
            .as_array()
            .expect("deliveries")
            .len()
            <= 256
    );
    stored.brightness_percent = 0;
    device.brightness_changed();
    assert_eq!(
        device.settings_status(&stored)["delivery"],
        json!({"state":"pending"})
    );
}
