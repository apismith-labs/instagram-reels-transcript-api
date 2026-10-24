use std::fmt;
use thiserror::Error as ThisError;

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ErrorKind {
    Input,
    Configuration,
    Transport,
    Protocol,
    CreationUnknown,
    CreateRejected,
    RunFailed,
    Dataset,
    Attribution,
    BuildMismatch,
    Journal,
    Output,
}

#[derive(ThisError)]
#[error("{kind:?} at {stage}: {message}")]
pub struct Error {
    pub kind: ErrorKind,
    pub stage: &'static str,
    pub message: String,
    pub run_id: Option<String>,
    pub dataset_id: Option<String>,
}

impl fmt::Debug for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Error")
            .field("kind", &self.kind)
            .field("stage", &crate::sanitize::redact_text(self.stage))
            .field("message", &crate::sanitize::diagnostic(&self.message))
            .field(
                "run_id",
                &self.run_id.as_deref().map(crate::sanitize::redact_text),
            )
            .field(
                "dataset_id",
                &self.dataset_id.as_deref().map(crate::sanitize::redact_text),
            )
            .finish()
    }
}

impl Error {
    pub fn new(kind: ErrorKind, stage: &'static str, message: impl AsRef<str>) -> Self {
        Self {
            kind,
            stage,
            message: crate::sanitize::diagnostic(message.as_ref()),
            run_id: None,
            dataset_id: None,
        }
    }

    pub fn with_run(mut self, run_id: impl Into<String>) -> Self {
        self.run_id = Some(run_id.into());
        self
    }

    pub fn with_dataset(mut self, dataset_id: impl Into<String>) -> Self {
        self.dataset_id = Some(dataset_id.into());
        self
    }

    pub fn exit_code(&self) -> i32 {
        match self.kind {
            ErrorKind::Input | ErrorKind::Configuration => 2,
            ErrorKind::CreateRejected => 4,
            ErrorKind::CreationUnknown => 10,
            ErrorKind::RunFailed => 9,
            ErrorKind::Dataset
            | ErrorKind::Attribution
            | ErrorKind::BuildMismatch
            | ErrorKind::Protocol => 7,
            ErrorKind::Transport => 8,
            ErrorKind::Journal | ErrorKind::Output => 2,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stable_exit_codes_cover_public_failure_classes() {
        // Keeps CLI automation aligned with the documented status-to-exit-code contract.
        let cases = [
            (ErrorKind::Configuration, 2),
            (ErrorKind::CreateRejected, 4),
            (ErrorKind::CreationUnknown, 10),
            (ErrorKind::RunFailed, 9),
            (ErrorKind::Dataset, 7),
            (ErrorKind::Transport, 8),
        ];
        for (kind, expected) in cases {
            assert_eq!(Error::new(kind, "test", "safe").exit_code(), expected);
        }
    }
}
