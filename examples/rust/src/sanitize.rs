use serde_json::{Map, Value};

const SENSITIVE_SUFFIXES: [&str; 7] = [
    "token",
    "sessionid",
    "password",
    "secret",
    "cookie",
    "authorization",
    "apikey",
];

const SENSITIVE_ALIASES: [&str; 4] = ["bearer", "credential", "passwd", "pwd"];
const SENSITIVE_EXACT: [&str; 2] = ["privatekey", "secretkey"];

pub fn is_sensitive_key(key: &str) -> bool {
    let normalized: String = key
        .chars()
        .filter(|c| *c != '_' && *c != '-')
        .flat_map(char::to_lowercase)
        .collect();
    SENSITIVE_ALIASES.contains(&normalized.as_str())
        || SENSITIVE_EXACT.contains(&normalized.as_str())
        || SENSITIVE_SUFFIXES
            .iter()
            .any(|suffix| normalized.ends_with(suffix))
}

pub fn redact_text(input: &str) -> String {
    let chars: Vec<char> = input.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        if word_at(&chars, i, "bearer") {
            let mut value_start = i + 6;
            while value_start < chars.len() && chars[value_start].is_whitespace() {
                value_start += 1;
            }
            let (quote, end) = secret_value_end(&chars, value_start);
            if end > value_start {
                out.extend(chars[i..value_start].iter());
                if let Some(q) = quote {
                    out.push(q);
                }
                out.push_str("[REDACTED]");
                if let Some(q) = quote {
                    if end > value_start + 1 && chars[end - 1] == q {
                        out.push(q);
                    }
                }
                i = end;
                continue;
            }
        }
        let mut found = false;
        for key in [
            "sessionid",
            "authorization",
            "password",
            "cookie",
            "api-key",
            "api_key",
            "apikey",
            "token",
        ] {
            if word_at(&chars, i, key) {
                let mut j = i + key.chars().count();
                while j < chars.len() && chars[j].is_whitespace() {
                    j += 1;
                }
                if j < chars.len() && matches!(chars[j], '"' | '\'') {
                    let key_quote = chars[j];
                    if chars[j + 1..].contains(&key_quote) {
                        j += 1;
                        while j < chars.len() && chars[j].is_whitespace() {
                            j += 1;
                        }
                    }
                }
                if j < chars.len() && (chars[j] == '=' || chars[j] == ':') {
                    j += 1;
                    while j < chars.len() && chars[j].is_whitespace() {
                        j += 1;
                    }
                    let mut secret_start = j;
                    let mut bearer_prefix_end = None;
                    if word_at(&chars, secret_start, "bearer") {
                        secret_start += 6;
                        while secret_start < chars.len() && chars[secret_start].is_whitespace() {
                            secret_start += 1;
                        }
                        bearer_prefix_end = Some(secret_start);
                    }
                    let (quote, end) = secret_value_end(&chars, secret_start);
                    if end > j {
                        let value_prefix_end = bearer_prefix_end.unwrap_or(secret_start);
                        out.extend(chars[i..value_prefix_end].iter());
                        if let Some(q) = quote {
                            out.push(q);
                        }
                        out.push_str("[REDACTED]");
                        if let Some(q) = quote {
                            if end > secret_start + 1 && chars[end - 1] == q {
                                out.push(q);
                            }
                        }
                        i = end;
                        found = true;
                        break;
                    }
                }
            }
        }
        if !found {
            out.push(chars[i]);
            i += 1;
        }
    }
    out
}

fn word_at(chars: &[char], i: usize, word: &str) -> bool {
    let w: Vec<char> = word.chars().collect();
    if i + w.len() > chars.len() {
        return false;
    }
    // Match recognizable credential keys after prefixes such as `access_`, `x-`,
    // or CJK prose. The right boundary below still prevents matching `tokenizer`.
    let is_boundary = |c: char| !(c.is_alphanumeric() || c == '_' || c == '-');
    if i + w.len() < chars.len() && !is_boundary(chars[i + w.len()]) {
        return false;
    }
    chars[i..i + w.len()]
        .iter()
        .zip(w.iter())
        .all(|(a, b)| a.to_ascii_lowercase() == *b)
}

fn secret_value_end(chars: &[char], start: usize) -> (Option<char>, usize) {
    if start >= chars.len() {
        return (None, start);
    }
    if matches!(chars[start], '"' | '\'') {
        let quote = chars[start];
        if let Some(offset) = chars[start + 1..].iter().position(|c| *c == quote) {
            return (Some(quote), start + offset + 2);
        }
        return (Some(quote), token_end(chars, start + 1));
    }
    (None, token_end(chars, start))
}

fn token_end(chars: &[char], mut i: usize) -> usize {
    while i < chars.len()
        && !chars[i].is_whitespace()
        && !matches!(chars[i], ',' | ';' | '&' | ']' | '}' | ')')
    {
        i += 1;
    }
    while i > 0 && matches!(chars[i - 1], '.' | ':' | '!') {
        i -= 1;
    }
    i
}

pub fn diagnostic(input: &str) -> String {
    let normalized = input
        .replace("\r\n", "\n")
        .replace('\r', "\n")
        .replace('\n', " ");
    let redacted = redact_text(&normalized);
    redacted.chars().take(300).collect()
}

pub fn sanitize_value(value: &Value) -> Value {
    match value {
        Value::String(s) => Value::String(redact_text(s)),
        Value::Array(a) => Value::Array(a.iter().map(sanitize_value).collect()),
        Value::Object(m) => {
            let mut clean = Map::new();
            for (k, v) in m {
                if !is_sensitive_key(k) {
                    clean.insert(k.clone(), sanitize_value(v));
                }
            }
            Value::Object(clean)
        }
        _ => value.clone(),
    }
}

pub(crate) fn sanitize_debug_payload(input: &str) -> String {
    match serde_json::from_str::<Value>(input) {
        Ok(value) => {
            serde_json::to_string(&sanitize_value(&value)).unwrap_or_else(|_| redact_text(input))
        }
        Err(_) => redact_text(input),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn key_variants_are_removed() {
        for k in [
            "token",
            "sessionId",
            "session_id",
            "session-id",
            "apiKey",
            "api_key",
            "api-key",
            "Authorization",
            "PASSWORD",
            "id_token",
            "auth_token",
            "session_token",
            "access_token",
            "refresh_token",
            "user_password",
            "db_password",
            "x-api-key",
            "session-token",
            "X-Cookie",
            "client_secret",
            "api_token",
            "x-auth-token",
            "proxy-authorization",
            "set-cookie",
            "private_key",
            "secret_key",
            "passwd",
            "pwd",
            "bearer",
            "credential",
        ] {
            assert!(is_sensitive_key(k));
        }
        for k in [
            "token_count",
            "password_policy",
            "tokenizer",
            "access_token_count",
            "tokens",
            "token_budget",
            "password_hint",
            "access_token_ttl",
            "cookie_notice",
            "authorization_level",
            "secret_santa",
        ] {
            assert!(!is_sensitive_key(k), "business field removed: {k}");
        }
    }

    #[test]
    fn nested_sensitive_keys_are_removed_but_similar_business_keys_remain() {
        let value = serde_json::json!({
            "id_token": "KEY_SECRET_ID",
            "nested": [
                {"auth_token": "KEY_SECRET_AUTH"},
                [
                    {"session_token": "KEY_SECRET_SESSION"},
                    {"user_password": "KEY_SECRET_USER_PASSWORD"},
                    {"db_password": "KEY_SECRET_DB_PASSWORD"},
                    {"x-api-key": "KEY_SECRET_API_KEY"},
                    {"session-token": "KEY_SECRET_SESSION_DASH"},
                    {"X-Cookie": "KEY_SECRET_COOKIE"},
                    {"access_token": "KEY_SECRET_ACCESS", "refresh_token": "KEY_SECRET_REFRESH"}
                ]
            ],
            "token_count": 12,
            "password_policy": "minimum length",
            "tokenizer": "whitespace"
        });
        let clean = sanitize_value(&value);
        let rendered = clean.to_string();
        for secret in [
            "KEY_SECRET_ID",
            "KEY_SECRET_AUTH",
            "KEY_SECRET_SESSION",
            "KEY_SECRET_USER_PASSWORD",
            "KEY_SECRET_DB_PASSWORD",
            "KEY_SECRET_API_KEY",
            "KEY_SECRET_SESSION_DASH",
            "KEY_SECRET_COOKIE",
            "KEY_SECRET_ACCESS",
            "KEY_SECRET_REFRESH",
        ] {
            assert!(
                !rendered.contains(secret),
                "bare keyed secret persisted: {secret}"
            );
        }
        assert!(clean.get("id_token").is_none());
        assert_eq!(clean["nested"][0].get("auth_token"), None);
        assert_eq!(clean["nested"][1][0].get("session_token"), None);
        assert_eq!(clean["nested"][1][7].get("access_token"), None);
        assert_eq!(clean["token_count"], 12);
        assert_eq!(clean["password_policy"], "minimum length");
        assert_eq!(clean["tokenizer"], "whitespace");
    }
    #[test]
    fn bearer_is_redacted() {
        assert_eq!(
            redact_text("oops Bearer abc.def:xy happened"),
            "oops Bearer [REDACTED] happened"
        );
    }

    #[test]
    fn quoted_and_authorization_values_are_fully_redacted() {
        for (input, secret) in [
            ("token=SECRET", "SECRET"),
            ("token=\"SECRET\"", "SECRET"),
            ("password='SECRET'", "SECRET"),
            ("api_key: SECRET", "SECRET"),
            ("Authorization: Bearer SECRET", "SECRET"),
            ("Bearer SECRET", "SECRET"),
            ("Bearer \"SECRET\"", "SECRET"),
            ("upstream said {\"token\":\"SECRET\"}", "SECRET"),
            ("upstream error: {\"sessionid\":\"SECRET\"}", "SECRET"),
        ] {
            let redacted = redact_text(input);
            assert!(
                !redacted.contains(secret),
                "secret persisted in {redacted:?}"
            );
            assert!(
                redacted.contains("[REDACTED]"),
                "missing marker in {redacted:?}"
            );
        }
        assert_eq!(
            redact_text("normal transcript stays readable"),
            "normal transcript stays readable"
        );
    }

    #[test]
    fn credential_suffixes_redact_but_longer_words_stay_intact() {
        for (input, secret) in [
            ("access_token=SECRET_A", "SECRET_A"),
            ("refresh_token=SECRET_B", "SECRET_B"),
            ("mytoken=SECRET_C", "SECRET_C"),
            ("查询参数token=SECRET_D", "SECRET_D"),
            ("用户password=SECRET_E", "SECRET_E"),
        ] {
            let redacted = redact_text(input);
            assert!(!redacted.contains(secret), "secret persisted: {redacted}");
        }
        assert_eq!(
            redact_text("tokenizer stays intact"),
            "tokenizer stays intact"
        );
        let unicode = "普通中文与 Unicode 🙂 transcript ".repeat(30);
        assert_eq!(redact_text(&unicode), unicode);
    }
    #[test]
    fn assignment_forms_are_redacted() {
        for s in [
            "token=abc",
            "sessionid: xyz",
            "api_key=abc",
            "api-key:abc",
            "password = secret",
            "cookie: secret",
            "authorization=Basic abc",
        ] {
            assert!(redact_text(s).contains("[REDACTED]"), "{s}");
        }
    }
    #[test]
    fn normal_text_is_retained() {
        assert_eq!(
            redact_text("crawed empty and readable"),
            "crawed empty and readable"
        );
    }
    #[test]
    fn diagnostics_normalize_and_truncate() {
        let s = diagnostic(&format!("a\r\nb{}", "x".repeat(400)));
        assert!(!s.contains('\n'));
        assert_eq!(s.chars().count(), 300);
    }
    #[test]
    fn nested_values_preserve_shape_and_remove_secret_keys() {
        let v = serde_json::json!({"n":3,"flag":true,"nested":[{"token":"fake","text":"hi apiKey=secret"}]});
        let s = sanitize_value(&v);
        assert_eq!(s["n"], 3);
        assert_eq!(s["flag"], true);
        assert!(s["nested"][0].get("token").is_none());
        assert_eq!(s["nested"][0]["text"], "hi apiKey=[REDACTED]");
    }
    #[test]
    fn long_nonsecret_text_not_truncated() {
        let s = "z".repeat(1000);
        assert_eq!(redact_text(&s).len(), 1000);
    }
}
