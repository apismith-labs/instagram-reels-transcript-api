use crate::profile::{ProfileOptions, ProfileResult};
use crate::{
    bulk::{BulkOptions, BulkResult},
    config::Config,
    error::Result,
    status::TranscriptResult,
};

pub struct Client {
    pub(crate) config: Config,
}
impl Client {
    pub fn new(config: Config) -> Self {
        Self { config }
    }

    /// Plan CSV rows without Config, credentials, transport construction, or network access.
    pub fn plan_csv(
        rows: &[crate::csv_batch::CsvRow],
        csv_path: Option<String>,
        per_run_cap_usd: Option<&str>,
        concurrency: usize,
    ) -> Result<crate::csv_batch::CsvPlan> {
        crate::csv_batch::plan_csv(rows, csv_path, per_run_cap_usd, concurrency)
    }
    /// Run the pinned Actor once and return a result attributed to this exact URL.
    pub fn get_transcript(&self, url: &str) -> Result<TranscriptResult> {
        crate::execute::get_transcript(&self.config, url)
    }

    /// Execute one Actor-native bulk Run for the deduplicated typed URL identities.
    pub fn get_transcripts(&self, urls: &[String], options: BulkOptions) -> BulkResult {
        crate::bulk::execute_bulk(&self.config, urls, options)
    }

    /// Fetch Profile post metadata. This endpoint does not produce transcript text.
    pub fn get_profile_posts(
        &self,
        usernames: &[String],
        options: ProfileOptions,
    ) -> Result<ProfileResult> {
        crate::profile::get_profile_posts(&self.config, usernames, options)
    }

    /// Resume a previously created Single Run using GET requests only.
    pub fn resume_transcript(&self, run_id: &str) -> Result<TranscriptResult> {
        crate::execute::resume_transcript(&self.config, run_id, None)
    }

    /// Resume a Single Run and require an optional caller-supplied URL to match the journal exactly.
    pub fn resume_transcript_with_url(
        &self,
        run_id: &str,
        expected_url: Option<&str>,
    ) -> Result<TranscriptResult> {
        crate::execute::resume_transcript(&self.config, run_id, expected_url)
    }

    /// Resume a previously created Native Bulk Run using GET requests only.
    pub fn resume_transcripts(&self, run_id: &str, urls: &[String]) -> BulkResult {
        crate::bulk::resume_bulk(&self.config, run_id, urls)
    }

    /// Run a CSV plan sequentially. The plan function itself is pure and needs no Client.
    pub fn run_csv(
        &self,
        rows: &[crate::csv_batch::CsvRow],
        options: crate::csv_batch::CsvExecuteOptions,
    ) -> crate::csv_batch::CsvBatchResult {
        crate::csv_batch::run_csv(&self.config, rows, options)
    }
}
