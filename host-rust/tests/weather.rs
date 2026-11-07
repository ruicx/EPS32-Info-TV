//! Provider parsing preserves source freshness and never fabricates hazard alerts.

use info_tv::{config::WeatherSettings, weather};
use serde_json::json;

#[test]
fn forecast_source_time_ranges_and_rounding() {
    let settings = WeatherSettings {
        location: "Shanghai".into(),
        latitude: 31.2304,
        longitude: 121.4737,
        refresh_seconds: 900,
        retry_seconds: 60,
        valid_for_seconds: 1800,
    };
    let now = 1_800_000_000i64;
    let forecast = json!({"current":{"time":now-1000,"temperature_2m":20.5,"weather_code":2},
        "daily":{"time":[now-3600],"temperature_2m_min":[16.2],"temperature_2m_max":[23.8]}});
    let (value, source) =
        weather::build_weather(&forecast, &settings, now * 1000).expect("weather");
    assert_eq!(source, now - 1000);
    assert_eq!(value.valid_for_seconds, 800);
    assert_eq!(value.temperature_c, 20);
    assert_eq!(value.daily_high_c, Some(24));
    for (path, replacement) in [
        ("time", json!(now - 4000)),
        ("time", json!(now + 4000)),
        ("time", json!(i64::MAX)),
        ("temperature_2m", json!(null)),
        ("temperature_2m", json!(true)),
        ("weather_code", json!(null)),
    ] {
        let mut invalid = forecast.clone();
        invalid["current"][path] = replacement;
        assert!(weather::build_weather(&invalid, &settings, now * 1000).is_err());
    }
    let mut invalid = forecast.clone();
    invalid["daily"]["temperature_2m_min"] = json!([25]);
    assert!(weather::build_weather(&invalid, &settings, now * 1000).is_err());
    for (code, expected) in [
        (97, "storm"),
        (86, "snow"),
        (67, "rain"),
        (48, "fog"),
        (999, "unknown"),
    ] {
        assert_eq!(weather::condition(code), expected);
    }
}

#[test]
fn display_labels_match_python_unicode_printability() {
    for invalid in [
        "City\n",
        "\u{7f}City",
        "\u{200b}City",
        "City\u{2028}",
        "\u{e000}City",
        "City\u{a0}",
    ] {
        assert!(weather::validate_label(invalid, 64, true).is_err());
    }
    assert!(weather::validate_label("Shanghai 上海", 64, true).is_ok());
    assert_eq!(
        info_tv::hooks::display_text(" A\u{200b}界\n B ", 7),
        "A 界 B"
    );
}
