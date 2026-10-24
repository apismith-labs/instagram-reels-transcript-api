//! Safe, synchronous client for the Instagram transcript Actor.
//!
//! The library never reads process environment or repository files. Callers must
//! provide credentials and an explicit per-run charge cap through `Config`.

pub mod attribution;
pub mod bulk;
mod client;
pub mod config;
pub mod csv_batch;
pub mod dataset;
pub mod error;
mod execute;
pub mod journal;
pub mod output;
pub mod profile;
pub mod sanitize;
pub mod status;
pub mod transport;
pub mod validators;

pub use client::Client;
pub use config::{
    Config, ConfigBuilder, DEFAULT_ACTOR_ID, EXPECTED_BUILD_ID, EXPECTED_BUILD_NUMBER,
};
pub use error::{Error, ErrorKind, Result};
pub use journal::{InMemoryJournal, Journal, JournalRecord, JsonlFileJournal};
pub use profile::{ProfileOptions, ProfilePost, ProfileResult, ProfileStatus};
pub use status::{AttributionVerification, BuildVerification, Status, TranscriptResult};
pub use transport::{
    Clock, Request, ReqwestTransport, Response, SystemClock, Transport, TransportError,
    TransportErrorKind,
};
