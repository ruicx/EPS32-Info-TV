//! Validate launcher quoting without registering a task or changing user startup.

#[cfg(windows)]
#[test]
fn hidden_launcher_with_spaces_and_apostrophes_parses_as_powershell() {
    use std::{os::windows::process::CommandExt, path::Path};
    let directory = tempfile::Builder::new()
        .prefix("info tv user's ")
        .tempdir()
        .expect("temp");
    let script = info_tv::autostart::launcher(
        Path::new("C:\\Program Files\\user's info-tv\\info-tv.exe"),
        directory.path(),
        &directory.path().join("state"),
        Some(&directory.path().join("settings.yaml")),
    );
    let path = directory.path().join("launch.ps1");
    std::fs::write(&path, format!("\u{feff}{script}")).expect("script");
    let literal = path.to_string_lossy().replace('\'', "''");
    let parser = format!(
        "$tokens=$null; $errors=$null; [System.Management.Automation.Language.Parser]::ParseFile('{literal}', [ref]$tokens, [ref]$errors) | Out-Null; if ($errors.Count) {{ $errors | Out-String | Write-Error; exit 1 }}"
    );
    let result = std::process::Command::new("powershell.exe")
        .creation_flags(0x0800_0000)
        .args(["-NoProfile", "-NonInteractive", "-Command", &parser])
        .output()
        .expect("PowerShell parser");
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
}
