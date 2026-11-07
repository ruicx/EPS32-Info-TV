//! Validated weather/alert inputs and timestamp-based Open-Meteo conversion.

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::{
    config::WeatherSettings,
    tasks::{AdmissionError, normalize_uuid},
};

/// A printable, nonblank display label bounded by its UTF-8 encoding.
pub fn validate_label(value: &str, limit: usize, required: bool) -> Result<(), AdmissionError> {
    crate::tasks::validate_text(value, limit, required)?;
    if (required && value.trim().is_empty())
        || value.chars().any(|c| !crate::tasks::is_printable(c))
    {
        return Err(AdmissionError::new(
            422,
            "Weather labels must be printable and nonblank",
        ));
    }
    Ok(())
}

fn validity_default() -> u32 {
    1800
}

/// Current conditions submitted manually or by the automatic updater.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WeatherRequest {
    pub location: String,
    pub temperature_c: i32,
    pub condition: String,
    #[serde(default = "validity_default")]
    pub valid_for_seconds: u32,
    #[serde(default)]
    pub daily_low_c: Option<i32>,
    #[serde(default)]
    pub daily_high_c: Option<i32>,
}

impl WeatherRequest {
    /// Validate bounds and paired daily temperatures before persistence.
    pub fn validate(&self) -> Result<(), AdmissionError> {
        validate_label(&self.location, 24, true)?;
        if !(-100..=100).contains(&self.temperature_c)
            || !(1..=3600).contains(&self.valid_for_seconds)
            || !["unknown", "clear", "cloudy", "rain", "snow", "storm", "fog"]
                .contains(&self.condition.as_str())
            || self.daily_low_c.is_some() != self.daily_high_c.is_some()
            || self
                .daily_low_c
                .zip(self.daily_high_c)
                .is_some_and(|(low, high)| low < -100 || high > 100 || low > high)
        {
            return Err(AdmissionError::new(
                422,
                "Invalid weather condition, range, or validity",
            ));
        }
        Ok(())
    }
}

/// One source-selected, ordered hazard alert independent of ordinary weather.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AlertRequest {
    pub alert_id: String,
    pub sequence: i64,
    pub title: String,
    pub source: String,
    pub location: String,
    pub severity: String,
    #[serde(default)]
    pub detail: String,
    pub valid_for_seconds: u32,
}

impl AlertRequest {
    /// Validate public fields and canonicalize the source-selected UUID.
    pub fn validate(&mut self) -> Result<(), AdmissionError> {
        self.alert_id = normalize_uuid(&self.alert_id)?;
        for text in [&self.title, &self.source] {
            validate_label(text, 64, true)?;
        }
        validate_label(&self.location, 24, true)?;
        validate_label(&self.detail, 160, false)?;
        if self.sequence <= 0
            || !(1..=86400).contains(&self.valid_for_seconds)
            || self.severity_value() == 0
        {
            return Err(AdmissionError::new(
                422,
                "Invalid alert sequence, severity, or validity",
            ));
        }
        Ok(())
    }

    /// Return the existing ordered wire severity, zero for an invalid input.
    pub fn severity_value(&self) -> i32 {
        match self.severity.as_str() {
            "blue" => 1,
            "yellow" => 2,
            "orange" => 3,
            "red" => 4,
            _ => 0,
        }
    }
}

/// Map WMO weather codes to the existing display conditions.
pub fn condition(code: i64) -> &'static str {
    match code {
        0 | 1 => "clear",
        2 | 3 => "cloudy",
        45 | 48 => "fog",
        51 | 53 | 55 | 56 | 57 | 61 | 63 | 65 | 66 | 67 | 80 | 81 | 82 => "rain",
        71 | 73 | 75 | 77 | 85 | 86 => "snow",
        95 | 96 | 97 | 99 => "storm",
        _ => "unknown",
    }
}

/// Convert validated model data without renewing its original source lifetime.
pub fn build_weather(
    data: &Value,
    settings: &WeatherSettings,
    now_ms: i64,
) -> anyhow::Result<(WeatherRequest, i64)> {
    let source = data["current"]["time"]
        .as_i64()
        .ok_or_else(|| anyhow::anyhow!("Missing current time"))?;
    let source_ms = source
        .checked_mul(1000)
        .ok_or_else(|| anyhow::anyhow!("Invalid source timestamp"))?;
    anyhow::ensure!(
        source > 0 && source_ms <= now_ms.saturating_add(300_000),
        "Weather source timestamp is invalid or in the future"
    );
    let remaining = (source_ms
        .saturating_add(i64::from(settings.valid_for_seconds) * 1000)
        .saturating_sub(now_ms))
    .min(i64::from(settings.valid_for_seconds) * 1000);
    anyhow::ensure!(remaining > 0, "Weather source timestamp is stale");
    let number = |value: &Value| -> anyhow::Result<f64> {
        let result = value
            .as_f64()
            .ok_or_else(|| anyhow::anyhow!("Missing weather value"))?;
        anyhow::ensure!(
            result.is_finite() && (-100.0..=100.0).contains(&result),
            "Weather value out of range"
        );
        Ok(result)
    };
    for key in ["time", "temperature_2m_min", "temperature_2m_max"] {
        anyhow::ensure!(
            data["daily"][key].as_array().is_some_and(|a| a.len() == 1),
            "Invalid daily range"
        );
    }
    let day = data["daily"]["time"][0]
        .as_i64()
        .ok_or_else(|| anyhow::anyhow!("Invalid daily time"))?;
    anyhow::ensure!(
        day <= now_ms / 1000 && now_ms / 1000 < day.saturating_add(25 * 3600),
        "Weather daily range is not for the current day"
    );
    let low = number(&data["daily"]["temperature_2m_min"][0])?;
    let high = number(&data["daily"]["temperature_2m_max"][0])?;
    anyhow::ensure!(low <= high, "Weather daily range is reversed");
    let code = data["current"]["weather_code"]
        .as_i64()
        .ok_or_else(|| anyhow::anyhow!("Missing weather code"))?;
    let value = WeatherRequest {
        location: settings.location.clone(),
        temperature_c: number(&data["current"]["temperature_2m"])?.round_ties_even() as i32,
        condition: condition(code).into(),
        valid_for_seconds: (remaining / 1000).max(1) as u32,
        daily_low_c: Some(low.round_ties_even() as i32),
        daily_high_c: Some(high.round_ties_even() as i32),
    };
    value.validate()?;
    Ok((value, source))
}

/// Provider diagnostics, independent of downstream device feedback.
pub fn updater_status(settings: Option<&WeatherSettings>) -> Value {
    match settings {
        Some(w) => {
            json!({"enabled":true,"provider":"Open-Meteo","attribution":"https://open-meteo.com/",
            "location":w.location,"last_attempt":null,"last_success":null,"source_time":null,"last_error":null})
        }
        None => json!({"enabled":false}),
    }
}
