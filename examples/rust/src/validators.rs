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

/// Validate Profile usernames without normalizing or silently merging caller input.
pub fn validate_usernames(usernames: &[String]) -> Result<Vec<String>> {
    let fail = || {
        Error::new(
            ErrorKind::Input,
            "input_validation",
            "usernames must be non-empty Instagram usernames without @ or whitespace",
        )
    };
    if usernames.is_empty() {
        return Err(fail());
    }
    let mut seen = std::collections::HashSet::new();
    for username in usernames {
        if username.is_empty()
            || username.starts_with('@')
            || username.starts_with('.')
            || username.ends_with('.')
            || username.contains("..")
            || !username
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_'))
            || !seen.insert(username.to_ascii_lowercase())
        {
            return Err(fail());
        }
    }
    Ok(usernames.to_vec())
}

/// Validate the Actor's documented relative date shapes (`YYYY-MM-DD` or `Nd/Nw/Nm/Ny`).
pub fn validate_only_posts_newer_than(value: Option<&str>) -> Result<Option<String>> {
    let Some(value) = value else { return Ok(None) };
    let year = value.get(0..4).and_then(|v| v.parse::<u16>().ok());
    let month = value.get(5..7).and_then(|v| v.parse::<u8>().ok());
    let day = value.get(8..10).and_then(|v| v.parse::<u8>().ok());
    let valid_date = value.len() == 10
        && value.as_bytes()[4] == b'-'
        && value.as_bytes()[7] == b'-'
        && value
            .bytes()
            .enumerate()
            .all(|(i, b)| i == 4 || i == 7 || b.is_ascii_digit())
        && year.is_some_and(|y| y > 0)
        && month.is_some_and(|m| (1..=12).contains(&m))
        && day.is_some_and(|d| {
            let Some(month) = month else { return false };
            let Some(year) = year else { return false };
            let last_day = match month {
                2 if year % 400 == 0 || (year % 4 == 0 && year % 100 != 0) => 29,
                2 => 28,
                4 | 6 | 9 | 11 => 30,
                _ => 31,
            };
            (1..=last_day).contains(&d)
        });
    let relative = value
        .strip_suffix(['d', 'w', 'm', 'y'])
        .is_some_and(|n| !n.is_empty() && n.bytes().all(|b| b.is_ascii_digit()) && n != "0");
    if valid_date || relative {
        Ok(Some(value.to_owned()))
    } else {
        Err(Error::new(
            ErrorKind::Input,
            "input_validation",
            "onlyPostsNewerThan must be YYYY-MM-DD or a positive integer followed by d, w, m, or y",
        ))
    }
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

    #[test]
    fn usernames_are_validated_without_case_insensitive_duplicates() {
        for bad in [
            vec![],
            vec!["@alice"],
            vec!["a b"],
            vec![".alice"],
            vec!["alice."],
            vec!["a..b"],
            vec!["a-b"],
            vec!["Alice", "alice"],
        ] {
            assert!(
                validate_usernames(&bad.into_iter().map(str::to_owned).collect::<Vec<_>>())
                    .is_err()
            );
        }
        assert_eq!(
            validate_usernames(&["alice_1".into(), "b.c".into()]).unwrap(),
            ["alice_1", "b.c"]
        );
    }

    #[test]
    fn usernames_reject_case_only_duplicate_without_silently_merging() {
        let duplicates = vec!["Alice".to_owned(), "alice".to_owned()];
        assert!(
            validate_usernames(&duplicates).is_err(),
            "case-insensitive duplicates must be rejected"
        );
        assert_eq!(
            duplicates.len(),
            2,
            "validation must not mutate or merge caller input"
        );
    }

    #[test]
    fn profile_date_filter_accepts_only_documented_shapes() {
        for value in ["2026-10-24", "1d", "3w", "2m", "1y"] {
            assert!(validate_only_posts_newer_than(Some(value)).is_ok());
        }
        for value in [
            "2026-13-40",
            "2026-02-29",
            "2025-04-31",
            "2026-01-01T00:00:00Z",
            "0d",
            "-1d",
            "y",
        ] {
            assert!(validate_only_posts_newer_than(Some(value)).is_err());
        }
        assert_eq!(
            validate_only_posts_newer_than(Some("2024-02-29"))
                .unwrap()
                .as_deref(),
            Some("2024-02-29")
        );
    }
}
