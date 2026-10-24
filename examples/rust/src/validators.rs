use crate::error::{Error, ErrorKind, Result};
use reqwest::Url;

pub fn validate_video_url(input: &str) -> Result<String> {
    let fail = || {
        Error::new(
            ErrorKind::Input,
            "input_validation",
            "URL must be a bare HTTPS Instagram reel/post URL",
        )
    };
    if input.trim() != input
        || input.is_empty()
        || input.chars().any(|c| matches!(c, '<' | '>' | '\n' | '\r'))
    {
        return Err(fail());
    }
    let url = Url::parse(input).map_err(|_| fail())?;
    if url.scheme() != "https"
        || !matches!(url.host_str(), Some("instagram.com" | "www.instagram.com"))
        || url.username() != ""
        || url.password().is_some()
        || url.port().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(fail());
    }
    // URL parsing normalizes a default :443 port away; reject explicit ports from raw authority.
    let authority = input
        .split_once("//")
        .map(|(_, rest)| rest.split('/').next().unwrap_or_default())
        .unwrap_or_default();
    if authority.contains('@') || authority.contains(':') {
        return Err(fail());
    }
    let path = url.path();
    let parts: Vec<&str> = path.split('/').collect();
    if parts.len() != 3 && !(parts.len() == 4 && parts[3].is_empty()) {
        return Err(fail());
    }
    if !matches!(parts[1], "reel" | "reels" | "p")
        || parts[2].is_empty()
        || !parts[2]
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
    {
        return Err(fail());
    }
    Ok(input.to_owned())
}

pub fn canonical_video_identity(input: &str) -> Option<String> {
    let valid = validate_video_url(input).ok()?;
    let url = Url::parse(&valid).ok()?;
    let code = url.path().trim_end_matches('/').rsplit('/').next()?;
    Some(code.to_owned())
}

pub fn validate_charge_cap(raw: Option<&str>) -> Result<String> {
    let raw = raw.ok_or_else(|| {
        Error::new(
            ErrorKind::Configuration,
            "config",
            "a positive maxTotalChargeUsd is required",
        )
    })?;
    let parts: Vec<&str> = raw.split('.').collect();
    let valid_syntax = parts.len() <= 2
        && parts
            .iter()
            .all(|part| part.bytes().all(|b| b.is_ascii_digit()))
        && parts.iter().any(|part| !part.is_empty())
        && raw.bytes().any(|b| b.is_ascii_digit())
        && !raw.is_empty();
    let is_positive = raw.bytes().any(|b| b.is_ascii_digit() && b != b'0');
    if !valid_syntax || !is_positive {
        return Err(Error::new(
            ErrorKind::Configuration,
            "config",
            "maxTotalChargeUsd must be a positive decimal",
        ));
    }
    Ok(raw.to_owned())
}

pub fn encode_actor_id(actor_id: &str) -> String {
    let normalized = actor_id.replace('/', "~");
    let mut encoded = String::new();
    for byte in normalized.bytes() {
        if byte.is_ascii_alphanumeric() || b"-_.~".contains(&byte) {
            encoded.push(byte as char);
        } else {
            encoded.push_str(&format!("%{byte:02X}"));
        }
    }
    encoded
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepts_reel_reels_and_post() {
        for p in ["reel", "reels", "p"] {
            assert!(validate_video_url(&format!("https://www.instagram.com/{p}/Ab_9-/")).is_ok());
        }
    }
    #[test]
    fn rejects_non_https_host_and_markdown() {
        for s in [
            "http://instagram.com/reel/a",
            "https://evil.com/reel/a",
            "[x](https://instagram.com/reel/a)",
        ] {
            assert!(validate_video_url(s).is_err());
        }
    }
    #[test]
    fn rejects_query_fragment_userinfo_and_explicit_port() {
        for s in [
            "https://instagram.com/reel/a?q=1",
            "https://instagram.com/reel/a#x",
            "https://u@instagram.com/reel/a",
            "https://instagram.com:443/reel/a",
        ] {
            assert!(validate_video_url(s).is_err());
        }
    }
    #[test]
    fn rejects_extra_path_and_invalid_code() {
        for s in [
            "https://instagram.com/reel/a/b",
            "https://instagram.com/reel/a%2Fb",
            "https://instagram.com/story/a",
        ] {
            assert!(validate_video_url(s).is_err());
        }
    }
    #[test]
    fn shortcode_identity_is_case_sensitive() {
        assert_ne!(
            canonical_video_identity("https://instagram.com/reel/AbC"),
            canonical_video_identity("https://instagram.com/reel/abc")
        );
    }
    #[test]
    fn rejects_invalid_caps() {
        for cap in [
            None,
            Some("0"),
            Some("-1"),
            Some("nan"),
            Some("1.2.3"),
            Some(""),
        ] {
            assert!(validate_charge_cap(cap).is_err());
        }
    }
    #[test]
    fn accepts_positive_cap() {
        assert_eq!(validate_charge_cap(Some("0.10")).unwrap(), "0.10");
    }
    #[test]
    fn accepts_tiny_positive_decimal_without_float_rounding() {
        assert_eq!(
            validate_charge_cap(Some("0.00000000000000000001")).unwrap(),
            "0.00000000000000000001"
        );
    }
    #[test]
    fn actor_id_is_path_safe() {
        assert_eq!(
            encode_actor_id("apple_yang/instagram-transcripts-scraper"),
            "apple_yang~instagram-transcripts-scraper"
        );
    }
}
