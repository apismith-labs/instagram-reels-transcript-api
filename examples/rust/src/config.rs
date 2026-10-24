use crate::{
    error::{Error, ErrorKind, Result},
    journal::{InMemoryJournal, Journal},
    transport::{Clock, ReqwestTransport, SystemClock, Transport},
    validators::validate_charge_cap,
};
use std::sync::Arc;

pub const DEFAULT_ACTOR_ID: &str = "apple_yang/instagram-transcripts-scraper";
pub const EXPECTED_BUILD_NUMBER: &str = "0.0.50";
pub const EXPECTED_BUILD_ID: &str = "aJLRmMdQapLQRT4sJ";

#[derive(Clone)]
pub struct Config {
    pub(crate) token: String,
    pub(crate) actor_id: String,
    pub(crate) session_id: Option<String>,
    pub(crate) build_number: String,
    pub(crate) build_id: String,
    pub(crate) charge_cap: String,
    pub(crate) dataset_page_limit: usize,
    pub(crate) poll_timeout: std::time::Duration,
    pub(crate) transport: Arc<dyn Transport>,
    pub(crate) clock: Arc<dyn Clock>,
    pub(crate) journal: Arc<dyn Journal>,
}

pub struct ConfigBuilder {
    token: Option<String>,
    actor_id: String,
    session_id: Option<String>,
    charge_cap: Option<String>,
    dataset_page_limit: usize,
    poll_timeout: std::time::Duration,
    transport: Option<Arc<dyn Transport>>,
    clock: Option<Arc<dyn Clock>>,
    journal: Option<Arc<dyn Journal>>,
}

impl Config {
    pub fn builder() -> ConfigBuilder {
        ConfigBuilder::default()
    }
}

impl Default for ConfigBuilder {
    fn default() -> Self {
        Self {
            token: None,
            actor_id: DEFAULT_ACTOR_ID.to_owned(),
            session_id: None,
            charge_cap: None,
            dataset_page_limit: 1000,
            poll_timeout: std::time::Duration::from_secs(300),
            transport: None,
            clock: None,
            journal: None,
        }
    }
}

impl ConfigBuilder {
    pub fn token(mut self, value: impl Into<String>) -> Self {
        self.token = Some(value.into());
        self
    }
    pub fn actor_id(mut self, value: impl Into<String>) -> Self {
        self.actor_id = value.into();
        self
    }
    pub fn session_id(mut self, value: Option<String>) -> Self {
        self.session_id = value.filter(|s| !s.trim().is_empty());
        self
    }
    pub fn max_total_charge_usd(mut self, value: impl Into<String>) -> Self {
        self.charge_cap = Some(value.into());
        self
    }
    #[deprecated(
        note = "every Actor-creating operation always requires a positive per-Run charge cap"
    )]
    pub fn require_charge_cap(self, _value: bool) -> Self {
        self
    }
    pub fn dataset_page_limit(mut self, value: usize) -> Self {
        self.dataset_page_limit = value;
        self
    }
    pub fn poll_timeout(mut self, value: std::time::Duration) -> Self {
        self.poll_timeout = value;
        self
    }
    pub fn transport(mut self, value: Arc<dyn Transport>) -> Self {
        self.transport = Some(value);
        self
    }
    pub fn clock(mut self, value: Arc<dyn Clock>) -> Self {
        self.clock = Some(value);
        self
    }
    pub fn journal(mut self, value: Arc<dyn Journal>) -> Self {
        self.journal = Some(value);
        self
    }
    pub fn build(self) -> Result<Config> {
        let token = self.token.filter(|v| !v.trim().is_empty()).ok_or_else(|| {
            Error::new(
                ErrorKind::Configuration,
                "config",
                "APIFY_TOKEN must be provided explicitly",
            )
        })?;
        if self.actor_id.trim().is_empty() {
            return Err(Error::new(
                ErrorKind::Configuration,
                "config",
                "actor id is required",
            ));
        }
        // G1 deliberately fails closed for every creation path; `require_charge_cap(false)`
        // cannot silently invent an amount or remove the request-level safety cap.
        let charge_cap = validate_charge_cap(self.charge_cap.as_deref())?;
        if self.dataset_page_limit == 0 {
            return Err(Error::new(
                ErrorKind::Configuration,
                "config",
                "dataset page limit must be positive",
            ));
        }
        let transport: Arc<dyn Transport> = match self.transport {
            Some(transport) => transport,
            None => Arc::new(ReqwestTransport::new().map_err(|_| {
                Error::new(
                    ErrorKind::Configuration,
                    "config",
                    "could not initialize HTTP transport",
                )
            })?),
        };
        if !transport.guarantees_single_shot_post() {
            return Err(Error::new(
                ErrorKind::Configuration,
                "config",
                "transport does not guarantee single-shot POST",
            ));
        }
        Ok(Config {
            token,
            actor_id: self.actor_id,
            session_id: self.session_id,
            build_number: EXPECTED_BUILD_NUMBER.to_owned(),
            build_id: EXPECTED_BUILD_ID.to_owned(),
            charge_cap,
            dataset_page_limit: self.dataset_page_limit,
            poll_timeout: self.poll_timeout,
            transport,
            clock: self.clock.unwrap_or_else(|| Arc::new(SystemClock)),
            journal: self
                .journal
                .unwrap_or_else(|| Arc::new(InMemoryJournal::default())),
        })
    }
}
