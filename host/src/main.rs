//! Dispatch short-lived commands before constructing any async runtime.

use info_tv::{
    cli::{self, Command},
    config::Settings,
};

/// Keep CLI/configuration failures distinct from runtime or HTTP failures.
fn main() {
    let cli = cli::parse();
    let result = match cli.command {
        Command::Hook(args) => {
            info_tv::hooks::run(args);
            return;
        }
        Command::Serve(args) => {
            let (settings, path) = match cli::settings(&args) {
                Ok(value) => value,
                Err(error) => {
                    eprintln!("Configuration error: {error:#}");
                    std::process::exit(2);
                }
            };
            tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .map_err(anyhow::Error::from)
                .and_then(|runtime| runtime.block_on(cli::serve(args, settings, path)))
        }
        Command::Ports { config } => {
            let settings = match std::env::current_dir()
                .map_err(anyhow::Error::from)
                .and_then(|cwd| {
                    Settings::load(
                        config.as_deref(),
                        &cwd,
                        &info_tv::config::installation_directory()?,
                    )
                }) {
                Ok((settings, _)) => settings,
                Err(error) => {
                    eprintln!("Configuration error: {error:#}");
                    std::process::exit(2);
                }
            };
            info_tv::transport::ports(settings.usb_vid, settings.usb_pid).and_then(|value| {
                println!("{}", serde_json::to_string_pretty(&value)?);
                Ok(())
            })
        }
        Command::Autostart { command } => info_tv::autostart::run(command),
        _ => cli::client(cli),
    };
    if let Err(error) = result {
        eprintln!("info-tv: {error:#}");
        std::process::exit(1);
    }
}
