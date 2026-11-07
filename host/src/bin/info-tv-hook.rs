//! Compatibility entry point for existing Python hook command configurations.

use clap::Parser;

/// Preserve the separate hook executable while sharing the adapter implementation.
#[derive(Parser)]
#[command(name = "info-tv-hook", version)]
struct Cli {
    #[command(flatten)]
    args: info_tv::hooks::HookArgs,
}

/// Process one callback with neutral output on runtime delivery failures.
fn main() {
    info_tv::hooks::run(Cli::parse().args);
}
