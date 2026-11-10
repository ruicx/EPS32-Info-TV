//! Strict YAML discovery and startup-only configuration.

use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};

/// Action applied when the current Windows session locks.
#[derive(Debug, Clone, Copy, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LockAction {
    #[default]
    None,
    ScreenOff,
    DeepSleep,
}

impl LockAction {
    /// Return the matching shared-protocol enum value.
    pub fn protocol_value(self) -> i32 {
        match self {
            Self::None => 0,
            Self::ScreenOff => 1,
            Self::DeepSleep => 2,
        }
    }
}

/// Optional Open-Meteo location and retrieval policy.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WeatherSettings {
    pub location: String,
    pub latitude: f64,
    pub longitude: f64,
    #[serde(default = "refresh_default")]
    pub refresh_seconds: u64,
    #[serde(default = "retry_default")]
    pub retry_seconds: u64,
    #[serde(default = "validity_default")]
    pub valid_for_seconds: u32,
}

fn refresh_default() -> u64 {
    900
}
fn retry_default() -> u64 {
    60
}
fn validity_default() -> u32 {
    1800
}
fn port_default() -> String {
    "auto".into()
}
fn vid_default() -> u16 {
    0x303a
}
fn pid_default() -> u16 {
    0x1001
}
fn http_default() -> u16 {
    8765
}
fn retention_default() -> u64 {
    300
}

/// Immutable configuration, with defaults matching the Python implementation.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Settings {
    #[serde(default = "port_default")]
    pub serial_port: String,
    #[serde(default = "vid_default")]
    pub usb_vid: u16,
    #[serde(default = "pid_default")]
    pub usb_pid: u16,
    #[serde(default = "http_default")]
    pub http_port: u16,
    #[serde(default = "retention_default")]
    pub completed_retention_seconds: u64,
    #[serde(default)]
    pub lock_action: LockAction,
    #[serde(default)]
    pub unlock_poll_seconds: u32,
    #[serde(default)]
    pub weather: Option<WeatherSettings>,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            serial_port: port_default(),
            usb_vid: vid_default(),
            usb_pid: pid_default(),
            http_port: http_default(),
            completed_retention_seconds: retention_default(),
            lock_action: LockAction::None,
            unlock_poll_seconds: 0,
            weather: None,
        }
    }
}

impl Settings {
    /// Discover one YAML file; an explicit missing path never falls back.
    pub fn load(path: Option<&Path>, cwd: &Path) -> Result<(Self, Option<PathBuf>)> {
        let selected = path.map(|p| {
            if p.is_absolute() {
                p.to_owned()
            } else {
                cwd.join(p)
            }
        });
        let selected = match selected {
            Some(path) => Some(path),
            None => match cwd.join("info-tv.yaml").try_exists()? {
                true => Some(cwd.join("info-tv.yaml")),
                false => None,
            },
        };
        let settings = if let Some(path) = &selected {
            let text = std::fs::read_to_string(path)
                .with_context(|| format!("Cannot read {}", path.display()))?;
            let value: serde_yaml_ng::Value = serde_yaml_ng::from_str(&text)?;
            if !value.is_mapping() {
                bail!("Configuration must be a YAML mapping");
            }
            serde_yaml_ng::from_value(value).context("Invalid configuration")?
        } else {
            Self::default()
        };
        settings.validate()?;
        Ok((settings, selected))
    }

    /// Check ranges before opening storage, ports, or network listeners.
    pub fn validate(&self) -> Result<()> {
        if self.unlock_poll_seconds > 3600 {
            bail!("unlock_poll_seconds must be between 0 and 3600");
        }
        if self.serial_port.trim().is_empty()
            || self.http_port == 0
            || self.completed_retention_seconds == 0
        {
            bail!("serial_port must be nonblank; HTTP port and retention must be positive");
        }
        if let Some(w) = &self.weather {
            crate::weather::validate_label(&w.location, 24, true)?;
            if !w.latitude.is_finite()
                || !(-90.0..=90.0).contains(&w.latitude)
                || !w.longitude.is_finite()
                || !(-180.0..=180.0).contains(&w.longitude)
                || w.refresh_seconds < 60
                || w.retry_seconds == 0
                || !(1..=3600).contains(&w.valid_for_seconds)
            {
                bail!("Invalid weather coordinates or timing");
            }
        }
        Ok(())
    }
}

/// Return the existing per-user data location, independent of the working directory.
pub fn state_directory() -> PathBuf {
    std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            std::env::var_os("HOME")
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("."))
                .join(".local/state")
        })
        .join("info_tv")
}
