//! Loopback HTTP routes preserving the producer-facing contract.

use axum::{
    Json, Router,
    extract::{DefaultBodyLimit, Path, State, rejection::JsonRejection},
    http::StatusCode,
    response::{Html, IntoResponse, Response},
    routing::{delete, get, post},
};
use serde::{Deserialize, de::DeserializeOwned};
use serde_json::{Value, json};

use crate::{
    runtime::{Handle, Operation},
    tasks::{AdmissionError, TaskEvent},
    weather::{AlertRequest, WeatherRequest},
};

impl IntoResponse for AdmissionError {
    fn into_response(self) -> Response {
        let detail = if self.status == 422 {
            json!([{"type":"value_error","loc":["body"],"msg":self.detail}])
        } else {
            json!(self.detail)
        };
        (
            StatusCode::from_u16(self.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR),
            Json(json!({"detail":detail})),
        )
            .into_response()
    }
}

/// Convert malformed JSON/type errors into the existing validation status.
fn body<T: DeserializeOwned>(value: Result<Json<T>, JsonRejection>) -> Result<T, AdmissionError> {
    value
        .map(|Json(value)| value)
        .map_err(|error| AdmissionError::new(422, error.body_text()))
}

/// Absolute brightness request; presence distinguishes off from missing input.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Brightness {
    brightness_percent: u32,
}

/// Build local routes without opening a listener or storing mutable global state.
pub fn router(handle: Handle) -> Router {
    let permits = std::sync::Arc::new(tokio::sync::Semaphore::new(64));
    Router::new()
        .route("/v1/task-events", post(submit))
        .route("/v1/tasks", get(tasks))
        .route("/v1/tasks/{card_id}", delete(close))
        .route("/v1/device", get(status))
        .route("/v1/device/settings", get(settings).put(brightness))
        .route(
            "/v1/weather",
            get(weather).put(set_weather).delete(clear_weather),
        )
        .route("/v1/weather/updater", get(updater))
        .route(
            "/v1/weather/alert",
            get(alert).put(set_alert).delete(clear_alert),
        )
        .route(
            "/openapi.json",
            get(|| async {
                (
                    [("content-type", "application/json")],
                    include_str!("../openapi.json"),
                )
            }),
        )
        .route(
            "/docs",
            get(|| async { Html(include_str!("../swagger.html")) }),
        )
        .layer(DefaultBodyLimit::max(16 * 1024))
        .layer(axum::middleware::from_fn(
            move |request: axum::extract::Request, next: axum::middleware::Next| {
                let permit = permits.clone().try_acquire_owned();
                async move {
                    let Ok(_permit) = permit else {
                        return AdmissionError::new(503, "Too many active HTTP requests")
                            .into_response();
                    };
                    match tokio::time::timeout(
                        std::time::Duration::from_secs(15),
                        next.run(request),
                    )
                    .await
                    {
                        Ok(response) => response,
                        Err(_) => AdmissionError::new(
                            503,
                            "Request timed out; retry with the same event identity",
                        )
                        .into_response(),
                    }
                }
            },
        ))
        .with_state(handle)
}

async fn submit(
    State(h): State<Handle>,
    value: Result<Json<TaskEvent>, JsonRejection>,
) -> Result<(StatusCode, Json<Value>), AdmissionError> {
    Ok((
        StatusCode::ACCEPTED,
        Json(h.request(Operation::Submit(body(value)?)).await?),
    ))
}
async fn tasks(State(h): State<Handle>) -> Result<Json<Value>, AdmissionError> {
    Ok(Json(h.request(Operation::Tasks).await?))
}
async fn close(
    State(h): State<Handle>,
    Path(id): Path<String>,
) -> Result<(StatusCode, Json<Value>), AdmissionError> {
    Ok((
        StatusCode::ACCEPTED,
        Json(h.request(Operation::Close(id)).await?),
    ))
}
async fn status(State(h): State<Handle>) -> Result<Json<Value>, AdmissionError> {
    Ok(Json(h.request(Operation::Status).await?))
}
async fn settings(State(h): State<Handle>) -> Result<Json<Value>, AdmissionError> {
    Ok(Json(h.request(Operation::Settings).await?))
}
async fn brightness(
    State(h): State<Handle>,
    value: Result<Json<Brightness>, JsonRejection>,
) -> Result<(StatusCode, Json<Value>), AdmissionError> {
    Ok((
        StatusCode::ACCEPTED,
        Json(
            h.request(Operation::Brightness(body(value)?.brightness_percent))
                .await?,
        ),
    ))
}
async fn weather(State(h): State<Handle>) -> Result<Json<Value>, AdmissionError> {
    Ok(Json(h.request(Operation::Weather).await?))
}
async fn set_weather(
    State(h): State<Handle>,
    value: Result<Json<WeatherRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<Value>), AdmissionError> {
    Ok((
        StatusCode::ACCEPTED,
        Json(h.request(Operation::SetWeather(Some(body(value)?))).await?),
    ))
}
async fn clear_weather(
    State(h): State<Handle>,
) -> Result<(StatusCode, Json<Value>), AdmissionError> {
    Ok((
        StatusCode::ACCEPTED,
        Json(h.request(Operation::SetWeather(None)).await?),
    ))
}
async fn updater(State(h): State<Handle>) -> Result<Json<Value>, AdmissionError> {
    Ok(Json(h.request(Operation::Updater).await?))
}
async fn alert(State(h): State<Handle>) -> Result<Json<Value>, AdmissionError> {
    Ok(Json(h.request(Operation::Alert).await?))
}
async fn set_alert(
    State(h): State<Handle>,
    value: Result<Json<AlertRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<Value>), AdmissionError> {
    Ok((
        StatusCode::ACCEPTED,
        Json(h.request(Operation::SetAlert(Some(body(value)?))).await?),
    ))
}
async fn clear_alert(State(h): State<Handle>) -> Result<(StatusCode, Json<Value>), AdmissionError> {
    Ok((
        StatusCode::ACCEPTED,
        Json(h.request(Operation::SetAlert(None)).await?),
    ))
}
