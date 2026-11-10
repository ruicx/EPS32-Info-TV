//! Single-owner coordinator with commit-before-publication and supervised I/O.

use std::{cell::Cell, path::Path, time::Duration};

use anyhow::Result;
use serde_json::{Value, json};
use tokio::sync::{mpsc, oneshot, watch};

use crate::{
    config::{LockAction, Settings},
    device::DeviceSession,
    storage::{Database, Storage, StoredState, Timed},
    tasks::{AdmissionError, TaskEvent, TaskStore, normalize_uuid},
    transport,
    weather::{self, AlertRequest, WeatherRequest},
};

/// Supported ingress operations, independent of a particular HTTP framework.
pub enum Operation {
    Submit(TaskEvent),
    Tasks,
    Close(String),
    Status,
    Settings,
    Brightness(u32),
    SessionLocked(bool),
    Weather,
    SetWeather(Option<WeatherRequest>),
    Alert,
    SetAlert(Option<AlertRequest>),
    Updater,
    WeatherResult(Result<(WeatherRequest, i64), String>),
}

struct Request {
    operation: Operation,
    response: oneshot::Sender<Result<Value, AdmissionError>>,
}

/// Cloneable bounded ingress handle; success requires the coordinator's reply.
#[derive(Clone)]
pub struct Handle {
    requests: mpsc::Sender<Request>,
}

impl Handle {
    /// Admit one request or report unavailable; a lost response remains retryable.
    pub async fn request(&self, operation: Operation) -> Result<Value, AdmissionError> {
        let (response, receive) = oneshot::channel();
        self.requests
            .try_send(Request {
                operation,
                response,
            })
            .map_err(|_| AdmissionError::new(503, "Coordinator unavailable or busy"))?;
        receive.await.map_err(|_| {
            AdmissionError::new(
                503,
                "Coordinator stopped; retry with the same event identity",
            )
        })?
    }
}

/// UTC clock advanced monotonically during one process, accounting for suspend time.
struct Clock {
    start: tokio::time::Instant,
    utc_ms: i64,
    last_ms: Cell<i64>,
}

impl Clock {
    fn new() -> Self {
        Self {
            start: tokio::time::Instant::now(),
            utc_ms: chrono::Utc::now().timestamp_millis(),
            last_ms: Cell::new(0),
        }
    }
    fn now(&self) -> i64 {
        let now = self
            .utc_ms
            .saturating_add(self.start.elapsed().as_millis().min(i64::MAX as u128) as i64)
            .max(chrono::Utc::now().timestamp_millis())
            .max(self.last_ms.get());
        self.last_ms.set(now);
        now
    }
}

/// Retire registered producers off the executor; an inconclusive query retains cards.
async fn retire_exited(tasks: &mut TaskStore) -> Vec<String> {
    let identities: Vec<_> = tasks
        .tasks
        .iter()
        .filter_map(|r| r.producer_process)
        .collect();
    if identities.is_empty() {
        return Vec::new();
    }
    let exited =
        match tokio::task::spawn_blocking(move || crate::process::exited(&identities)).await {
            Ok(exited) => exited,
            Err(error) => {
                tracing::warn!(%error, "Producer process observation failed");
                return Vec::new();
            }
        };
    let cards: Vec<_> = tasks
        .tasks
        .iter()
        .filter(|r| r.producer_process.is_some_and(|id| exited.contains(&id)))
        .map(|r| r.card_id.clone())
        .collect();
    for id in &cards {
        tasks.close(id);
    }
    cards
}

/// Coordinator owns all accepted business state and protocol scheduling state.
pub struct Coordinator {
    settings: Settings,
    stored: StoredState,
    storage: Storage,
    device: DeviceSession,
    requests: mpsc::Receiver<Request>,
    updater: Value,
    clock: Clock,
}

impl Coordinator {
    /// Apply the current session state only when lock following is configured.
    pub fn set_session_locked(&mut self, locked: bool) {
        self.device
            .set_session_locked(self.settings.lock_action != LockAction::None && locked);
    }

    /// Open durable state off the executor and reconstruct only still-valid content.
    pub async fn open(
        settings: Settings,
        directory: &Path,
    ) -> Result<(Self, Handle, std::thread::JoinHandle<()>)> {
        let directory = directory.to_owned();
        let (database, mut stored) = tokio::task::spawn_blocking(move || -> Result<_> {
            let database = Database::open(&directory)?;
            let stored = database.load()?;
            Ok((database, stored))
        })
        .await??;
        let clock = Clock::new();
        let now = clock.now();
        if now < stored.saved_at_ms {
            // Without a trustworthy cross-process elapsed time, expire timed content conservatively.
            for timed in stored.weather.iter_mut() {
                timed.expires_at_ms = 0;
            }
            for timed in stored.alert.iter_mut() {
                timed.expires_at_ms = 0;
            }
            let terminal: Vec<_> = stored
                .tasks
                .tasks
                .iter()
                .filter(|r| r.completed_at_ms.is_some())
                .map(|r| r.card_id.clone())
                .collect();
            for id in terminal {
                stored.tasks.close(&id);
            }
        }
        stored
            .tasks
            .expire(now, settings.completed_retention_seconds);
        retire_exited(&mut stored.tasks).await;
        stored.saved_at_ms = now;
        let (storage, worker) = Storage::start(database);
        storage.save(stored.clone()).await?;
        let (send, requests) = mpsc::channel(64);
        let updater = weather::updater_status(settings.weather.as_ref());
        let mut device = DeviceSession::default();
        device.set_lock_action(settings.lock_action);
        device.set_unlock_poll_seconds(settings.unlock_poll_seconds);
        Ok((
            Self {
                settings,
                stored,
                storage,
                device,
                requests,
                updater,
                clock,
            },
            Handle { requests: send },
            worker,
        ))
    }

    async fn save(&mut self, mut candidate: StoredState) -> Result<(), AdmissionError> {
        candidate.saved_at_ms = self.clock.now();
        self.storage
            .save(candidate.clone())
            .await
            .map_err(|error| {
                tracing::error!(%error, "Durable state commit failed");
                AdmissionError::new(503, "State could not be committed; retry the operation")
            })?;
        self.stored = candidate;
        Ok(())
    }

    async fn expire(&mut self, now: i64) -> Result<(), AdmissionError> {
        let mut candidate = self.stored.clone();
        let mut expired = candidate
            .tasks
            .expire(now, self.settings.completed_retention_seconds);
        expired.extend(retire_exited(&mut candidate.tasks).await);
        if !expired.is_empty() {
            self.save(candidate).await?;
            for id in expired {
                self.device.remove(&id);
            }
        }
        Ok(())
    }

    async fn operate(&mut self, operation: Operation) -> Result<Value, AdmissionError> {
        let now = self.clock.now();
        self.expire(now).await?;
        match operation {
            Operation::Submit(mut event) => {
                event.validate()?;
                let update = self.stored.tasks.prepare(&event, now)?;
                let mut notification = "none";
                if update.outcome == "accepted" {
                    let mut candidate = self.stored.clone();
                    candidate.tasks.commit(&update);
                    let retired = retire_exited(&mut candidate.tasks).await;
                    let closed = event.state == crate::tasks::TaskState::Closed
                        || retired.contains(&update.record.card_id);
                    let notify = update.notify && !closed;
                    if notify && self.device.online() && !self.device.can_notify(now) {
                        return Err(AdmissionError::new(
                            503,
                            "Notification queue is full; retry the event",
                        ));
                    }
                    self.save(candidate).await?;
                    for id in retired {
                        self.device.remove(&id);
                    }
                    if notify {
                        notification = if self.device.online() {
                            "queued"
                        } else {
                            "skipped_offline"
                        };
                    }
                    if closed {
                        self.device.remove(&update.record.card_id);
                    } else {
                        self.device.publish(&update.record, notify, now);
                    }
                }
                Ok(
                    json!({"outcome":update.outcome,"card_id":update.record.card_id,
                    "revision":update.record.revision,"notification":notification,"device_state":self.device.state}),
                )
            }
            Operation::Tasks => Ok(Value::Array(
                self.stored
                    .tasks
                    .tasks
                    .iter()
                    .map(|record| {
                        let mut value = serde_json::to_value(&record.event)
                            .expect("Task serialization is infallible");
                        value
                            .as_object_mut()
                            .expect("Task event is an object")
                            .remove("event_id");
                        value["revision"] = json!(record.revision);
                        if let Some(owner) = record.producer_process {
                            value["producer_process"] = json!(owner);
                        }
                        value["card_id"] = json!(record.card_id);
                        value["delivery"] = self.device.card_status(&record.card_id);
                        value
                    })
                    .collect(),
            )),
            Operation::Close(id) => {
                let id = normalize_uuid(&id)?;
                let mut candidate = self.stored.clone();
                let removed = candidate.tasks.close(&id);
                if removed {
                    self.save(candidate).await?;
                    self.device.remove(&id);
                }
                Ok(json!({"card_id":id,"removed":removed,"device_state":self.device.state}))
            }
            Operation::Status => Ok(self.device.status(&self.stored, now)),
            Operation::Settings => Ok(self.device.settings_status(&self.stored)),
            Operation::SessionLocked(locked) => {
                self.set_session_locked(locked);
                Ok(self.device.settings_status(&self.stored))
            }
            Operation::Brightness(value) => {
                if value > 100 {
                    return Err(AdmissionError::new(
                        422,
                        "Brightness must be between 0 and 100",
                    ));
                }
                let mut candidate = self.stored.clone();
                candidate.brightness_percent = value;
                self.save(candidate).await?;
                self.device.brightness_changed();
                Ok(self.device.settings_status(&self.stored))
            }
            Operation::Weather => Ok(self.device.weather_status(&self.stored, now)),
            Operation::SetWeather(value) => {
                if let Some(value) = &value {
                    value.validate()?;
                }
                let mut candidate = self.stored.clone();
                candidate.weather = value.map(|value| Timed {
                    expires_at_ms: now + i64::from(value.valid_for_seconds) * 1000,
                    value,
                });
                self.save(candidate).await?;
                self.device.weather_changed();
                Ok(self.device.weather_status(&self.stored, now))
            }
            Operation::Alert => Ok(self.device.alert_status(&self.stored, now)),
            Operation::SetAlert(value) => self.set_alert(value, now).await,
            Operation::Updater => Ok(self.updater.clone()),
            Operation::WeatherResult(result) => {
                self.updater["last_attempt"] = json!(chrono::Utc::now().to_rfc3339());
                match result {
                    Ok((value, source)) => {
                        let validity = self
                            .settings
                            .weather
                            .as_ref()
                            .map_or(1800, |w| w.valid_for_seconds);
                        let expiry = (source * 1000 + i64::from(validity) * 1000)
                            .min(now + i64::from(validity) * 1000);
                        if expiry <= now {
                            return Err(AdmissionError::new(
                                422,
                                "Weather expired before admission",
                            ));
                        }
                        let mut candidate = self.stored.clone();
                        candidate.weather = Some(Timed {
                            value,
                            expires_at_ms: expiry,
                        });
                        self.save(candidate).await?;
                        self.device.weather_changed();
                        self.updater["last_success"] = json!(chrono::Utc::now().to_rfc3339());
                        self.updater["source_time"] = json!(source);
                        self.updater["last_error"] = Value::Null;
                    }
                    Err(error) => {
                        tracing::warn!(%error, "Weather refresh failed");
                        self.updater["last_error"] = json!(error);
                    }
                }
                Ok(self.updater.clone())
            }
        }
    }

    async fn set_alert(
        &mut self,
        mut value: Option<AlertRequest>,
        now: i64,
    ) -> Result<Value, AdmissionError> {
        if let Some(value) = &mut value {
            value.validate()?;
        }
        let old = self.stored.alert.as_ref();
        let same = value
            .as_ref()
            .zip(old)
            .is_some_and(|(new, old)| new.alert_id == old.value.alert_id);
        if same
            && let (Some(new), Some(old)) = (&value, old)
            && new.sequence <= old.value.sequence
        {
            if new == &old.value {
                return Ok(self.device.alert_status(&self.stored, now));
            }
            return Err(AdmissionError::new(
                409,
                "Stale or conflicting weather alert sequence",
            ));
        }
        let trigger = !same
            || old.is_some_and(|a| a.remaining(now) == 0)
            || value
                .as_ref()
                .zip(old)
                .is_some_and(|(new, old)| new.severity_value() > old.value.severity_value());
        let notify = value.is_some() && self.device.online() && trigger;
        let mut candidate = self.stored.clone();
        candidate.alert = value.map(|value| Timed {
            expires_at_ms: now + i64::from(value.valid_for_seconds) * 1000,
            value,
        });
        self.save(candidate).await?;
        self.device
            .alert_changed(notify, self.stored.alert.is_some());
        Ok(self.device.alert_status(&self.stored, now))
    }

    /// Run until explicit shutdown; device failures reconnect without losing accepted state.
    pub async fn run(
        mut self,
        mut events: mpsc::Receiver<transport::Event>,
        commands: mpsc::Sender<transport::Command>,
        mut stop: watch::Receiver<bool>,
    ) -> Result<()> {
        let mut maintenance = tokio::time::interval(Duration::from_secs(1));
        loop {
            let now = self.clock.now();
            match self.device.poll(&self.stored, now) {
                Ok(envelopes) => {
                    for envelope in envelopes {
                        commands.try_send(transport::Command::Send(
                            self.device.generation,
                            Box::new(envelope),
                        ))?;
                    }
                }
                Err(error) => {
                    self.device.disconnected(error.to_string());
                    commands.try_send(transport::Command::Reconnect(self.device.generation))?;
                }
            }
            let delay = self
                .device
                .deadline()
                .map_or(Duration::from_secs(86400), |deadline| {
                    Duration::from_millis(deadline.saturating_sub(self.clock.now()).max(0) as u64)
                });
            tokio::select! {
                _ = stop.changed() => break,
                event = events.recv() => match event {
                    Some(transport::Event::Connected(generation)) => {
                        let hello = self.device.connected(generation, self.clock.now());
                        commands.try_send(transport::Command::Send(generation, Box::new(hello)))?;
                    }
                    Some(transport::Event::Feedback(generation, envelope)) if generation == self.device.generation => {
                        if let Err(error) = self.device.feedback(*envelope, &self.stored, self.clock.now()) {
                            self.device.disconnected(error.to_string());
                            commands.try_send(transport::Command::Reconnect(generation))?;
                        }
                    }
                    Some(transport::Event::Disconnected(generation, reason)) if generation >= self.device.generation => {
                        self.device.generation = generation;
                        self.device.disconnected(reason);
                    }
                    None => anyhow::bail!("Transport task stopped unexpectedly"),
                    _ => {},
                },
                _ = tokio::time::sleep(delay) => {},
                _ = maintenance.tick() => self.expire(self.clock.now()).await?,
                request = self.requests.recv() => match request {
                    Some(request) => { let result = self.operate(request.operation).await; let _ = request.response.send(result); }
                    None => break,
                }
            }
        }
        self.requests.close();
        Ok(())
    }
}

/// Retrieve weather without holding business state or database resources.
pub async fn run_weather(
    settings: crate::config::WeatherSettings,
    handle: Handle,
    mut stop: watch::Receiver<bool>,
) -> Result<()> {
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(10))
        .build()?;
    while !*stop.borrow() {
        let attempt = async {
            let mut response = client
                .get("https://api.open-meteo.com/v1/forecast")
                .query(&[
                    ("latitude", settings.latitude.to_string()),
                    ("longitude", settings.longitude.to_string()),
                    ("current", "temperature_2m,weather_code".into()),
                    ("daily", "temperature_2m_min,temperature_2m_max".into()),
                    ("timezone", "auto".into()),
                    ("timeformat", "unixtime".into()),
                    ("forecast_days", "1".into()),
                    ("temperature_unit", "celsius".into()),
                ])
                .send()
                .await?
                .error_for_status()?;
            let mut bytes = Vec::new();
            while let Some(chunk) = response.chunk().await? {
                anyhow::ensure!(
                    bytes.len() + chunk.len() <= 65_536,
                    "Weather response exceeds 64 KiB"
                );
                bytes.extend_from_slice(&chunk);
            }
            let data: Value = serde_json::from_slice(&bytes)?;
            weather::build_weather(&data, &settings, chrono::Utc::now().timestamp_millis())
        };
        let result = tokio::select! { _ = stop.changed() => break, result = attempt => result };
        let fetched = result.is_ok();
        let admitted = handle
            .request(Operation::WeatherResult(result.map_err(|e| e.to_string())))
            .await;
        if let Err(error) = &admitted {
            tracing::warn!(%error, "Weather result could not be admitted");
        }
        let delay = if fetched && admitted.is_ok() {
            settings.refresh_seconds
        } else {
            settings.retry_seconds
        };
        tokio::select! { _ = stop.changed() => break, _ = tokio::time::sleep(Duration::from_secs(delay)) => {} }
    }
    Ok(())
}
