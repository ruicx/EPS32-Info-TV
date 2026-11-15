//! Read-only Windows WTS sampling and supervised helper shutdown.

#![cfg(windows)]

use std::time::Duration;

use info_tv::{
    config::{LockAction, Settings},
    runtime::{Coordinator, Operation},
    session_lock::Monitor,
};
use tokio::sync::{mpsc, watch};

/// Check display policy against local, remote, disconnected, and switching sessions.
#[test]
fn only_active_unlocked_console_session_allows_display() {
    use std::os::windows::process::CommandExt;

    // Load the production C# policy without starting the polling loop.
    let helper = include_str!("../src/session_lock.ps1")
        .split("$hostProcess =")
        .next()
        .expect("helper definitions");
    let script = format!(
        "{helper}\n{}",
        r#"
$cases = @(
    @(7, 0, 1, 7, $false), # Local, active, unlocked.
    @(7, 0, 0, 7, $true),  # Local, active, locked.
    @(7, 0, 1, 8, $true),  # Unlocked RDP session; console belongs elsewhere.
    @(7, 4, 1, 8, $true),  # RDP disconnected, unlock flag retained.
    @(7, 4, 1, 7, $true),  # Disconnected even if console ID still matches.
    @(7, 1, 1, 7, $true),  # Connecting is not yet active.
    @(7, 0, 1, [uint32]::MaxValue, $true) # No console during switching.
)
foreach ($case in $cases) {
    $actual = [InfoTvSession]::RequiresLock($case[0], $case[1], $case[2], $case[3])
    if ($actual -ne $case[4]) { throw "Incorrect display policy: $case" }
}
try {
    [InfoTvSession]::RequiresLock(7, 0, -1, 7)
    throw 'Unknown lock state was accepted'
} catch [System.Management.Automation.MethodInvocationException] {
    if ($_.Exception.InnerException -isnot [InvalidOperationException]) { throw }
}
exit 0
"#
    );
    let output = std::process::Command::new("powershell.exe")
        .creation_flags(0x0800_0000)
        .args(["-NoProfile", "-NonInteractive", "-Command", &script])
        .output()
        .expect("policy helper");
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

/// Exercise the actual embedded helper without locking Windows or opening USB.
#[tokio::test]
async fn windows_monitor_reports_current_session_and_stops_cleanly() {
    let monitor = Monitor::start().await.expect("query current WTS session");
    let locked = monitor.locked;
    let directory = tempfile::TempDir::new().expect("temp");
    let (mut coordinator, handle, worker) = Coordinator::open(
        Settings {
            lock_action: LockAction::ScreenOff,
            ..Settings::default()
        },
        directory.path(),
    )
    .await
    .expect("coordinator");
    // Seed the opposite state to prove that the monitor forwards its sample.
    coordinator.set_session_locked(!locked);
    let (stop, receive_stop) = watch::channel(false);
    let (_events, receive_events) = mpsc::channel(32);
    let (commands, _receive_commands) = mpsc::channel(8);
    let actor = tokio::spawn(coordinator.run(receive_events, commands, receive_stop.clone()));
    let monitor = tokio::spawn(monitor.run(handle.clone(), receive_stop));
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let settings = handle.request(Operation::Settings).await.expect("settings");
            if settings["screen_off_for_lock"] == locked {
                assert_eq!(settings["brightness_percent"], 100);
                assert_eq!(
                    settings["effective_brightness_percent"],
                    if locked { 0 } else { 100 }
                );
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .expect("sample admission");
    stop.send(true).expect("stop");
    tokio::time::timeout(Duration::from_secs(3), monitor)
        .await
        .expect("monitor shutdown")
        .expect("monitor task")
        .expect("helper terminated");
    actor.await.expect("actor task").expect("actor");
    tokio::task::spawn_blocking(move || worker.join())
        .await
        .expect("worker task")
        .expect("worker");
}
