use serde::{Deserialize, Serialize, Serializer};
use serde_json::Value;
use std::fmt;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Success,
    ActorError,
    Empty,
    NoTranscript,
    Unknown,
    TransportError,
    RunFailed,
    CreationUnknown,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BuildVerification {
    Verified,
    Mismatch,
    Unknown,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AttributionVerification {
    Verified,
    Mismatch,
    Unknown,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TranscriptResult {
    pub status: Status,
    pub run_id: Option<String>,
    pub dataset_id: Option<String>,
    pub source_url: String,
    pub text: Option<String>,
    pub segments: Vec<Value>,
    pub raw_items: Vec<Value>,
    pub error: Option<String>,
    pub stage: Option<String>,
    pub build_number: Option<String>,
    pub build_id: Option<String>,
    pub build_verification: BuildVerification,
    pub attribution_verification: AttributionVerification,
    pub dataset_complete: bool,
}

impl fmt::Debug for TranscriptResult {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let safe_string =
            |value: &Option<String>| value.as_deref().map(crate::sanitize::redact_text);
        let run_id = safe_string(&self.run_id);
        let dataset_id = safe_string(&self.dataset_id);
        let source_url = crate::sanitize::redact_text(&self.source_url);
        let text = safe_string(&self.text);
        let segments: Vec<Value> = self
            .segments
            .iter()
            .map(crate::sanitize::sanitize_value)
            .collect();
        let raw_items: Vec<Value> = self
            .raw_items
            .iter()
            .map(crate::sanitize::sanitize_value)
            .collect();
        let error = safe_string(&self.error);
        let stage = safe_string(&self.stage);
        let build_number = safe_string(&self.build_number);
        let build_id = safe_string(&self.build_id);
        f.debug_struct("TranscriptResult")
            .field("status", &self.status)
            .field("run_id", &run_id)
            .field("dataset_id", &dataset_id)
            .field("source_url", &source_url)
            .field("text", &text)
            .field("segments", &segments)
            .field("raw_items", &raw_items)
            .field("error", &error)
            .field("stage", &stage)
            .field("build_number", &build_number)
            .field("build_id", &build_id)
            .field("build_verification", &self.build_verification)
            .field("attribution_verification", &self.attribution_verification)
            .field("dataset_complete", &self.dataset_complete)
            .finish()
    }
}

impl Serialize for TranscriptResult {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        #[derive(Serialize)]
        #[serde(rename_all = "camelCase")]
        struct SafeResult<'a> {
            status: Status,
            run_id: &'a Option<String>,
            dataset_id: &'a Option<String>,
            source_url: &'a str,
            text: &'a Option<String>,
            segments: &'a Vec<Value>,
            raw_items: &'a Vec<Value>,
            error: &'a Option<String>,
            stage: &'a Option<String>,
            build_number: &'a Option<String>,
            build_id: &'a Option<String>,
            build_verification: BuildVerification,
            attribution_verification: AttributionVerification,
            dataset_complete: bool,
        }
        let safe = SafeResult {
            status: self.status,
            run_id: &self.run_id,
            dataset_id: &self.dataset_id,
            source_url: &self.source_url,
            text: &self.text,
            segments: &self.segments,
            raw_items: &self.raw_items,
            error: &self.error,
            stage: &self.stage,
            build_number: &self.build_number,
            build_id: &self.build_id,
            build_verification: self.build_verification,
            attribution_verification: self.attribution_verification,
            dataset_complete: self.dataset_complete,
        };
        let value = serde_json::to_value(safe).map_err(serde::ser::Error::custom)?;
        crate::sanitize::sanitize_value(&value).serialize(serializer)
    }
}

impl TranscriptResult {
    pub fn empty(source_url: &str, status: Status, stage: &str, error: Option<&str>) -> Self {
        Self {
            status,
            run_id: None,
            dataset_id: None,
            source_url: source_url.to_owned(),
            text: None,
            segments: Vec::new(),
            raw_items: Vec::new(),
            error: error.map(crate::sanitize::diagnostic),
            stage: Some(stage.to_owned()),
            build_number: None,
            build_id: None,
            build_verification: BuildVerification::Unknown,
            attribution_verification: AttributionVerification::Unknown,
            dataset_complete: false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn result_debug_redacts_raw_item_secret() {
        let result = TranscriptResult {
            status: Status::Success,
            run_id: Some("run-1".into()),
            dataset_id: Some("dataset-1".into()),
            source_url: "https://www.instagram.com/reel/abc/".into(),
            text: Some("normal transcript".into()),
            segments: vec![],
            raw_items: vec![serde_json::json!({"errMsg":"api_key=RAW_SECRET"})],
            error: None,
            stage: Some("done".into()),
            build_number: Some("0.0.50".into()),
            build_id: Some("build-id".into()),
            build_verification: BuildVerification::Verified,
            attribution_verification: AttributionVerification::Verified,
            dataset_complete: true,
        };
        let rendered = format!("{result:?}");
        assert!(!rendered.contains("RAW_SECRET"));
        assert!(rendered.contains("normal transcript"));
    }
}
