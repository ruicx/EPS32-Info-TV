//! Native Windows login launcher that keeps the CLI host out of a console.

#![cfg_attr(windows, windows_subsystem = "windows")]

/// Wait for the host and preserve its exit status for Task Scheduler.
#[cfg(windows)]
fn main() {
    let code = run().unwrap_or_else(|error| {
        eprintln!("info-tv-startup: {error}");
        1
    });
    std::process::exit(code);
}

/// Launch the adjacent host with inherited arguments and persistent startup diagnostics.
#[cfg(windows)]
fn run() -> std::io::Result<i32> {
    use std::{
        fs::OpenOptions,
        io::Write,
        mem::ManuallyDrop,
        os::windows::process::CommandExt,
        process::{Command, Stdio},
    };

    let executable = std::env::current_exe()?.canonicalize()?;
    let host = executable.with_file_name("info-tv.exe");
    let logs = executable.with_file_name("logs");
    std::fs::create_dir_all(&logs)?;
    let mut log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(logs.join("startup.log"))?;
    let result = (|| -> std::io::Result<i32> {
        let mut limits = win32job::ExtendedLimitInfo::new();
        limits.limit_kill_on_job_close();
        // Keep the job handle until process exit. Dropping it here would kill
        // this launcher before main can propagate the child's actual exit code.
        let job = ManuallyDrop::new(
            win32job::Job::create_with_limit_info(&limits).map_err(std::io::Error::other)?,
        );
        job.assign_current_process()
            .map_err(std::io::Error::other)?;
        let status = Command::new(&host)
            .arg("serve")
            .args(std::env::args_os().skip(1))
            .creation_flags(0x0800_0000)
            .env("NO_COLOR", "1")
            .stdin(Stdio::null())
            .stdout(log.try_clone()?)
            .stderr(log.try_clone()?)
            .status()?;
        Ok(status.code().unwrap_or(1))
    })();
    if let Err(error) = &result {
        writeln!(
            log,
            "info-tv-startup: Cannot start {}: {error}",
            host.display()
        )?;
    }
    result
}

/// Report the platform boundary when built with the other host binaries on Unix.
#[cfg(not(windows))]
fn main() {
    eprintln!("info-tv-startup supports Windows only");
    std::process::exit(1);
}
