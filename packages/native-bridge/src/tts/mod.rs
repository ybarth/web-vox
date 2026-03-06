pub mod traits;

#[cfg(target_os = "macos")]
pub mod macos;

#[cfg(target_os = "windows")]
pub mod windows;

#[cfg(target_os = "linux")]
pub mod linux;

pub mod piper;
pub mod espeak;
pub mod chatterbox;
pub mod kokoro;
pub mod coqui;
pub mod coqui_xtts;
pub mod qwen;
pub mod qwen_clone;
pub mod alignment;
pub mod quality;
