//! Current Windows session lock detection through an embedded, hidden helper.

#[cfg(windows)]
use anyhow::{Context, Result, bail};
#[cfg(windows)]
use tokio::{
    io::{AsyncBufReadExt, BufReader, Lines},
    process::{Child, ChildStdout, Command},
    sync::watch,
};

/// One supervised PowerShell helper, retained so cancellation terminates it.
#[cfg(windows)]
pub struct Monitor {
    child: Child,
    lines: Lines<BufReader<ChildStdout>>,
    pub locked: bool,
}

#[cfg(windows)]
impl Monitor {
    /// Query initial state before allowing the device brightness handshake.
    pub async fn start() -> Result<Self> {
        let mut child = Command::new("powershell.exe")
            .creation_flags(0x0800_0000)
            .args([
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                include_str!("session_lock.ps1"),
            ])
            .stdin(std::process::Stdio::null())
            .env("INFO_TV_HOST_PID", std::process::id().to_string())
            .stdout(std::process::Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .context("Cannot start Windows session lock monitor")?;
        let lines = BufReader::new(child.stdout.take().context("Missing monitor output")?).lines();
        let mut monitor = Self {
            child,
            lines,
            locked: false,
        };
        monitor.locked =
            tokio::time::timeout(std::time::Duration::from_secs(10), monitor.next_state())
                .await
                .context("Windows session lock monitor startup timed out")??;
        Ok(monitor)
    }

    /// Read a validated state or report a failed monitor.
    async fn next_state(&mut self) -> Result<bool> {
        // No runtime deadline: a suspended computer cannot produce samples until resume.
        let line = self.lines.next_line().await?;
        match line.as_deref() {
            Some("locked") => Ok(true),
            Some("unlocked") => Ok(false),
            _ => bail!("Windows session lock monitor stopped or returned invalid state"),
        }
    }

    /// Forward sampled state to the coordinator and reap the helper at shutdown.
    pub async fn run(
        mut self,
        handle: crate::runtime::Handle,
        mut stop: watch::Receiver<bool>,
    ) -> Result<()> {
        let result = async {
            while !*stop.borrow() {
                let locked = tokio::select! {
                    _ = stop.changed() => break,
                    state = self.next_state() => state?,
                };
                // Repeated samples also retry admission if the bounded ingress is busy.
                if let Err(error) = handle
                    .request(crate::runtime::Operation::SessionLocked(locked))
                    .await
                {
                    tracing::warn!(%error, "Session lock state could not be admitted");
                }
            }
            Ok(())
        }
        .await;
        self.child.kill().await?;
        result
    }
}
