//! Explicit per-user login startup; registration never occurs during normal serve.

use std::path::Path;

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
fn quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "''"))
}

/// Build the hidden launcher's fixed paths without shell-interpolating user data.
pub fn launcher(executable: &Path, cwd: &Path, state: &Path, config: Option<&Path>) -> String {
    let mut script = format!(
        "$ErrorActionPreference = 'Stop'\nSet-Location -LiteralPath {}\n& {} 'serve' '--state-dir' {}",
        quote(&cwd.to_string_lossy()),
        quote(&executable.to_string_lossy()),
        quote(&state.to_string_lossy())
    );
    if let Some(config) = config {
        script.push_str(&format!(" '--config' {}", quote(&config.to_string_lossy())));
    }
    script.push_str("\nexit $LASTEXITCODE\n");
    script
}

/// Execute an explicit autostart operation on Windows under the current user.
#[cfg(windows)]
pub fn run(command: AutostartCommand) -> Result<()> {
    use std::os::windows::process::CommandExt;
    let identity = "$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent(); $taskName = 'info-tv-' + $identity.User.Value;";
    let script = match command {
        AutostartCommand::Install { config, state_dir } => {
            let cwd = std::env::current_dir()?;
            let (_, config) = crate::config::Settings::load(config.as_deref(), &cwd)?;
            let state = state_dir.unwrap_or_else(crate::config::state_directory);
            let state = if state.is_absolute() { state } else { cwd.join(state) };
            std::fs::create_dir_all(&state)?;
            let launcher_path = state.join("autostart.ps1");
            let text = launcher(&std::env::current_exe()?, &cwd, &state, config.as_deref());
            // Windows PowerShell reads non-ASCII script paths correctly with a UTF-8 BOM.
            std::fs::write(&launcher_path, format!("\u{feff}{text}"))?;
            format!("$ErrorActionPreference = 'Stop'; {identity}
                $action = New-ScheduledTaskAction -Execute ([IO.Path]::Combine($PSHOME, 'powershell.exe')) -Argument {} -WorkingDirectory {};
                $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name;
                $principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Limited;
                $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1);
                Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null;
                @{{ installed = $true; task = $taskName; launcher = {} }} | ConvertTo-Json -Compress;",
                quote(&format!("-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File \"{}\"", launcher_path.display())),
                quote(&cwd.to_string_lossy()), quote(&launcher_path.to_string_lossy()))
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
