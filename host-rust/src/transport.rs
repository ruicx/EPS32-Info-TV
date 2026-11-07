//! Async byte I/O isolated from business state, with generation-tagged reconnects.

use std::time::Duration;

use anyhow::{Result, bail};
use prost::Message;
use serde_json::{Value, json};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    sync::{mpsc, watch},
};
use tokio_serial::{SerialPortBuilderExt, SerialPortType};

use crate::{
    config::Settings,
    protocol::{self, FrameDecoder, pb},
};

/// A connection event tagged so a replaced stream cannot supply stale feedback.
pub enum Event {
    Connected(u64),
    Feedback(u64, Box<pb::Envelope>),
    Disconnected(u64, String),
}

/// A bounded I/O request from the coordinator.
pub enum Command {
    Send(u64, Box<pb::Envelope>),
    Reconnect(u64),
}

/// List candidates without acquiring any serial handle.
pub fn ports(vid: u16, pid: u16) -> Result<Vec<Value>> {
    Ok(tokio_serial::available_ports()?.into_iter().map(|port| {
        let (vendor, product, serial_number, description) = match port.port_type {
            SerialPortType::UsbPort(usb) => (Some(usb.vid), Some(usb.pid), usb.serial_number, usb.product),
            _ => (None, None, None, None),
        };
        json!({"port":port.port_name,"description":description,"vid":vendor.map(|v| format!("{v:04X}")),"pid":product.map(|p| format!("{p:04X}")),
            "serial_number":serial_number,"candidate":vendor==Some(vid) && product==Some(pid)})
    }).collect())
}

/// Resolve one explicit serial path or exactly one matching USB device.
pub fn resolve(settings: &Settings) -> Result<String> {
    if settings.serial_port != "auto" {
        return Ok(settings.serial_port.clone());
    }
    let candidates: Vec<_> = ports(settings.usb_vid, settings.usb_pid)?
        .into_iter()
        .filter(|p| p["candidate"] == true)
        .collect();
    if candidates.len() != 1 {
        bail!(
            "Expected one matching USB device, found {}",
            candidates.len()
        );
    }
    Ok(candidates[0]["port"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("Invalid serial port"))?
        .into())
}

/// Own one duplex stream until cancellation, explicit reconnect, or an I/O failure.
pub async fn run_stream<R, W>(
    mut read: R,
    mut write: W,
    generation: u64,
    events: &mpsc::Sender<Event>,
    commands: &mut mpsc::Receiver<Command>,
    stop: &mut watch::Receiver<bool>,
) -> Result<()>
where
    R: AsyncRead + Unpin,
    W: AsyncWrite + Unpin,
{
    events.send(Event::Connected(generation)).await?;
    let mut decoder = FrameDecoder::default();
    let mut buffer = [0u8; 4096];
    loop {
        tokio::select! {
            biased;
            _ = stop.changed() => return Ok(()),
            command = commands.recv() => match command {
                Some(Command::Reconnect(id)) if id == generation => bail!("Coordinator requested reconnect"),
                Some(Command::Send(id, envelope)) if id == generation => {
                    let bytes = protocol::encode_frame(&envelope.encode_to_vec())?;
                    tokio::time::timeout(Duration::from_millis(500), write.write_all(&bytes)).await??;
                }
                None => return Ok(()),
                _ => {},
            },
            count = read.read(&mut buffer) => {
                let count = count?;
                if count == 0 { bail!("Device stream closed"); }
                for payload in decoder.feed(&buffer[..count]) {
                    if let Some(envelope) = protocol::decode_feedback(&payload) {
                        tokio::select! {
                            _ = stop.changed() => return Ok(()),
                            result = events.send(Event::Feedback(generation, Box::new(envelope))) => result?,
                        }
                    }
                }
            }
        }
    }
}

/// Discover, open, and reconnect the serial stream while honoring bounded shutdown.
pub async fn run(
    settings: Settings,
    events: mpsc::Sender<Event>,
    mut commands: mpsc::Receiver<Command>,
    mut stop: watch::Receiver<bool>,
) -> Result<()> {
    let mut generation = 0u64;
    while !*stop.borrow() {
        generation += 1;
        let copy = settings.clone();
        let attempt = async {
            let path = tokio::task::spawn_blocking(move || resolve(&copy)).await??;
            let stream = tokio_serial::new(path, 115200)
                .dtr_on_open(false)
                .open_native_async()?;
            // Disable control-line reset behavior before protocol discovery.
            use tokio_serial::SerialPort;
            let mut stream = stream;
            stream.write_data_terminal_ready(false)?;
            stream.write_request_to_send(false)?;
            // Purging an async Windows handle aborts Tokio's already-pending read.
            // Framing and session checks discard stale input without cancelling I/O.
            let (read, write) = tokio::io::split(stream);
            run_stream(read, write, generation, &events, &mut commands, &mut stop).await
        }
        .await;
        if *stop.borrow() {
            break;
        }
        let reason = attempt
            .err()
            .map_or_else(|| "Device connection ended".into(), |e| e.to_string());
        tokio::select! {
            _ = stop.changed() => break,
            result = events.send(Event::Disconnected(generation, reason)) => result?,
        }
        tokio::select! {
            _ = stop.changed() => break,
            _ = tokio::time::sleep(Duration::from_secs(1)) => {},
        }
    }
    Ok(())
}
