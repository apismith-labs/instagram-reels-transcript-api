use crate::error::{Error, ErrorKind, Result};
use serde_json::Value;
use std::fmt;

#[derive(Clone)]
pub struct DatasetPage {
    pub items: Vec<Value>,
    pub complete: bool,
    pub limit: usize,
}

impl fmt::Debug for DatasetPage {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let items: Vec<Value> = self
            .items
            .iter()
            .map(crate::sanitize::sanitize_value)
            .collect();
        f.debug_struct("DatasetPage")
            .field("items", &items)
            .field("complete", &self.complete)
            .field("limit", &self.limit)
            .finish()
    }
}

pub fn parse_dataset(body: &str, limit: usize) -> Result<DatasetPage> {
    let parsed: Value = serde_json::from_str(body).map_err(|_| {
        Error::new(
            ErrorKind::Protocol,
            "dataset_parse",
            "Dataset response is not valid JSON",
        )
    })?;
    let items = parsed
        .as_array()
        .ok_or_else(|| {
            Error::new(
                ErrorKind::Protocol,
                "dataset_parse",
                "Dataset response must be a bare JSON array",
            )
        })?
        .clone();
    let complete = items.len() < limit;
    Ok(DatasetPage {
        items,
        complete,
        limit,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepts_bare_array() {
        let p = parse_dataset("[{\"text\":\"x\"}]", 10).unwrap();
        assert_eq!(p.items.len(), 1);
        assert!(p.complete);
    }
    #[test]
    fn rejects_wrapped_object() {
        assert_eq!(
            parse_dataset("{\"data\":[]}", 10).unwrap_err().kind,
            ErrorKind::Protocol
        );
    }
    #[test]
    fn reaching_limit_means_incomplete() {
        let p = parse_dataset("[1,2]", 2).unwrap();
        assert!(!p.complete);
    }
    #[test]
    fn accepts_empty_array() {
        assert!(parse_dataset("[]", 10).unwrap().complete);
    }
    #[test]
    fn rejects_bad_json() {
        assert!(parse_dataset("not json", 10).is_err());
    }

    #[test]
    fn debug_redacts_untrusted_dataset_items() {
        let page = parse_dataset(r#"[{"text":"token=DATASET_SECRET"}]"#, 10).unwrap();
        assert!(!format!("{page:?}").contains("DATASET_SECRET"));
    }
}
