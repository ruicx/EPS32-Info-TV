//! Coordinator-owned connection state, bounded delivery, and actual device feedback.

use std::collections::{BTreeMap, VecDeque};

use anyhow::{Result, bail};
use serde::Serialize;
use serde_json::{Value, json};
use uuid::Uuid;

use crate::{
    config::LockAction,
    protocol::{
        self,
        pb::{self, envelope::Body},
    },
    storage::StoredState,
    tasks::TaskRecord,
    views,
};

/// Reception, display, and hardware feedback for one operation.
#[derive(Debug, Clone, Serialize)]
pub struct Delivery {
    pub message_id: String,
    pub accepted: bool,
    pub presented: bool,
    pub applied: bool,
    pub error: Option<String>,
}

impl Delivery {
    fn new(id: &str) -> Self {
        Self {
            message_id: id.into(),
            accepted: false,
            presented: false,
            applied: false,
            error: None,
        }
    }
}

/// One operation awaiting Accepted or Applied, with an unchanged retry identity.
struct Pending {
    envelope: pb::Envelope,
    sent_at_ms: i64,
    attempts: u8,
    expires_at_ms: Option<i64>,
}

/// Device state is mutated only by the runtime coordinator.
pub struct DeviceSession {
    pub session_id: String,
    pub state: &'static str,
    pub generation: u64,
    pub last_error: Option<String>,
    pub applied_brightness: Option<u32>,
    dirty: VecDeque<pb::Card>,
    snapshot_dirty: bool,
    notifications: VecDeque<(pb::Notification, i64)>,
    deliveries: VecDeque<(String, Delivery)>,
    card_delivery: BTreeMap<String, (u64, String)>,
    brightness_delivery: Option<String>,
    power_delivery: Option<String>,
    weather_delivery: Option<String>,
    alert_delivery: Option<String>,
    pub alert_notification: &'static str,
    brightness_dirty: bool,
    session_locked: bool,
    lock_action: LockAction,
    power_supported: bool,
    power_dirty: bool,
    power_configured: bool,
    weather_dirty: bool,
    alert_dirty: bool,
    alert_notify: bool,
    pending: Option<Pending>,
    last_received_ms: i64,
    last_ping_ms: i64,
    handshake_deadline_ms: i64,
    card_sent_since_notice: bool,
}

impl Default for DeviceSession {
    fn default() -> Self {
        Self {
            session_id: Uuid::new_v4().simple().to_string(),
            state: "offline",
            generation: 0,
            last_error: None,
            applied_brightness: None,
            dirty: VecDeque::new(),
            snapshot_dirty: false,
            notifications: VecDeque::new(),
            deliveries: VecDeque::new(),
            card_delivery: BTreeMap::new(),
            brightness_delivery: None,
            power_delivery: None,
            weather_delivery: None,
            alert_delivery: None,
            alert_notification: "suppressed",
            brightness_dirty: true,
            session_locked: false,
            lock_action: LockAction::None,
            power_supported: false,
            power_dirty: false,
            power_configured: false,
            weather_dirty: false,
            alert_dirty: true,
            alert_notify: false,
            pending: None,
            last_received_ms: 0,
            last_ping_ms: 0,
            handshake_deadline_ms: 0,
            card_sent_since_notice: false,
        }
    }
}

impl DeviceSession {
    /// Whether snapshot reception and brightness application are complete.
    pub fn online(&self) -> bool {
        self.state == "online"
    }

    /// Reserve notification capacity before committing a business transition.
    pub fn can_notify(&mut self, now_ms: i64) -> bool {
        self.notifications.retain(|(_, expiry)| *expiry > now_ms);
        self.notifications.len() < 8
    }

    /// Coalesce unsent content for the same card without accumulating revisions.
    pub fn publish(&mut self, record: &TaskRecord, notify: bool, now_ms: i64) {
        let value = views::card(record, now_ms);
        if let Some(old) = self.dirty.iter_mut().find(|c| c.card_id == value.card_id) {
            *old = value;
        } else {
            self.dirty.push_back(value);
        }
        if notify && self.online() {
            self.notifications
                .push_back((views::notification(record, now_ms), now_ms + 30_000));
        }
    }

    /// Remove pending work for a retired card and schedule an authoritative snapshot.
    pub fn remove(&mut self, card_id: &str) {
        self.dirty.retain(|card| card.card_id != card_id);
        self.notifications
            .retain(|(note, _)| note.card_id != card_id);
        self.card_delivery.remove(card_id);
        self.snapshot_dirty = true;
    }

    /// Mark the durable target as requiring new Applied feedback.
    pub fn brightness_changed(&mut self) {
        self.brightness_dirty = true;
        self.brightness_delivery = None;
    }

    /// Select the startup-only lock action before the connection handshake.
    pub fn set_lock_action(&mut self, action: LockAction) {
        self.lock_action = action;
    }

    /// Apply a new lock state without changing durable user brightness.
    pub fn set_session_locked(&mut self, locked: bool) {
        if self.session_locked == locked {
            return;
        }
        self.session_locked = locked;
        // A retry of an obsolete brightness must not undo the new lock state.
        if self.pending.as_ref().is_some_and(|pending| {
            matches!(
                pending.envelope.body,
                Some(Body::DeviceSettings(_) | Body::PowerSettings(_))
            )
        }) {
            self.pending = None;
        }
        self.brightness_changed();
        self.power_dirty = self.power_supported;
        self.power_configured = false;
        self.power_delivery = None;
    }

    /// Resolve the temporary lock override against the persisted user setting.
    fn effective_brightness(&self, stored: &StoredState) -> u32 {
        if self.session_locked && self.lock_action == LockAction::ScreenOff {
            0
        } else {
            stored.brightness_percent
        }
    }

    /// Mark fresh or cleared weather for downstream publication.
    pub fn weather_changed(&mut self) {
        self.weather_dirty = true;
        self.weather_delivery = None;
    }

    /// Retain alert publication intent separately from its durable marker.
    pub fn alert_changed(&mut self, notify: bool, has_alert: bool) {
        let notify =
            has_alert && (notify || (self.alert_dirty && self.alert_notify && self.online()));
        self.alert_dirty = true;
        self.alert_notify = notify;
        self.alert_delivery = None;
        self.alert_notification = if notify {
            "queued"
        } else if has_alert && !self.online() {
            "skipped_offline"
        } else {
            "suppressed"
        };
    }

    /// Begin discovery on a newly opened transport generation.
    pub fn connected(&mut self, generation: u64, now_ms: i64) -> pb::Envelope {
        self.generation = generation;
        self.state = "handshaking";
        self.handshake_deadline_ms = now_ms + 3000;
        self.last_received_ms = now_ms;
        self.last_ping_ms = now_ms;
        protocol::envelope("", Body::Hello(pb::Hello::default()))
    }

    /// Forget connection-specific proof while retaining business state externally.
    pub fn disconnected(&mut self, reason: impl Into<String>) {
        let reason = reason.into();
        if self.last_error.as_deref() != Some(&reason) {
            tracing::warn!(%reason, "Device offline");
        }
        self.last_error = Some(reason);
        self.state = "offline";
        if let Some(pending) = self.pending.take() {
            self.mark_error(
                &pending.envelope.message_id,
                "Connection lost; outcome may be unknown",
            );
        }
        self.notifications.clear();
        self.applied_brightness = None;
        self.brightness_dirty = true;
        self.brightness_delivery = None;
        self.power_delivery = None;
        self.power_supported = false;
        self.power_dirty = false;
        self.power_configured = false;
        self.weather_delivery = None;
        self.alert_delivery = None;
        self.card_delivery.clear();
        self.alert_dirty = true;
        self.alert_notify = false;
        self.alert_notification = "suppressed";
    }

    /// Process valid current-connection feedback, preserving milestone distinctions.
    pub fn feedback(
        &mut self,
        envelope: pb::Envelope,
        stored: &StoredState,
        now_ms: i64,
    ) -> Result<()> {
        if self.state == "handshaking" {
            if let Some(Body::Hello(hello)) = envelope.body {
                anyhow::ensure!(
                    hello.boot_id != 0
                        && hello.max_cards >= 8
                        && hello.task_icons
                        && hello.brightness_control
                        && hello.weather
                        && hello.weather_details,
                    "Device firmware lacks required capabilities"
                );
                anyhow::ensure!(
                    self.lock_action != LockAction::DeepSleep || hello.power_control,
                    "Device firmware lacks ULP deep-sleep power control"
                );
                self.power_supported = hello.power_control;
                self.power_dirty = hello.power_control;
                self.state = "synchronizing";
                self.snapshot_dirty = true;
                self.dirty.clear();
                self.last_received_ms = now_ms;
            }
            return Ok(());
        }
        if envelope.session_id != self.session_id {
            return Ok(());
        }
        self.last_received_ms = now_ms;
        match envelope.body {
            Some(Body::Hello(_)) => bail!("Device restarted"),
            Some(Body::Error(error)) => {
                self.mark_error(&error.in_reply_to, &error.detail);
                if self
                    .pending
                    .as_ref()
                    .is_some_and(|p| p.envelope.message_id == error.in_reply_to)
                {
                    let required = self.state != "online"
                        || self
                            .pending
                            .as_ref()
                            .is_some_and(|p| matches!(p.envelope.body, Some(Body::Snapshot(_))));
                    self.pending = None;
                    anyhow::ensure!(!required, "Device rejected recovery synchronization");
                }
            }
            Some(Body::Acknowledgment(ack)) => self.acknowledge(ack, stored),
            _ => {}
        }
        Ok(())
    }

    fn acknowledge(&mut self, ack: pb::Acknowledgment, stored: &StoredState) {
        let pending = self
            .pending
            .as_ref()
            .filter(|p| p.envelope.message_id == ack.in_reply_to);
        if ack.stage == 3 {
            if let Some(Body::PowerSettings(settings)) =
                pending.and_then(|p| p.envelope.body.as_ref())
            {
                if ack.lock_action != Some(settings.lock_action)
                    || ack.session_locked != Some(settings.session_locked)
                {
                    return;
                }
                self.power_configured = !self.power_dirty;
                if let Some((_, delivery)) = self
                    .deliveries
                    .iter_mut()
                    .find(|(key, _)| key == &ack.in_reply_to)
                {
                    delivery.accepted = true;
                    delivery.applied = true;
                }
                self.pending = None;
                self.finish_configuration(stored);
                return;
            }
            let expected = pending.and_then(|p| match &p.envelope.body {
                Some(Body::DeviceSettings(s)) => s.brightness_percent,
                _ => None,
            });
            if expected.is_none() || expected != ack.brightness_percent {
                return;
            }
            self.applied_brightness = expected;
            for (key, value) in &mut self.deliveries {
                if key == &ack.in_reply_to {
                    value.accepted = true;
                    value.applied = true;
                }
            }
            self.pending = None;
            self.finish_configuration(stored);
            return;
        }
        if pending.is_some_and(|p| {
            matches!(
                p.envelope.body,
                Some(Body::DeviceSettings(_) | Body::PowerSettings(_))
            )
        }) {
            return;
        }
        if ack.stage == 1 {
            for (key, value) in &mut self.deliveries {
                if key == &ack.in_reply_to || key.starts_with(&format!("{}:", ack.in_reply_to)) {
                    value.accepted = true;
                }
            }
            if let Some(pending) = pending {
                if self.state == "synchronizing"
                    && matches!(pending.envelope.body, Some(Body::Snapshot(_)))
                {
                    self.state = "configuring";
                }
                self.pending = None;
            }
        } else if ack.stage == 2 {
            if !ack.card_id.is_empty()
                && self.card_delivery.get(&ack.card_id)
                    != Some(&(ack.revision, ack.in_reply_to.clone()))
            {
                return;
            }
            let key = if ack.card_id.is_empty() {
                ack.in_reply_to
            } else {
                format!("{}:{}", ack.in_reply_to, ack.card_id)
            };
            if let Some((_, delivery)) = self.deliveries.iter_mut().find(|(id, _)| id == &key)
                && delivery.accepted
            {
                delivery.presented = true;
            }
        }
    }

    /// Require current brightness and power-policy proof before reporting online.
    fn finish_configuration(&mut self, stored: &StoredState) {
        if self.state == "configuring"
            && !self.brightness_dirty
            && self.applied_brightness == Some(self.effective_brightness(stored))
            && (!self.power_supported || self.power_configured)
        {
            self.state = "online";
            self.last_error = None;
        }
    }

    /// Select at most one business command, plus a liveness ping when due.
    pub fn poll(&mut self, stored: &StoredState, now_ms: i64) -> Result<Vec<pb::Envelope>> {
        if self.state == "offline" {
            return Ok(Vec::new());
        }
        if self.state == "handshaking" {
            anyhow::ensure!(now_ms < self.handshake_deadline_ms, "Device Hello timeout");
            return Ok(Vec::new());
        }
        anyhow::ensure!(
            now_ms - self.last_received_ms < 3000,
            "Device heartbeat timeout"
        );
        let mut output = Vec::new();
        if now_ms - self.last_ping_ms >= 1000 {
            output.push(protocol::envelope(
                &self.session_id,
                Body::Ping(pb::Ping {}),
            ));
            self.last_ping_ms = now_ms;
        }
        if self.pending.is_some() {
            if let Some(retry) = self.retry(now_ms)? {
                output.push(retry);
            }
            return Ok(output);
        }
        let selected = if self.snapshot_dirty && matches!(self.state, "synchronizing" | "online") {
            self.snapshot_dirty = false;
            self.weather_dirty = false;
            self.dirty.clear();
            Some((
                Body::Snapshot(views::snapshot(stored, now_ms)),
                stored.weather.as_ref().map(|w| w.expires_at_ms),
            ))
        } else if matches!(self.state, "configuring" | "online") && self.brightness_dirty {
            self.brightness_dirty = false;
            Some((
                Body::DeviceSettings(pb::DeviceSettings {
                    brightness_percent: Some(self.effective_brightness(stored)),
                }),
                None,
            ))
        } else if matches!(self.state, "configuring" | "online") && self.power_dirty {
            self.power_dirty = false;
            Some((
                Body::PowerSettings(pb::PowerSettings {
                    lock_action: self.lock_action.protocol_value(),
                    session_locked: self.session_locked,
                }),
                None,
            ))
        } else if self.online() {
            self.next_online(stored, now_ms)
        } else {
            None
        };
        if let Some((body, expiry)) = selected {
            output.push(self.start_command(body, expiry, now_ms));
        }
        Ok(output)
    }

    fn next_online(&mut self, stored: &StoredState, now_ms: i64) -> Option<(Body, Option<i64>)> {
        self.notifications.retain(|(_, expiry)| *expiry > now_ms);
        if self.alert_dirty {
            self.alert_dirty = false;
            return Some((
                Body::WeatherAlert(views::alert(stored, now_ms, self.alert_notify)),
                stored.alert.as_ref().map(|a| a.expires_at_ms),
            ));
        }
        if self.weather_dirty {
            self.weather_dirty = false;
            return Some((
                Body::Weather(views::weather(stored, now_ms)),
                stored.weather.as_ref().map(|w| w.expires_at_ms),
            ));
        }
        if !self.notifications.is_empty() && (self.dirty.is_empty() || self.card_sent_since_notice)
        {
            let index = self
                .notifications
                .iter()
                .position(|(n, _)| n.priority == 2)
                .unwrap_or(0);
            if let Some((mut note, expiry)) = self.notifications.remove(index) {
                note.valid_for_ms = (expiry - now_ms).max(1) as u32;
                self.card_sent_since_notice = false;
                return Some((Body::Notification(note), Some(expiry)));
            }
        }
        if let Some(mut card) = self.dirty.pop_front() {
            if let Some(record) = stored
                .tasks
                .tasks
                .iter()
                .find(|r| r.card_id == card.card_id)
            {
                card = views::card(record, now_ms);
            }
            self.card_sent_since_notice = true;
            return Some((Body::CardUpsert(pb::CardUpsert { card: Some(card) }), None));
        }
        None
    }

    fn start_command(&mut self, body: Body, expiry: Option<i64>, now_ms: i64) -> pb::Envelope {
        let envelope = protocol::envelope(&self.session_id, body);
        let id = envelope.message_id.clone();
        self.deliveries.push_back((id.clone(), Delivery::new(&id)));
        let cards = match &envelope.body {
            Some(Body::Snapshot(s)) => s.cards.clone(),
            Some(Body::CardUpsert(c)) => c.card.iter().cloned().collect(),
            _ => Vec::new(),
        };
        match &envelope.body {
            Some(Body::DeviceSettings(_)) => self.brightness_delivery = Some(id.clone()),
            Some(Body::PowerSettings(_)) => self.power_delivery = Some(id.clone()),
            Some(Body::Snapshot(_) | Body::Weather(_)) => self.weather_delivery = Some(id.clone()),
            Some(Body::WeatherAlert(_)) => self.alert_delivery = Some(id.clone()),
            _ => {}
        }
        for card in cards {
            self.card_delivery
                .insert(card.card_id.clone(), (card.revision, id.clone()));
            self.deliveries
                .push_back((format!("{id}:{}", card.card_id), Delivery::new(&id)));
        }
        while self.deliveries.len() > 256 {
            let index = self
                .deliveries
                .iter()
                .position(|(key, _)| {
                    Some(key) != self.brightness_delivery.as_ref()
                        && Some(key) != self.power_delivery.as_ref()
                        && Some(key) != self.weather_delivery.as_ref()
                        && Some(key) != self.alert_delivery.as_ref()
                })
                .unwrap_or(0);
            self.deliveries.remove(index);
        }
        self.pending = Some(Pending {
            envelope: envelope.clone(),
            sent_at_ms: now_ms,
            attempts: 1,
            expires_at_ms: expiry,
        });
        envelope
    }

    fn retry(&mut self, now_ms: i64) -> Result<Option<pb::Envelope>> {
        let Some(pending) = &mut self.pending else {
            return Ok(None);
        };
        if now_ms - pending.sent_at_ms < 1000 {
            return Ok(None);
        }
        if let Some(expiry) = pending.expires_at_ms {
            let remaining = (expiry - now_ms).max(0) as u32;
            match &mut pending.envelope.body {
                Some(Body::Notification(note)) => {
                    if remaining == 0 {
                        let id = pending.envelope.message_id.clone();
                        self.mark_error(&id, "Notification expired");
                        self.pending = None;
                        return Ok(None);
                    }
                    note.valid_for_ms = remaining;
                }
                Some(Body::Weather(w)) => {
                    if remaining == 0 {
                        *w = pb::Weather::default();
                    } else {
                        w.valid_for_ms = remaining;
                    }
                }
                Some(Body::Snapshot(s)) => {
                    if let Some(w) = &mut s.weather {
                        if remaining == 0 {
                            *w = pb::Weather::default();
                        } else if w.temperature_c.is_some() {
                            w.valid_for_ms = remaining;
                        }
                    }
                }
                Some(Body::WeatherAlert(a)) => {
                    if remaining == 0 {
                        *a = pb::WeatherAlert::default();
                    } else if !a.alert_id.is_empty() {
                        a.valid_for_ms = remaining;
                    }
                }
                _ => {}
            }
        }
        anyhow::ensure!(pending.attempts < 3, "Device acknowledgment timeout");
        pending.attempts += 1;
        pending.sent_at_ms = now_ms;
        Ok(Some(pending.envelope.clone()))
    }

    fn mark_error(&mut self, id: &str, reason: &str) {
        for (key, value) in &mut self.deliveries {
            if key == id || key.starts_with(&format!("{id}:")) {
                value.error = Some(reason.into());
            }
        }
    }

    /// Next protocol deadline, avoiding fixed short polling when idle.
    pub fn deadline(&self) -> Option<i64> {
        match self.state {
            "offline" => None,
            "handshaking" => Some(self.handshake_deadline_ms),
            _ => Some(
                (self.last_received_ms + 3000)
                    .min(self.last_ping_ms + 1000)
                    .min(
                        self.pending
                            .as_ref()
                            .map_or(i64::MAX, |p| p.sent_at_ms + 1000),
                    ),
            ),
        }
    }

    fn delivery(&self, identity: &Option<String>) -> Option<&Delivery> {
        identity
            .as_ref()
            .and_then(|id| self.deliveries.iter().find(|(key, _)| key == id))
            .map(|(_, d)| d)
    }

    /// Most recent correlated feedback for a card revision in the current connection.
    pub fn card_status(&self, id: &str) -> Value {
        let Some((revision, message_id)) = self.card_delivery.get(id) else {
            return json!({"state":"pending"});
        };
        let key = format!("{message_id}:{id}");
        let delivery = self
            .deliveries
            .iter()
            .find(|(id, _)| id == &key)
            .map(|(_, d)| d);
        json!({"revision":revision,"message_id":message_id,"accepted":delivery.is_some_and(|d| d.accepted),
            "presented":delivery.is_some_and(|d| d.presented),"error":delivery.and_then(|d| d.error.as_ref())})
    }

    /// Target brightness and current-connection application proof.
    pub fn settings_status(&self, stored: &StoredState) -> Value {
        let delivery = self.delivery(&self.brightness_delivery).map_or(
            json!({"state":"pending"}),
            |d| json!({"message_id":d.message_id,"applied":d.applied,"error":d.error}),
        );
        json!({"brightness_percent":stored.brightness_percent,
            "effective_brightness_percent":self.effective_brightness(stored),
            "screen_off_for_lock":self.session_locked && self.lock_action == LockAction::ScreenOff,
            "lock_action":self.lock_action,"session_locked":self.session_locked,
            "power_delivery":self.delivery(&self.power_delivery),
            "applied_brightness_percent":self.applied_brightness,"delivery":delivery})
    }

    /// Weather content/freshness, without claiming independent LCD presentation.
    pub fn weather_status(&self, stored: &StoredState, now_ms: i64) -> Value {
        let value = stored.weather.as_ref();
        let remaining = value.map_or(0, |w| w.remaining(now_ms));
        let delivery = self.delivery(&self.weather_delivery).map_or(
            json!({"state":"pending"}),
            |d| json!({"message_id":d.message_id,"accepted":d.accepted,"error":d.error}),
        );
        json!({"state":if value.is_none() {"unavailable"} else if remaining>0 {"fresh"} else {"stale"},
            "location":value.map(|w| &w.value.location),"temperature_c":value.map(|w| w.value.temperature_c),
            "condition":value.map(|w| &w.value.condition),"daily_low_c":value.and_then(|w| w.value.daily_low_c),
            "daily_high_c":value.and_then(|w| w.value.daily_high_c),"valid_for_ms":remaining,"delivery":delivery})
    }

    /// Retained alert validity and independently correlated transient presentation.
    pub fn alert_status(&self, stored: &StoredState, now_ms: i64) -> Value {
        let value = stored.alert.as_ref();
        let remaining = value.map_or(0, |a| a.remaining(now_ms));
        let delivery = self.delivery(&self.alert_delivery).map_or(json!({"state":"pending"}),
            |d| json!({"message_id":d.message_id,"accepted":d.accepted,"notification_presented":d.presented,"error":d.error}));
        json!({"state":if value.is_none() {"unavailable"} else if remaining>0 {"active"} else {"expired"},
            "alert_id":value.map(|a| &a.value.alert_id),"sequence":value.map_or(0, |a| a.value.sequence),
            "title":value.map(|a| &a.value.title),"source":value.map(|a| &a.value.source),"location":value.map(|a| &a.value.location),
            "detail":value.map_or("", |a| a.value.detail.as_str()),"severity":value.map(|a| &a.value.severity),
            "valid_for_ms":remaining,"notification":self.alert_notification,"delivery":delivery})
    }

    /// Diagnostics keep admission, connection, and display milestones distinct.
    pub fn status(&self, stored: &StoredState, now_ms: i64) -> Value {
        let deliveries: Vec<_> = self
            .deliveries
            .iter()
            .map(|(key, d)| {
                json!({"message_id":key,
            "accepted":d.accepted,"presented":d.presented,"applied":d.applied,"error":d.error})
            })
            .collect();
        json!({"state":self.state,"session_id":self.session_id,"last_error":self.last_error,
            "settings":self.settings_status(stored),"weather":self.weather_status(stored, now_ms),
            "weather_alert":self.alert_status(stored, now_ms),"deliveries":deliveries})
    }
}
