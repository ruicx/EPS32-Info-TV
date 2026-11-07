//! Compile the shared device schema using a build-only, bundled protoc.

/// Generate Rust bindings without requiring protoc on the developer's PATH.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("cargo:rerun-if-changed=../protocol/device.proto");
    let mut config = prost_build::Config::new();
    config.protoc_executable(protoc_bin_vendored::protoc_bin_path()?);
    config.compile_protos(&["../protocol/device.proto"], &["../protocol"])?;
    Ok(())
}
