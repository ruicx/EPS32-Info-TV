//! Explicit per-user login startup; registration never occurs during normal serve.

use std::{borrow::Cow, path::Path};

use anyhow::Result;
use clap::Subcommand;

/// User-invoked login startup management, without installing a system service.
#[derive(Subcommand)]
pub enum AutostartCommand {
    Install {
        #[arg(long)]
        config: Option<std::path::PathBuf>,
        #[arg(long)]
        state_dir: Option<std::path::PathBuf>,
    },
    Status,
    Remove,
}

/// Quote a literal PowerShell argument; embedded apostrophes remain data.
#[cfg(windows)]
fn quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "''"))
}

/// Prefer ordinary Windows drive paths only when their filesystem meaning is unchanged.
fn path_text(path: &Path) -> Cow<'_, str> {
    let text = path.to_string_lossy();
    #[cfg(windows)]
    if let Some(ordinary) = text.strip_prefix(r"\\?\")
        && ordinary.as_bytes().get(1) == Some(&b':')
        && ordinary.as_bytes().get(2) == Some(&b'\\')
        && ordinary.encode_utf16().count() < 260
        && std::fs::canonicalize(ordinary).ok().as_deref() == Some(path)
    {
        return Cow::Owned(ordinary.to_owned());
    }
    text
}

/// Quote one native Windows argument, including trailing backslashes and quotes.
fn native_argument(value: &str) -> String {
    let mut quoted = String::from("\"");
    let mut backslashes = 0;
    for character in value.chars() {
        if character == '\\' {
            backslashes += 1;
            continue;
        }
        let count = if character == '"' {
            backslashes * 2 + 1
        } else {
            backslashes
        };
        quoted.extend(std::iter::repeat_n('\\', count));
        quoted.push(character);
        backslashes = 0;
    }
    quoted.extend(std::iter::repeat_n('\\', backslashes * 2));
    quoted.push('"');
    quoted
}

/// Encode explicit host overrides for Task Scheduler's native command line.
pub fn startup_arguments(state: Option<&Path>, config: Option<&Path>) -> String {
    let mut arguments = Vec::new();
    for (option, path) in [("--state-dir", state), ("--config", config)] {
        if let Some(path) = path {
            arguments.push(option.to_owned());
            arguments.push(native_argument(&path_text(path)));
        }
    }
    arguments.join(" ")
}

/// Execute an explicit autostart operation on Windows under the current user.
#[cfg(windows)]
pub fn run(command: AutostartCommand) -> Result<()> {
    use std::os::windows::process::CommandExt;
    let identity = "$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent(); $taskName = 'info-tv-' + $identity.User.Value;";
    let script = match command {
        AutostartCommand::Install { config, state_dir } => {
            let cwd = std::env::current_dir()?;
            let installation = crate::config::installation_directory()?;
            let launcher = installation.join("info-tv-startup.exe");
            anyhow::ensure!(
                launcher.is_file(),
                "Cannot find {}. Extract both Windows executables from the same release.",
                launcher.display()
            );
            let (_, config) = crate::config::Settings::load(config.as_deref(), &cwd, &installation)?;
            let state = state_dir.map(|path| if path.is_absolute() { path } else { cwd.join(path) });
            let arguments = startup_arguments(state.as_deref(), config.as_deref());
            let argument_option = if arguments.is_empty() {
                String::new()
            } else {
                format!(" -Argument {}", quote(&arguments))
            };
            format!("$ErrorActionPreference = 'Stop'; {identity}
                $action = New-ScheduledTaskAction -Execute {}{} -WorkingDirectory {};
                $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name;
                $principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Limited;
                $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1);
                Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null;
                @{{ installed = $true; task = $taskName; launcher = {} }} | ConvertTo-Json -Compress;",
                quote(&path_text(&launcher)), argument_option,
                quote(&path_text(&installation)), quote(&path_text(&launcher)))
        }
        AutostartCommand::Status => format!("$ErrorActionPreference = 'Stop'; {identity}
            $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue;
            @{{ installed = ($null -ne $task); task = $taskName; state = [string]$task.State }} | ConvertTo-Json -Compress;"),
        AutostartCommand::Remove => format!("$ErrorActionPreference = 'Stop'; {identity}
            $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue;
            if ($null -ne $task) {{ Unregister-ScheduledTask -TaskName $taskName -Confirm:$false; }}
            @{{ installed = $false; task = $taskName }} | ConvertTo-Json -Compress;"),
    };
    let output = std::process::Command::new("powershell.exe")
        .creation_flags(0x0800_0000)
        .args(["-NoProfile", "-NonInteractive", "-Command", &script])
        .output()?;
    anyhow::ensure!(
        output.status.success(),
        "Startup registration failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    println!("{}", String::from_utf8_lossy(&output.stdout).trim());
    Ok(())
}

/// Other platforms report the currently supported startup integration explicitly.
#[cfg(not(windows))]
pub fn run(_command: AutostartCommand) -> Result<()> {
    anyhow::bail!("Login startup management currently supports Windows only")
}
