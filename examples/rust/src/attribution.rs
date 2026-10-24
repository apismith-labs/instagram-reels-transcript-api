use crate::{status::AttributionVerification, validators::canonical_video_identity};
use serde_json::Value;
use std::fmt;

#[derive(Clone)]
pub struct Attribution {
    pub matched: Vec<Value>,
    pub extras: Vec<Value>,
    pub verification: AttributionVerification,
}

impl fmt::Debug for Attribution {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let matched: Vec<Value> = self
            .matched
            .iter()
            .map(crate::sanitize::sanitize_value)
            .collect();
        let extras: Vec<Value> = self
            .extras
            .iter()
            .map(crate::sanitize::sanitize_value)
            .collect();
        f.debug_struct("Attribution")
            .field("matched", &matched)
            .field("extras", &extras)
            .field("verification", &self.verification)
            .finish()
    }
}

pub fn attribute_single(requested_url: &str, items: &[Value]) -> Attribution {
    let requested = canonical_video_identity(requested_url);
    let mut matched = Vec::new();
    let mut extras = Vec::new();
    for item in items {
        let output = item
            .get("url")
            .and_then(Value::as_str)
            .and_then(canonical_video_identity);
        if requested.is_some() && output == requested {
            matched.push(item.clone())
        } else {
            extras.push(item.clone())
        }
    }
    let verification = match (requested, matched.len()) {
        (Some(_), 1) => AttributionVerification::Verified,
        (Some(_), n) if n > 1 => AttributionVerification::Mismatch,
        _ => AttributionVerification::Unknown,
    };
    Attribution {
        matched,
        extras,
        verification,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn matches_url_identity_not_position() {
        let items = vec![
            serde_json::json!({"url":"https://instagram.com/reel/OTHER","text":"wrong"}),
            serde_json::json!({"url":"https://instagram.com/p/ABC","text":"right"}),
        ];
        let a = attribute_single("https://www.instagram.com/reel/ABC/", &items);
        assert_eq!(a.verification, AttributionVerification::Verified);
        assert_eq!(a.matched[0]["text"], "right");
        assert_eq!(a.extras.len(), 1);
    }
    #[test]
    fn mismatch_never_matches() {
        let a = attribute_single(
            "https://instagram.com/reel/abc",
            &[serde_json::json!({"url":"https://instagram.com/reel/xyz"})],
        );
        assert_eq!(a.verification, AttributionVerification::Unknown);
        assert!(a.matched.is_empty());
    }
    #[test]
    fn duplicate_match_is_ambiguous() {
        let x = serde_json::json!({"url":"https://instagram.com/reel/abc"});
        let a = attribute_single("https://instagram.com/reel/abc", &[x.clone(), x]);
        assert_eq!(a.verification, AttributionVerification::Mismatch);
    }
    #[test]
    fn missing_url_is_unknown() {
        assert_eq!(
            attribute_single(
                "https://instagram.com/reel/a",
                &[serde_json::json!({"text":"x"})]
            )
            .verification,
            AttributionVerification::Unknown
        );
    }

    #[test]
    fn debug_redacts_untrusted_attributed_items() {
        let item = serde_json::json!({
            "url":"https://instagram.com/reel/abc",
            "text":"password=ATTRIBUTION_SECRET"
        });
        let debug = format!(
            "{:?}",
            attribute_single("https://instagram.com/reel/abc", &[item])
        );
        assert!(!debug.contains("ATTRIBUTION_SECRET"));
    }
}
