//! Mock Cargo and rustc to check platform selection without cross-compiling binaries.

use std::{path::Path, path::PathBuf, process::Command};

/// Check native, cross-compilation, environment, and profile choices in either shell.
fn check_build_script(shell: &Path, powershell: bool) {
    const WINDOWS: &str = "x86_64-pc-windows-msvc";
    const WINDOWS_ARM: &str = "aarch64-pc-windows-msvc";
    const LINUX: &str = "x86_64-unknown-linux-gnu";
    let repository = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("repository");
    let script = repository.join(if powershell {
        "scripts/host/build_host.ps1"
    } else {
        "scripts/host/build_host.sh"
    });
    for (host, explicit, environment, expected, debug) in [
        (WINDOWS, None, None, WINDOWS, false),
        (LINUX, None, None, LINUX, false),
        (WINDOWS, Some(LINUX), None, LINUX, true),
        (LINUX, Some(WINDOWS), None, WINDOWS, false),
        (WINDOWS, None, Some(LINUX), LINUX, false),
        (LINUX, Some(WINDOWS), Some(LINUX), WINDOWS, true),
        (WINDOWS, Some(WINDOWS_ARM), None, WINDOWS_ARM, false),
    ] {
        let mut command = Command::new(shell);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x0800_0000);
        }
        if powershell {
            command.args([
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                r#"
function cargo { $global:LASTEXITCODE = 0; $args | ForEach-Object { Write-Output $_ } }
function rustc { $global:LASTEXITCODE = 0; 'host: ' + $env:INFO_TV_TEST_HOST }
$parameters = @{}
if ($env:INFO_TV_TEST_TARGET) { $parameters.Target = $env:INFO_TV_TEST_TARGET }
if ($env:INFO_TV_TEST_DEBUG -eq '1') { $parameters.Debug = $true }
& $env:INFO_TV_TEST_BUILD_SCRIPT @parameters
"#,
            ]);
        } else {
            command.args([
                "--noprofile",
                "--norc",
                "-c",
                r#"
cargo() { printf '%s\n' "$@"; }
rustc() { printf 'host: %s\n' "$INFO_TV_TEST_HOST"; }
parameters=()
if [[ -n "$INFO_TV_TEST_TARGET" ]]; then parameters+=(--target "$INFO_TV_TEST_TARGET"); fi
if [[ "$INFO_TV_TEST_DEBUG" == 1 ]]; then parameters+=(--debug); fi
source "$INFO_TV_TEST_BUILD_SCRIPT" "${parameters[@]}"
"#,
            ]);
        }
        command
            .env(
                "INFO_TV_TEST_BUILD_SCRIPT",
                script.to_string_lossy().replace('\\', "/"),
            )
            .env("INFO_TV_TEST_HOST", host)
            .env("INFO_TV_TEST_TARGET", explicit.unwrap_or(""))
            .env("INFO_TV_TEST_DEBUG", if debug { "1" } else { "0" });
        if let Some(target) = environment {
            command.env("CARGO_BUILD_TARGET", target);
        } else {
            command.env_remove("CARGO_BUILD_TARGET");
        }
        let output = command.output().expect("build script");
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let text = String::from_utf8(output.stdout).expect("Cargo arguments");
        let arguments: Vec<_> = text.lines().collect();
        assert_eq!(arguments.first(), Some(&"build"));
        assert!(arguments.contains(&"--locked"));
        assert!(!arguments.contains(&"--bins") && !arguments.contains(&"--bin"));
        assert!(
            arguments
                .windows(2)
                .any(|pair| pair == ["--target", expected]),
            "{arguments:?}"
        );
        assert_eq!(arguments.contains(&"--release"), !debug);
        assert_eq!(
            arguments
                .windows(2)
                .any(|pair| pair == ["--features", "windows-startup"]),
            matches!(expected, WINDOWS | WINDOWS_ARM),
            "{arguments:?}",
        );
    }
}

/// Locate Git Bash on Windows, avoiding an unrelated WSL bash shim.
#[cfg(windows)]
fn git_bash() -> Option<PathBuf> {
    let output = Command::new("git").arg("--exec-path").output().ok()?;
    if !output.status.success() {
        return None;
    }
    let directory = PathBuf::from(String::from_utf8(output.stdout).ok()?.trim());
    directory
        .ancestors()
        .map(|parent| parent.join("bin/bash.exe"))
        .find(|path| path.is_file())
}

/// Bash builds select features from the resolved target rather than the shell's OS.
#[test]
fn bash_build_selects_platform_automatically() {
    #[cfg(windows)]
    let Some(shell) = git_bash() else {
        eprintln!("SKIP: install Git Bash to validate the Bash build script on Windows");
        return;
    };
    #[cfg(not(windows))]
    let shell = PathBuf::from("bash");
    check_build_script(&shell, false);
}

/// Windows PowerShell applies the same target precedence and feature selection.
#[cfg(windows)]
#[test]
fn powershell_build_selects_platform_automatically() {
    check_build_script(Path::new("powershell.exe"), true);
}
