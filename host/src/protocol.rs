//! Shared generated messages and bounded COBS/CRC framing.

use prost::Message;
use uuid::Uuid;

/// Bindings generated from the authoritative shared schema at build time.
#[allow(clippy::all)]
pub mod pb {
    include!(concat!(env!("OUT_DIR"), "/info_tv.v1.rs"));
}

pub const MAX_PAYLOAD: usize = 4096;
const MAX_ENCODED: usize = 4120;

/// Give a command its process session and immutable transmission identity.
pub fn envelope(session_id: &str, body: pb::envelope::Body) -> pb::Envelope {
    pb::Envelope {
        protocol_version: 1,
        session_id: session_id.into(),
        message_id: Uuid::new_v4().simple().to_string(),
        body: Some(body),
    }
}

/// Encode a nonempty bounded payload with zero delimiters and CRC32-IEEE.
pub fn encode_frame(payload: &[u8]) -> anyhow::Result<Vec<u8>> {
    anyhow::ensure!(
        !payload.is_empty() && payload.len() <= MAX_PAYLOAD,
        "Invalid payload size"
    );
    let mut raw = payload.to_vec();
    raw.extend_from_slice(&crc32fast::hash(payload).to_le_bytes());
    let mut encoded = vec![0, 0];
    let mut index = 1;
    let mut code = 1u8;
    for value in raw {
        if value == 0 {
            encoded[index] = code;
            index = encoded.len();
            encoded.push(0);
            code = 1;
        } else {
            encoded.push(value);
            code += 1;
            if code == 255 {
                encoded[index] = code;
                index = encoded.len();
                encoded.push(0);
                code = 1;
            }
        }
    }
    encoded[index] = code;
    encoded.push(0);
    Ok(encoded)
}

/// Decode one delimiter-free frame, rejecting malformed COBS and CRC corruption.
pub fn decode_frame(encoded: &[u8]) -> Option<Vec<u8>> {
    let mut raw = Vec::new();
    let mut index = 0;
    while index < encoded.len() {
        let code = encoded[index] as usize;
        index += 1;
        if code == 0 || index + code - 1 > encoded.len() {
            return None;
        }
        raw.extend_from_slice(&encoded[index..index + code - 1]);
        index += code - 1;
        if code != 255 && index < encoded.len() {
            raw.push(0);
        }
    }
    if !(5..=MAX_PAYLOAD + 4).contains(&raw.len()) {
        return None;
    }
    let payload_len = raw.len() - 4;
    if raw[payload_len..] != crc32fast::hash(&raw[..payload_len]).to_le_bytes() {
        return None;
    }
    raw.truncate(payload_len);
    Some(raw)
}

/// Incremental decoder with bounded storage and delimiter resynchronization.
#[derive(Default)]
pub struct FrameDecoder {
    buffer: Vec<u8>,
    discard: bool,
}

impl FrameDecoder {
    /// Consume a chunk, retaining incomplete frames and dropping oversized ones.
    pub fn feed(&mut self, chunk: &[u8]) -> Vec<Vec<u8>> {
        let mut result = Vec::new();
        for &value in chunk {
            if value == 0 {
                if !self.discard
                    && !self.buffer.is_empty()
                    && let Some(payload) = decode_frame(&self.buffer)
                {
                    result.push(payload);
                }
                self.buffer.clear();
                self.discard = false;
            } else if !self.discard {
                self.buffer.push(value);
                if self.buffer.len() > MAX_ENCODED {
                    self.buffer.clear();
                    self.discard = true;
                }
            }
        }
        result
    }
}

/// Parse only structurally supported, versioned feedback messages.
pub fn decode_feedback(payload: &[u8]) -> Option<pb::Envelope> {
    let value = pb::Envelope::decode(payload).ok()?;
    if value.protocol_version != 1 || value.message_id.is_empty() || value.message_id.len() > 36 {
        return None;
    }
    matches!(
        value.body,
        Some(
            pb::envelope::Body::Hello(_)
                | pb::envelope::Body::Acknowledgment(_)
                | pb::envelope::Body::Error(_)
                | pb::envelope::Body::Pong(_)
        )
    )
    .then_some(value)
}
