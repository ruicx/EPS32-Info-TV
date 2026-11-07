//! Versioned durable snapshots with a dedicated SQLite worker and OS-held lock.

use std::{
    fs::{File, OpenOptions},
    path::Path,
    time::Duration,
};

use anyhow::{Context, Result, bail};
use rusqlite::{Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use tokio::sync::{mpsc, oneshot};

use crate::{
    tasks::TaskStore,
    weather::{AlertRequest, WeatherRequest},
};

/// Persist an original UTC expiry alongside accepted content.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Timed<T> {
    pub value: T,
    pub expires_at_ms: i64,
}

impl<T> Timed<T> {
    /// Remaining lifetime, clamped to a wire-compatible millisecond count.
    pub fn remaining(&self, now_ms: i64) -> u32 {
        self.expires_at_ms
            .saturating_sub(now_ms)
            .clamp(0, u32::MAX as i64) as u32
    }
}

/// Small bounded business snapshot; transport state and transient notices are excluded.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoredState {
    pub tasks: TaskStore,
    pub brightness_percent: u32,
    pub weather: Option<Timed<WeatherRequest>>,
    pub alert: Option<Timed<AlertRequest>>,
    pub saved_at_ms: i64,
}

impl Default for StoredState {
    fn default() -> Self {
        Self {
            tasks: TaskStore::default(),
            brightness_percent: 100,
            weather: None,
            alert: None,
            saved_at_ms: 0,
        }
    }
}

/// A locked database handle used only by a dedicated blocking worker.
pub struct Database {
    connection: Connection,
    _lock: File,
}

impl Database {
    /// Lock a state directory, validate schema, and open a fully synchronized database.
    pub fn open(directory: &Path) -> Result<Self> {
        std::fs::create_dir_all(directory)?;
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(directory.join("host.lock"))?;
        lock.try_lock()
            .context("Another service owns this state directory")?;
        let connection = Connection::open(directory.join("host.sqlite3"))?;
        connection.busy_timeout(Duration::from_secs(1))?;
        let version: u32 = connection.query_row("PRAGMA user_version", [], |r| r.get(0))?;
        if version > 1 {
            bail!("Unsupported host database schema {version}");
        }
        connection.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;")?;
        if version == 0 {
            connection.execute_batch(
                "BEGIN IMMEDIATE;
                CREATE TABLE host_state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
                PRAGMA user_version=1; COMMIT;",
            )?;
        }
        Ok(Self {
            connection,
            _lock: lock,
        })
    }

    /// Load the last committed state without treating invalid data as an empty database.
    pub fn load(&self) -> Result<StoredState> {
        let payload: Option<String> = self
            .connection
            .query_row("SELECT payload FROM host_state WHERE id=1", [], |r| {
                r.get(0)
            })
            .optional()?;
        let state: StoredState = payload
            .map(|text| serde_json::from_str(&text))
            .transpose()?
            .unwrap_or_default();
        anyhow::ensure!(
            state.tasks.tasks.len() <= 8
                && state.tasks.events.len() <= 256
                && state.tasks.retired.len() <= 256
                && state.brightness_percent <= 100,
            "Invalid stored state bounds"
        );
        anyhow::ensure!(state.saved_at_ms >= 0, "Invalid stored timestamp");
        for record in state.tasks.tasks.iter().chain(state.tasks.retired.iter()) {
            let mut event = record.event.clone();
            event.validate()?;
            crate::tasks::normalize_uuid(&record.card_id)?;
            anyhow::ensure!(
                record.revision > 0 && record.completed_at_ms.is_none_or(|v| v >= 0),
                "Invalid stored task metadata"
            );
        }
        for event in &state.tasks.events {
            let mut event = event.clone();
            event.validate()?;
        }
        if let Some(weather) = &state.weather {
            weather.value.validate()?;
        }
        if let Some(alert) = &state.alert {
            let mut value = alert.value.clone();
            value.validate()?;
        }
        Ok(state)
    }

    /// Atomically replace the bounded state; return only after the durable commit.
    pub fn save(&mut self, state: &StoredState) -> Result<()> {
        let payload = serde_json::to_string(state)?;
        let transaction = self.connection.transaction()?;
        transaction.execute(
            "INSERT INTO host_state(id,payload) VALUES(1,?1)
            ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            [&payload],
        )?;
        transaction.commit()?;
        Ok(())
    }
}

/// An asynchronous handle to the single database-owning blocking worker.
#[derive(Clone)]
pub struct Storage {
    requests: mpsc::Sender<(StoredState, oneshot::Sender<Result<()>>)>,
}

impl Storage {
    /// Move an opened database onto a dedicated thread and bound outstanding saves.
    pub fn start(mut database: Database) -> (Self, std::thread::JoinHandle<()>) {
        let (requests, mut receive) =
            mpsc::channel::<(StoredState, oneshot::Sender<Result<()>>)>(1);
        let thread = std::thread::spawn(move || {
            while let Some((state, response)) = receive.blocking_recv() {
                let _ = response.send(database.save(&state));
            }
        });
        (Self { requests }, thread)
    }

    /// Wait for one durable transaction; cancellation never acknowledges an uncommitted event.
    pub async fn save(&self, state: StoredState) -> Result<()> {
        let (send, receive) = oneshot::channel();
        self.requests
            .send((state, send))
            .await
            .map_err(|_| anyhow::anyhow!("Storage worker stopped"))?;
        receive
            .await
            .context("Storage worker stopped during commit")?
    }
}
