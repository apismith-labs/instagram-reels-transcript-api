use crate::{
    bulk::{BulkOptions, BulkResult},
    config::Config,
    error::Result,
    status::TranscriptResult,
};

pub struct Client {
    config: Config,
}
impl Client {
    pub fn new(config: Config) -> Self {
        Self { config }
    }
    /// Run the pinned Actor once and return a result attributed to this exact URL.
    pub fn get_transcript(&self, url: &str) -> Result<TranscriptResult> {
        crate::execute::get_transcript(&self.config, url)
    }

    /// Execute one Actor-native bulk Run for the deduplicated typed URL identities.
    pub fn get_transcripts(&self, urls: &[String], options: BulkOptions) -> BulkResult {
        crate::bulk::execute_bulk(&self.config, urls, options)
    }
}
