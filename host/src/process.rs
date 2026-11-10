//! Producer process identity and read-only lifecycle observation.

use serde::{Deserialize, Serialize};
use sysinfo::{Pid, ProcessRefreshKind, ProcessStatus, ProcessesToUpdate, System};

/// A local process identity, including its start time to detect PID reuse.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProcessIdentity {
    pub pid: u32,
    /// Process start time in seconds since the Unix epoch.
    pub started_at: u64,
}

/// A failed observation must not be interpreted as a process exit.
#[derive(Debug, Eq, PartialEq)]
enum Presence {
    Alive,
    Exited,
    Unknown,
}

/// Read only process identity metadata, without command lines or environment data.
fn snapshot(pids: ProcessesToUpdate<'_>) -> System {
    let mut system = System::new();
    system.refresh_processes_specifics(pids, true, ProcessRefreshKind::nothing());
    system
}

/// Identify a process only when its creation time is available.
pub fn identify(pid: u32) -> Option<ProcessIdentity> {
    let system = snapshot(ProcessesToUpdate::Some(&[Pid::from_u32(pid)]));
    let started_at = system.process(Pid::from_u32(pid))?.start_time();
    (started_at > 0).then_some(ProcessIdentity { pid, started_at })
}

/// Find the nearest AGY ancestor of the native hook, through intermediary shells.
pub fn agy_ancestor() -> Option<ProcessIdentity> {
    let system = snapshot(ProcessesToUpdate::All);
    let mut child = system.process(Pid::from_u32(std::process::id()))?;
    for _ in 0..32 {
        let parent = system.process(child.parent()?)?;
        // An inaccessible or reused parent cannot establish hook ownership.
        if child.start_time() == 0
            || parent.start_time() == 0
            || parent.start_time() > child.start_time()
        {
            return None;
        }
        let name = parent.name().to_str()?;
        if name == "agy" || (cfg!(windows) && name.eq_ignore_ascii_case("agy.exe")) {
            return Some(ProcessIdentity {
                pid: parent.pid().as_u32(),
                started_at: parent.start_time(),
            });
        }
        child = parent;
    }
    None
}

/// Compare observable creation times; zero means the query was inconclusive.
fn compare_start(expected: u64, observed: u64) -> Presence {
    if observed == 0 {
        Presence::Unknown
    } else if expected == observed {
        Presence::Alive
    } else {
        Presence::Exited
    }
}

/// Distinguish a missing Linux PID from an unreadable /proc entry.
fn missing_process(pid: u32) -> Presence {
    #[cfg(target_os = "linux")]
    {
        match std::fs::metadata(format!("/proc/{pid}")) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Presence::Exited,
            _ => Presence::Unknown,
        }
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = pid;
        Presence::Exited
    }
}

/// Return only identities proven to have exited in a successful process snapshot.
pub fn exited(identities: &[ProcessIdentity]) -> Vec<ProcessIdentity> {
    if identities.is_empty() {
        return Vec::new();
    }
    let own_pid = Pid::from_u32(std::process::id());
    let mut pids: Vec<_> = identities.iter().map(|id| Pid::from_u32(id.pid)).collect();
    pids.push(own_pid);
    let system = snapshot(ProcessesToUpdate::Some(&pids));
    // A failed refresh must not turn all registered producers into closed cards.
    if system.process(own_pid).is_none_or(|p| p.start_time() == 0) {
        return Vec::new();
    }
    identities
        .iter()
        .copied()
        .filter(|identity| {
            let presence = match system.process(Pid::from_u32(identity.pid)) {
                Some(process) if process.status() == ProcessStatus::Zombie => Presence::Exited,
                Some(process) => compare_start(identity.started_at, process.start_time()),
                None => missing_process(identity.pid),
            };
            presence == Presence::Exited
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn creation_time_distinguishes_live_reused_and_unreadable_processes() {
        assert_eq!(compare_start(100, 100), Presence::Alive);
        assert_eq!(compare_start(100, 101), Presence::Exited);
        assert_eq!(compare_start(100, 0), Presence::Unknown);
    }
}
