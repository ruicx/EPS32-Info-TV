//! Real Windows launcher checks without registering or changing user startup tasks.

#![cfg(windows)]

use std::{
    os::windows::process::CommandExt,
    path::{Path, PathBuf},
    process::{Child, Command},
    time::{Duration, Instant},
};

/// Always reap a test launcher, including after a failed assertion.
struct Startup(Child);

impl Drop for Startup {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

/// Install a real launcher beside a console probe compiled with Windows PowerShell.
fn prepare_probe(installation: &Path) -> PathBuf {
    let launcher = installation.join("info-tv-startup.exe");
    let host = installation.join("info-tv.exe");
    std::fs::copy(env!("CARGO_BIN_EXE_info-tv-startup"), &launcher).expect("copy startup");
    let output_path = host.to_string_lossy().replace('\'', "''");
    let script = format!(
        "Add-Type -TypeDefinition @'\n{}\n'@ -OutputAssembly '{output_path}' -OutputType ConsoleApplication",
        include_str!("fixtures/startup-probe.cs")
    );
    let compiled = Command::new("powershell.exe")
        .creation_flags(0x0800_0000)
        .args(["-NoProfile", "-NonInteractive", "-Command", &script])
        .output()
        .expect("compile console probe");
    assert!(
        compiled.status.success(),
        "{}",
        String::from_utf8_lossy(&compiled.stderr)
    );
    launcher
}

/// Read the PE subsystem field shared by Windows x86-64 and ARM64 binaries.
fn subsystem(executable: &Path) -> u16 {
    let bytes = std::fs::read(executable).expect("PE executable");
    let pe = u32::from_le_bytes(bytes[0x3c..0x40].try_into().expect("PE offset")) as usize;
    assert_eq!(&bytes[pe..pe + 4], b"PE\0\0");
    let offset = pe + 24 + 68;
    u16::from_le_bytes(bytes[offset..offset + 2].try_into().expect("subsystem"))
}

/// The task entry point must not allocate its own console; the CLI keeps console semantics.
#[test]
fn startup_is_a_gui_binary_and_the_cli_remains_a_console_binary() {
    assert_eq!(
        subsystem(Path::new(env!("CARGO_BIN_EXE_info-tv-startup"))),
        2
    );
    assert_eq!(subsystem(Path::new(env!("CARGO_BIN_EXE_info-tv"))), 3);
}

/// Native startup preserves argument boundaries, waits, and starts the child without a console.
#[test]
fn startup_waits_for_a_consoleless_child_and_preserves_arguments_and_exit_code() {
    let installation = tempfile::Builder::new()
        .prefix("info tv user's ")
        .tempdir()
        .expect("installation");
    let workspace = tempfile::TempDir::new().expect("unrelated working directory");
    let launcher = prepare_probe(installation.path());
    let report = installation.path().join("probe.txt");
    let config = installation.path().join("设置 user's.yaml");
    std::fs::write(&config, "{}").expect("config");
    let state = installation.path().join("state with spaces");
    std::fs::create_dir(&state).expect("state");
    let state = std::path::PathBuf::from(format!("{}\\", state.display()));
    let arguments = info_tv::autostart::startup_arguments(Some(&state), Some(&config));
    let output = Command::new(&launcher)
        .raw_arg(arguments)
        .current_dir(workspace.path())
        .env("INFO_TV_STARTUP_PROBE", &report)
        .output()
        .expect("run startup");
    assert_eq!(output.status.code(), Some(37));
    let report = std::fs::read_to_string(&report).expect("child completed its report");
    let lines: Vec<_> = report.lines().collect();
    assert_eq!(
        lines,
        [
            "0",
            workspace.path().to_str().expect("working directory"),
            "serve",
            "--state-dir",
            state.to_str().expect("state"),
            "--config",
            config.to_str().expect("config"),
        ]
    );
    assert!(installation.path().join("logs/startup.log").is_file());
    assert!(!workspace.path().join("logs").exists());
    assert!(info_tv::autostart::startup_arguments(None, None).is_empty());
}

/// A missing adjacent host produces a task failure and a persistent diagnostic.
#[test]
fn missing_host_is_reported_without_an_interactive_error_dialog() {
    let directory = tempfile::TempDir::new().expect("installation");
    let launcher = directory.path().join("info-tv-startup.exe");
    std::fs::copy(env!("CARGO_BIN_EXE_info-tv-startup"), &launcher).expect("copy startup");
    let output = Command::new(launcher).output().expect("run startup");
    assert_eq!(output.status.code(), Some(1));
    let log = std::fs::read_to_string(directory.path().join("logs/startup.log"))
        .expect("persistent diagnostic");
    assert!(log.contains("Cannot start") && log.contains("info-tv.exe"));
}

/// Long state paths must retain the namespace prefix in the task's native arguments.
#[test]
fn task_arguments_preserve_extended_paths_for_long_state_directories() {
    let directory = tempfile::TempDir::new().expect("temp");
    let state = directory.path().join("x".repeat(220));
    std::fs::create_dir(&state).expect("long state directory");
    let state = state.canonicalize().expect("canonical state");
    let arguments = info_tv::autostart::startup_arguments(Some(&state), None);
    assert!(state.as_os_str().len() >= 260);
    assert!(arguments.contains(r"\\?\"));
}

/// Ending the task's launcher must also end the host process it owns.
#[test]
fn terminating_startup_does_not_leave_its_child_running() {
    let directory = tempfile::TempDir::new().expect("installation");
    let launcher = prepare_probe(directory.path());
    let report = directory.path().join("probe.txt");
    let mut startup = Startup(
        Command::new(launcher)
            .env("INFO_TV_STARTUP_PROBE", &report)
            .env("INFO_TV_STARTUP_PROBE_WAIT", "1")
            .spawn()
            .expect("persistent startup"),
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    let child_pid = loop {
        if let Some(pid) = std::fs::read_to_string(report.with_extension("pid"))
            .ok()
            .and_then(|text| text.parse::<u32>().ok())
        {
            break pid;
        }
        assert!(startup.0.try_wait().expect("startup status").is_none());
        assert!(Instant::now() < deadline, "probe startup timeout");
        std::thread::sleep(Duration::from_millis(20));
    };
    let identity = info_tv::process::identify(child_pid).expect("live probe identity");
    startup.0.kill().expect("terminate launcher");
    startup.0.wait().expect("reap launcher");
    let deadline = Instant::now() + Duration::from_secs(5);
    while info_tv::process::identify(child_pid) == Some(identity) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    let still_running = info_tv::process::identify(child_pid) == Some(identity);
    if still_running {
        let _ = Command::new("taskkill.exe")
            .args(["/PID", &child_pid.to_string(), "/F"])
            .creation_flags(0x0800_0000)
            .output();
    }
    assert!(
        !still_running,
        "task termination left the probe child running"
    );
}
