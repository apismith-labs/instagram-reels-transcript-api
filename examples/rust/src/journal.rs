use crate::{
    error::{Error, ErrorKind, Result},
    sanitize::diagnostic,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{fmt, sync::Mutex};

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct JournalRecord {
    pub stage: String,
    pub mode: String,
    pub actor_id: String,
    pub source_url: Option<String>,
    pub run_id: Option<String>,
    pub dataset_id: Option<String>,
    pub run_status: Option<String>,
    pub build_number: Option<String>,
    pub build_id: Option<String>,
    pub build_verification: String,
    pub cap: Option<String>,
    pub input_digest: Option<String>,
    pub context: Option<Value>,
    pub error: Option<String>,
}

impl fmt::Debug for JournalRecord {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let safe = |value: &Option<String>| value.as_deref().map(crate::sanitize::redact_text);
        let source_url = safe(&self.source_url);
        let run_id = safe(&self.run_id);
        let dataset_id = safe(&self.dataset_id);
        let run_status = safe(&self.run_status);
        let build_number = safe(&self.build_number);
        let build_id = safe(&self.build_id);
        let cap = safe(&self.cap);
        let input_digest = safe(&self.input_digest);
        let context = self.context.as_ref().map(crate::sanitize::sanitize_value);
        let error = self.error.as_deref().map(diagnostic);
        f.debug_struct("JournalRecord")
            .field("stage", &crate::sanitize::redact_text(&self.stage))
            .field("mode", &crate::sanitize::redact_text(&self.mode))
            .field("actor_id", &crate::sanitize::redact_text(&self.actor_id))
            .field("source_url", &source_url)
            .field("run_id", &run_id)
            .field("dataset_id", &dataset_id)
            .field("run_status", &run_status)
            .field("build_number", &build_number)
            .field("build_id", &build_id)
            .field(
                "build_verification",
                &crate::sanitize::redact_text(&self.build_verification),
            )
            .field("cap", &cap)
            .field("input_digest", &input_digest)
            .field("context", &context)
            .field("error", &error)
            .finish()
    }
}

pub trait Journal: Send + Sync {
    fn append(&self, record: &JournalRecord) -> Result<()>;
    fn latest(&self, run_id: &str) -> Result<Option<JournalRecord>>;
}

#[derive(Default)]
pub struct InMemoryJournal {
    records: Mutex<Vec<JournalRecord>>,
}
impl InMemoryJournal {
    pub fn records(&self) -> Vec<JournalRecord> {
        self.records.lock().map(|r| r.clone()).unwrap_or_default()
    }
}
impl Journal for InMemoryJournal {
    fn append(&self, record: &JournalRecord) -> Result<()> {
        let mut safe = record.clone();
        safe.error = safe.error.as_deref().map(diagnostic);
        if let Some(context) = safe.context.take() {
            safe.context = Some(crate::sanitize::sanitize_value(&context));
        }
        if let Some(context) = &safe.context {
            if contains_sensitive_key(context) {
                return Err(Error::new(
                    ErrorKind::Journal,
                    "journal",
                    "journal context contains a credential key",
                ));
            }
        }
        self.records
            .lock()
            .map_err(|_| Error::new(ErrorKind::Journal, "journal", "journal lock poisoned"))?
            .push(safe);
        Ok(())
    }
    fn latest(&self, run_id: &str) -> Result<Option<JournalRecord>> {
        Ok(self
            .records
            .lock()
            .map_err(|_| Error::new(ErrorKind::Journal, "journal", "journal lock poisoned"))?
            .iter()
            .rev()
            .find(|r| r.run_id.as_deref() == Some(run_id))
            .cloned())
    }
}
fn contains_sensitive_key(v: &Value) -> bool {
    match v {
        Value::Object(m) => m
            .iter()
            .any(|(k, v)| crate::sanitize::is_sensitive_key(k) || contains_sensitive_key(v)),
        Value::Array(a) => a.iter().any(contains_sensitive_key),
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn memory_journal_tracks_intent() {
        let j = InMemoryJournal::default();
        let r = JournalRecord {
            stage: "intent".into(),
            mode: "single".into(),
            actor_id: "a".into(),
            source_url: None,
            run_id: None,
            dataset_id: None,
            run_status: None,
            build_number: None,
            build_id: None,
            build_verification: "pending".into(),
            cap: Some("0.1".into()),
            input_digest: None,
            context: None,
            error: None,
        };
        j.append(&r).unwrap();
        assert_eq!(j.records().len(), 1);
    }
    #[test]
    fn journal_context_drops_credential_key() {
        let j = InMemoryJournal::default();
        let mut r = JournalRecord {
            stage: "intent".into(),
            mode: "single".into(),
            actor_id: "a".into(),
            source_url: None,
            run_id: None,
            dataset_id: None,
            run_status: None,
            build_number: None,
            build_id: None,
            build_verification: "pending".into(),
            cap: None,
            input_digest: None,
            context: Some(serde_json::json!({"session_id":"fake"})),
            error: None,
        };
        assert!(j.append(&r).is_ok());
        assert!(j.records()[0]
            .context
            .as_ref()
            .unwrap()
            .get("session_id")
            .is_none());
        r.context = None;
        assert!(j.append(&r).is_ok());
    }

    #[test]
    fn journal_record_debug_redacts_context_strings() {
        let record = JournalRecord {
            stage: "intent".into(),
            mode: "single".into(),
            actor_id: "a".into(),
            source_url: None,
            run_id: None,
            dataset_id: None,
            run_status: None,
            build_number: None,
            build_id: None,
            build_verification: "pending".into(),
            cap: None,
            input_digest: None,
            context: Some(serde_json::json!({"note":"api_key=JOURNAL_SECRET"})),
            error: None,
        };
        assert!(!format!("{record:?}").contains("JOURNAL_SECRET"));
    }
}
