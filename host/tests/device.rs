//! Device state-machine regressions independent of timing or physical hardware.

use info_tv::{
    config::LockAction,
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
            power_control: false,
            unlock_polling: false,
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
fn session_lock_sends_zero_and_restores_the_latest_target() {
    let mut stored = StoredState::default();
    let mut device = online(&stored);
    device.set_lock_action(LockAction::ScreenOff);
    device.set_session_locked(true);
    let off = device.poll(&stored, 10).expect("poll").pop().expect("off");
    assert!(matches!(
        off.body,
        Some(Body::DeviceSettings(pb::DeviceSettings {
            brightness_percent: Some(0)
        }))
    ));
    device
        .feedback(ack(&device, &off.message_id, 3, Some(0)), &stored, 11)
        .expect("off applied");
    assert_eq!(device.applied_brightness, Some(0));
    device.set_session_locked(true);
    assert!(device.poll(&stored, 12).expect("unchanged lock").is_empty());
    stored.brightness_percent = 40;
    device.brightness_changed();
    let still_off = device
        .poll(&stored, 13)
        .expect("poll")
        .pop()
        .expect("still off");
    assert!(matches!(
        still_off.body,
        Some(Body::DeviceSettings(pb::DeviceSettings {
            brightness_percent: Some(0)
        }))
    ));
    device.set_session_locked(false);
    let restore = device
        .poll(&stored, 14)
        .expect("poll")
        .pop()
        .expect("restore");
    assert!(matches!(
        restore.body,
        Some(Body::DeviceSettings(pb::DeviceSettings {
            brightness_percent: Some(40)
        }))
    ));
    device
        .feedback(ack(&device, &still_off.message_id, 3, Some(0)), &stored, 15)
        .expect("stale off ignored");
    device
        .feedback(ack(&device, &restore.message_id, 3, Some(40)), &stored, 16)
        .expect("restore applied");
    assert_eq!(device.applied_brightness, Some(40));
}

#[test]
fn locked_reconnect_completes_handshake_at_zero_brightness() {
    let stored = StoredState::default();
    let mut device = online(&stored);
    device.set_lock_action(LockAction::ScreenOff);
    device.set_session_locked(true);
    device.disconnected("reconnect while locked");
    device.connected(2, 10);
    let reply = feedback(
        &device,
        Body::Hello(pb::Hello {
            boot_id: 124,
            max_cards: 8,
            task_icons: true,
            brightness_control: true,
            weather: true,
            weather_details: true,
            power_control: false,
            unlock_polling: false,
        }),
    );
    device.feedback(reply, &stored, 11).expect("hello");
    let snapshot = device
        .poll(&stored, 11)
        .expect("snapshot")
        .pop()
        .expect("command");
    device
        .feedback(ack(&device, &snapshot.message_id, 1, None), &stored, 12)
        .expect("snapshot accepted");
    let off = device
        .poll(&stored, 12)
        .expect("brightness")
        .pop()
        .expect("command");
    assert!(matches!(
        off.body,
        Some(Body::DeviceSettings(pb::DeviceSettings {
            brightness_percent: Some(0)
        }))
    ));
    device
        .feedback(ack(&device, &off.message_id, 3, Some(0)), &stored, 13)
        .expect("off applied");
    assert!(device.online());
    assert_eq!(device.settings_status(&stored)["brightness_percent"], 100);
}

/// Complete content and brightness synchronization up to the new power-policy command.
fn configure_power(
    device: &mut DeviceSession,
    stored: &StoredState,
    now: i64,
    polling: bool,
) -> pb::Envelope {
    device.connected(2, now);
    let hello = feedback(
        device,
        Body::Hello(pb::Hello {
            boot_id: 125,
            max_cards: 8,
            task_icons: true,
            brightness_control: true,
            weather: true,
            weather_details: true,
            power_control: true,
            unlock_polling: polling,
        }),
    );
    device.feedback(hello, stored, now + 1).expect("hello");
    let snapshot = device
        .poll(stored, now + 1)
        .expect("snapshot")
        .pop()
        .expect("command");
    device
        .feedback(ack(device, &snapshot.message_id, 1, None), stored, now + 2)
        .expect("snapshot applied");
    if polling {
        return device
            .poll(stored, now + 2)
            .expect("power before brightness")
            .pop()
            .expect("command");
    }
    let brightness = device
        .poll(stored, now + 2)
        .expect("brightness")
        .pop()
        .expect("command");
    assert!(matches!(
        brightness.body,
        Some(Body::DeviceSettings(pb::DeviceSettings {
            brightness_percent: Some(100)
        }))
    ));
    device
        .feedback(
            ack(device, &brightness.message_id, 3, Some(100)),
            stored,
            now + 3,
        )
        .expect("brightness applied");
    assert!(!device.online());
    device
        .poll(stored, now + 3)
        .expect("power")
        .pop()
        .expect("command")
}

#[test]
fn deep_sleep_keeps_preview_brightness_and_requires_correlated_power_proof() {
    let stored = StoredState::default();
    let mut device = DeviceSession::default();
    device.set_lock_action(LockAction::DeepSleep);
    device.set_session_locked(true);
    let power = configure_power(&mut device, &stored, 10, false);
    assert!(matches!(
        power.body,
        Some(Body::PowerSettings(pb::PowerSettings {
            lock_action: 2,
            session_locked: true,
            unlock_poll_seconds: 0
        }))
    ));
    device
        .feedback(ack(&device, &power.message_id, 3, Some(100)), &stored, 14)
        .expect("brightness-only proof ignored");
    assert!(!device.online());
    let mut reply = pb::Acknowledgment {
        in_reply_to: power.message_id.clone(),
        stage: 3,
        lock_action: Some(2),
        session_locked: Some(false),
        ..Default::default()
    };
    device
        .feedback(
            feedback(&device, Body::Acknowledgment(reply.clone())),
            &stored,
            15,
        )
        .expect("wrong lock ignored");
    assert!(!device.online());
    reply.session_locked = Some(true);
    device
        .feedback(feedback(&device, Body::Acknowledgment(reply)), &stored, 16)
        .expect("policy applied");
    assert!(device.online());
    assert_eq!(
        device.settings_status(&stored)["effective_brightness_percent"],
        100
    );
    // Touch wake causes a fresh USB handshake; repeat the same policy, leaving preview timing to firmware.
    device.disconnected("sleeping");
    let repeated = configure_power(&mut device, &stored, 20, false);
    assert!(matches!(
        repeated.body,
        Some(Body::PowerSettings(pb::PowerSettings {
            lock_action: 2,
            session_locked: true,
            unlock_poll_seconds: 0
        }))
    ));
    device.set_session_locked(false);
    let brightness = device
        .poll(&stored, 25)
        .expect("brightness")
        .pop()
        .expect("command");
    device
        .feedback(
            ack(&device, &brightness.message_id, 3, Some(100)),
            &stored,
            26,
        )
        .expect("brightness");
    let unlock = device
        .poll(&stored, 26)
        .expect("unlock")
        .pop()
        .expect("command");
    assert!(matches!(
        unlock.body,
        Some(Body::PowerSettings(pb::PowerSettings {
            lock_action: 2,
            session_locked: false,
            unlock_poll_seconds: 0
        }))
    ));
}

#[test]
fn deep_sleep_rejects_firmware_without_power_control() {
    let stored = StoredState::default();
    let mut device = DeviceSession::default();
    device.set_lock_action(LockAction::DeepSleep);
    device.connected(1, 0);
    let hello = feedback(
        &device,
        Body::Hello(pb::Hello {
            boot_id: 1,
            max_cards: 8,
            task_icons: true,
            brightness_control: true,
            weather: true,
            weather_details: true,
            power_control: false,
            unlock_polling: false,
        }),
    );
    assert!(device.feedback(hello, &stored, 1).is_err());
}

#[test]
fn automatic_unlock_configures_power_before_brightness_and_checks_interval_proof() {
    let stored = StoredState::default();
    let mut device = DeviceSession::default();
    device.set_lock_action(LockAction::DeepSleep);
    device.set_unlock_poll_seconds(5);
    let power = configure_power(&mut device, &stored, 10, true);
    assert!(matches!(
        power.body,
        Some(Body::PowerSettings(pb::PowerSettings {
            lock_action: 2,
            session_locked: false,
            unlock_poll_seconds: 5
        }))
    ));
    assert_eq!(device.applied_brightness, None);
    let mut reply = pb::Acknowledgment {
        in_reply_to: power.message_id,
        stage: 3,
        lock_action: Some(2),
        session_locked: Some(false),
        ..Default::default()
    };
    for interval in [None, Some(0), Some(15)] {
        reply.unlock_poll_seconds = interval;
        device
            .feedback(
                feedback(&device, Body::Acknowledgment(reply.clone())),
                &stored,
                13,
            )
            .expect("ignore interval mismatch");
        assert_eq!(
            device.settings_status(&stored)["power_delivery"]["applied"],
            false
        );
    }
    reply.unlock_poll_seconds = Some(5);
    device
        .feedback(feedback(&device, Body::Acknowledgment(reply)), &stored, 14)
        .expect("power applied");
    assert!(!device.online());
    let brightness = device
        .poll(&stored, 14)
        .expect("brightness")
        .pop()
        .expect("command");
    assert!(matches!(brightness.body, Some(Body::DeviceSettings(_))));
    device
        .feedback(
            ack(&device, &brightness.message_id, 3, Some(100)),
            &stored,
            15,
        )
        .expect("brightness applied");
    assert!(device.online());
    assert_eq!(device.settings_status(&stored)["unlock_poll_seconds"], 5);
    device.disconnected("timer cycle");
    let next = configure_power(&mut device, &stored, 20, true);
    assert!(matches!(
        next.body,
        Some(Body::PowerSettings(pb::PowerSettings {
            unlock_poll_seconds: 5,
            ..
        }))
    ));
}

#[test]
fn polling_requires_its_own_firmware_capability() {
    let stored = StoredState::default();
    let mut device = DeviceSession::default();
    device.set_lock_action(LockAction::DeepSleep);
    device.set_unlock_poll_seconds(5);
    device.connected(1, 0);
    let hello = feedback(
        &device,
        Body::Hello(pb::Hello {
            boot_id: 1,
            max_cards: 8,
            task_icons: true,
            brightness_control: true,
            weather: true,
            weather_details: true,
            power_control: true,
            unlock_polling: false,
        }),
    );
    assert!(device.feedback(hello, &stored, 1).is_err());
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
