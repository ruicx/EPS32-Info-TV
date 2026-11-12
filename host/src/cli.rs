//! Service startup and HTTP client command-line interface.

use std::{path::PathBuf, time::Duration};

use anyhow::{Context, Result};
use clap::{Args, Parser, Subcommand};
use serde::Serialize;
use serde_json::{Value, json};
use uuid::Uuid;

use crate::{
    config::{self, Settings},
    hooks::HookArgs,
};

/// Public command line, with the same client connection defaults as Python.
#[derive(Parser)]
#[command(name = "info-tv", version, about = "Local structured-display service")]
pub struct Cli {
    #[arg(long, default_value = "http://127.0.0.1:8765")]
    pub url: String,
    #[arg(long, default_value = "5", value_parser = positive_timeout)]
    pub timeout: f64,
    #[command(subcommand)]
    pub command: Command,
}

/// Installed executable roles; only Serve is persistent.
#[derive(Subcommand)]
pub enum Command {
    Serve(ServeArgs),
    Status,
    Ports {
        #[arg(long)]
        config: Option<PathBuf>,
    },
    Task {
        #[command(subcommand)]
        command: TaskCommand,
    },
    Weather {
        #[command(subcommand)]
        command: WeatherCommand,
    },
    Alert {
        #[command(subcommand)]
        command: AlertCommand,
    },
    Brightness {
        #[arg(value_parser = clap::value_parser!(u32).range(0..=100))]
        brightness_percent: Option<u32>,
    },
    Hook(HookArgs),
    Autostart {
        #[command(subcommand)]
        command: crate::autostart::AutostartCommand,
    },
}

/// Startup-only overrides and an explicit state directory for isolated deployments.
#[derive(Debug, Clone, Args)]
pub struct ServeArgs {
    #[arg(long)]
    pub config: Option<PathBuf>,
    #[arg(long)]
    pub serial_port: Option<String>,
    #[arg(long)]
    pub http_port: Option<u16>,
    #[arg(long)]
    pub state_dir: Option<PathBuf>,
}

/// Task client operations.
#[derive(Subcommand)]
pub enum TaskCommand {
    Submit(Box<TaskSubmit>),
    List,
    Close { card_id: Uuid },
}

/// Producer fields remain independent of device details.
#[derive(Args, Serialize)]
pub struct TaskSubmit {
    #[arg(long, default_value = "cli")]
    source: String,
    #[arg(long)]
    task_id: String,
    #[arg(long)]
    sequence: i64,
    #[arg(long, value_parser = ["running", "waiting_input", "completed", "failed", "interrupted", "closed"])]
    state: String,
    #[arg(long)]
    title: String,
    #[arg(long)]
    event_id: Option<Uuid>,
    #[arg(long, default_value = "")]
    detail: String,
    #[arg(long)]
    progress_percent: Option<u32>,
    #[arg(long, default_value = "task", value_parser = ["task", "code", "test", "build", "review", "deploy"])]
    icon: String,
    #[arg(long)]
    conversation_id: Option<String>,
    #[arg(long)]
    run_sequence: Option<i64>,
    #[arg(long, default_value = "")]
    conversation_title: String,
    #[arg(long, default_value = "")]
    context: String,
}

/// Current weather clients and automatic-retrieval diagnostics.
#[derive(Subcommand)]
pub enum WeatherCommand {
    Get,
    Clear,
    Updater,
    Set(WeatherSet),
}

/// A manual current-conditions update.
#[derive(Args, Serialize)]
pub struct WeatherSet {
    #[arg(long)]
    location: String,
    #[arg(long, allow_hyphen_values = true)]
    temperature_c: i32,
    #[arg(long, value_parser = ["unknown", "clear", "cloudy", "rain", "snow", "storm", "fog"])]
    condition: String,
    #[arg(long, default_value = "1800")]
    valid_for_seconds: u32,
    #[arg(long, allow_hyphen_values = true)]
    daily_low_c: Option<i32>,
    #[arg(long, allow_hyphen_values = true)]
    daily_high_c: Option<i32>,
}

/// Independent hazard alert clients.
#[derive(Subcommand)]
pub enum AlertCommand {
    Get,
    Clear,
    Set(AlertSet),
}

/// An ordered producer-selected alert.
#[derive(Args, Serialize)]
pub struct AlertSet {
    #[arg(long)]
    alert_id: Uuid,
    #[arg(long)]
    sequence: i64,
    #[arg(long)]
    title: String,
    #[arg(long)]
    source: String,
    #[arg(long)]
    location: String,
    #[arg(long, value_parser = ["blue", "yellow", "orange", "red"])]
    severity: String,
    #[arg(long, default_value = "")]
    detail: String,
    #[arg(long)]
    valid_for_seconds: u32,
}

/// Parse legacy server-option invocations through the same Serve implementation.
pub fn parse() -> Cli {
    let mut arguments: Vec<_> = std::env::args_os().collect();
    if arguments.get(1).is_some_and(|arg| {
        matches!(
            arg.to_string_lossy().split('=').next(),
            Some("--config" | "--serial-port" | "--http-port" | "--state-dir")
        )
    }) {
        arguments.insert(1, "serve".into());
    }
    Cli::parse_from(arguments)
}

/// Load the selected or discovered YAML and apply explicit overrides.
pub fn settings(args: &ServeArgs) -> Result<(Settings, Option<PathBuf>)> {
    let (mut settings, path) = Settings::load(
        args.config.as_deref(),
        &std::env::current_dir()?,
        &config::installation_directory()?,
    )?;
    if let Some(port) = &args.serial_port {
        settings.serial_port = port.clone();
    }
    if let Some(port) = args.http_port {
        settings.http_port = port;
    }
    settings.validate()?;
    Ok((settings, path))
}

/// Make exactly one HTTP request, bypassing environment proxy settings.
pub fn client(cli: Cli) -> Result<()> {
    anyhow::ensure!(
        positive_timeout(&cli.timeout.to_string()).is_ok(),
        "Invalid HTTP timeout"
    );
    let (method, endpoint, payload) = match cli.command {
        Command::Status => ("GET", "/v1/device".into(), None),
        Command::Task {
            command: TaskCommand::List,
        } => ("GET", "/v1/tasks".into(), None),
        Command::Task {
            command: TaskCommand::Close { card_id },
        } => ("DELETE", format!("/v1/tasks/{}", card_id.simple()), None),
        Command::Task {
            command: TaskCommand::Submit(mut value),
        } => {
            value.event_id = Some(value.event_id.unwrap_or_else(Uuid::new_v4));
            (
                "POST",
                "/v1/task-events".into(),
                Some(serde_json::to_value(value)?),
            )
        }
        Command::Weather { command } => match command {
            WeatherCommand::Get => ("GET", "/v1/weather".into(), None),
            WeatherCommand::Clear => ("DELETE", "/v1/weather".into(), None),
            WeatherCommand::Updater => ("GET", "/v1/weather/updater".into(), None),
            WeatherCommand::Set(value) => (
                "PUT",
                "/v1/weather".into(),
                Some(serde_json::to_value(value)?),
            ),
        },
        Command::Alert { command } => match command {
            AlertCommand::Get => ("GET", "/v1/weather/alert".into(), None),
            AlertCommand::Clear => ("DELETE", "/v1/weather/alert".into(), None),
            AlertCommand::Set(value) => (
                "PUT",
                "/v1/weather/alert".into(),
                Some(serde_json::to_value(value)?),
            ),
        },
        Command::Brightness { brightness_percent } => match brightness_percent {
            Some(value) => {
                anyhow::ensure!(value <= 100, "Brightness must be between 0 and 100");
                (
                    "PUT",
                    "/v1/device/settings".into(),
                    Some(json!({"brightness_percent":value})),
                )
            }
            None => ("GET", "/v1/device/settings".into(), None),
        },
        _ => anyhow::bail!("Expected an HTTP client command"),
    };
    let client = reqwest::blocking::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs_f64(cli.timeout))
        .build()?;
    let mut request = client.request(
        method.parse()?,
        format!("{}{endpoint}", cli.url.trim_end_matches('/')),
    );
    if let Some(payload) = payload {
        request = request.json(&payload);
    }
    let response = request.send().context("Request failed")?;
    let status = response.status();
    let text = response.text()?;
    anyhow::ensure!(status.is_success(), "HTTP {}: {text}", status.as_u16());
    let value: Value = serde_json::from_str(&text).context("Invalid JSON response")?;
    println!("{}", serde_json::to_string_pretty(&value)?);
    Ok(())
}

/// Validate client timeout syntax as a usage error before contacting the server.
fn positive_timeout(value: &str) -> Result<f64, String> {
    let timeout: f64 = value.parse().map_err(|_| "Expected a number".to_string())?;
    if !timeout.is_finite() || timeout <= 0.0 || Duration::try_from_secs_f64(timeout).is_err() {
        return Err("Timeout must be finite, positive, and representable".into());
    }
    Ok(timeout)
}

/// Run one service with supervised tasks and orderly SQLite/serial shutdown.
pub async fn serve(args: ServeArgs, settings: Settings, path: Option<PathBuf>) -> Result<()> {
    let (directory, logs) = match args.state_dir {
        Some(directory) => {
            let logs = directory.join("logs");
            (directory, logs)
        }
        None => {
            let installation = config::installation_directory()?;
            (installation.join("data"), installation.join("logs"))
        }
    };
    std::fs::create_dir_all(&logs)?;
    let file = tracing_appender::rolling::Builder::new()
        .rotation(tracing_appender::rolling::Rotation::DAILY)
        .filename_prefix("host")
        .max_log_files(7)
        .build(&logs)?;
    let (writer, _guard) = tracing_appender::non_blocking(file);
    use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .with(tracing_subscriber::fmt::layer().with_writer(std::io::stderr))
        .with(
            tracing_subscriber::fmt::layer()
                .with_ansi(false)
                .with_writer(writer),
        )
        .try_init()?;
    tracing::info!(configuration = ?path, state_directory = %directory.display(), log_directory = %logs.display(), "Starting info-tv");
    #[cfg(not(windows))]
    anyhow::ensure!(
        settings.lock_action == crate::config::LockAction::None,
        "lock_action currently supports Windows only"
    );
    #[cfg(windows)]
    let monitor = if settings.lock_action != crate::config::LockAction::None {
        Some(crate::session_lock::Monitor::start().await?)
    } else {
        None
    };
    #[cfg(windows)]
    let initial_locked = monitor.as_ref().is_some_and(|monitor| monitor.locked);
    #[cfg(not(windows))]
    let initial_locked = false;
    let (mut coordinator, handle, storage_worker) =
        crate::runtime::Coordinator::open(settings.clone(), &directory).await?;
    coordinator.set_session_locked(initial_locked);
    let listener =
        tokio::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, settings.http_port)).await?;
    let (stop, stop_receive) = tokio::sync::watch::channel(false);
    let (events, receive_events) = tokio::sync::mpsc::channel(32);
    let (commands, receive_commands) = tokio::sync::mpsc::channel(8);
    let mut tasks = tokio::task::JoinSet::new();
    tasks.spawn(coordinator.run(receive_events, commands, stop_receive.clone()));
    tasks.spawn(crate::transport::run(
        settings.clone(),
        events,
        receive_commands,
        stop_receive.clone(),
    ));
    #[cfg(windows)]
    if let Some(monitor) = monitor {
        tasks.spawn(monitor.run(handle.clone(), stop_receive.clone()));
    }
    if let Some(weather) = settings.weather {
        tasks.spawn(crate::runtime::run_weather(
            weather,
            handle.clone(),
            stop_receive.clone(),
        ));
    }
    let mut shutdown = stop_receive.clone();
    tasks.spawn(async move {
        axum::serve(listener, crate::http::router(handle))
            .with_graceful_shutdown(async move {
                let _ = shutdown.changed().await;
            })
            .await?;
        Ok(())
    });
    let result = tokio::select! {
        signal = shutdown_signal() => signal,
        ended = tasks.join_next() => match ended {
            Some(Ok(Ok(()))) => Err(anyhow::anyhow!("Background task exited unexpectedly")),
            Some(Ok(Err(error))) => Err(error), Some(Err(error)) => Err(error.into()),
            None => Err(anyhow::anyhow!("Service has no active tasks")),
        },
    };
    let _ = stop.send(true);
    let cleanup = async {
        while let Some(ended) = tasks.join_next().await {
            ended??;
        }
        Ok::<(), anyhow::Error>(())
    };
    let cleaned = tokio::time::timeout(Duration::from_secs(5), cleanup).await;
    if cleaned.is_err() {
        tasks.abort_all();
        while tasks.join_next().await.is_some() {}
    }
    // No accepted transaction is abandoned: the worker drains its bounded save queue.
    tokio::task::spawn_blocking(move || {
        storage_worker
            .join()
            .map_err(|_| anyhow::anyhow!("Storage worker panicked"))
    })
    .await??;
    result?;
    cleaned.context("Timed out stopping service tasks")??;
    Ok(())
}

async fn shutdown_signal() -> Result<()> {
    #[cfg(windows)]
    {
        let mut close = tokio::signal::windows::ctrl_close()?;
        let mut logoff = tokio::signal::windows::ctrl_logoff()?;
        let mut shutdown = tokio::signal::windows::ctrl_shutdown()?;
        tokio::select! { result = tokio::signal::ctrl_c() => result?, _ = close.recv() => {}, _ = logoff.recv() => {}, _ = shutdown.recv() => {} }
    }
    #[cfg(unix)]
    {
        let mut terminate =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
        tokio::select! { result = tokio::signal::ctrl_c() => result?, _ = terminate.recv() => {} }
    }
    Ok(())
}
