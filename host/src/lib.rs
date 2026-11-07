//! Rust host: durable business state, bounded device delivery, and local ingress.

pub mod autostart;
pub mod cli;
pub mod config;
pub mod device;
pub mod hooks;
pub mod http;
pub mod protocol;
pub mod runtime;
pub mod storage;
pub mod tasks;
pub mod transport;
pub mod views;
pub mod weather;
