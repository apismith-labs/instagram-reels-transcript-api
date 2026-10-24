use crate::{
    error::{Error, ErrorKind, Result},
    sanitize::sanitize_value,
    status::TranscriptResult,
};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
    time::{SystemTime, UNIX_EPOCH},
};

static SEQUENCE: AtomicU64 = AtomicU64::new(0);

pub fn write_result(output_dir: &Path, result: &TranscriptResult) -> Result<PathBuf> {
    fs::create_dir_all(output_dir).map_err(|_| {
        Error::new(
            ErrorKind::Output,
            "output",
            "could not create output directory",
        )
    })?;
    let json = serde_json::to_vec_pretty(&sanitize_value(
        &serde_json::to_value(result)
            .map_err(|_| Error::new(ErrorKind::Output, "output", "could not serialize result"))?,
    ))
    .map_err(|_| {
        Error::new(
            ErrorKind::Output,
            "output",
            "could not serialize sanitized result",
        )
    })?;
    for _ in 0..100 {
        let n = SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        let base = format!("transcript-{stamp}-{}-{n}.json", std::process::id());
        let final_path = output_dir.join(base);
        let temp_path = output_dir.join(format!(
            ".{}.tmp",
            final_path.file_name().unwrap().to_string_lossy()
        ));
        let mut opts = OpenOptions::new();
        opts.write(true).create_new(true);
        set_private_mode(&mut opts);
        let mut file = match opts.open(&temp_path) {
            Ok(f) => f,
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(_) => {
                return Err(Error::new(
                    ErrorKind::Output,
                    "output",
                    "could not create private temporary result file",
                ))
            }
        };
        if file
            .write_all(&json)
            .and_then(|_| file.write_all(b"\n"))
            .and_then(|_| file.sync_all())
            .is_err()
        {
            let _ = fs::remove_file(&temp_path);
            return Err(Error::new(
                ErrorKind::Output,
                "output",
                "could not durably write result",
            ));
        }
        // A same-filesystem hard-link publishes the complete file atomically without replacing an existing name.
        if let Err(e) = fs::hard_link(&temp_path, &final_path) {
            let _ = fs::remove_file(&temp_path);
            if e.kind() == std::io::ErrorKind::AlreadyExists {
                continue;
            }
            return Err(Error::new(
                ErrorKind::Output,
                "output",
                "could not atomically publish result",
            ));
        }
        fs::remove_file(&temp_path).map_err(|_| {
            Error::new(
                ErrorKind::Output,
                "output",
                "result published but temporary link cleanup failed",
            )
        })?;
        sync_directory(output_dir)?;
        return Ok(final_path);
    }
    Err(Error::new(
        ErrorKind::Output,
        "output",
        "could not allocate a unique result filename",
    ))
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<()> {
    let dir = OpenOptions::new().read(true).open(path).map_err(|_| {
        Error::new(
            ErrorKind::Output,
            "output",
            "could not open output directory for sync",
        )
    })?;
    dir.sync_all().map_err(|_| {
        Error::new(
            ErrorKind::Output,
            "output",
            "could not sync output directory",
        )
    })
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<()> {
    Ok(())
}

#[cfg(unix)]
fn set_private_mode(opts: &mut OpenOptions) {
    use std::os::unix::fs::OpenOptionsExt;
    opts.mode(0o600);
}
#[cfg(not(unix))]
fn set_private_mode(_opts: &mut OpenOptions) {}

pub fn ensure_output_directory(path: &Path) -> Result<()> {
    if !Path::new(path).is_dir() && path.exists() {
        return Err(Error::new(
            ErrorKind::Output,
            "output",
            "output path is not a directory",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::journal::{InMemoryJournal, Journal, JournalRecord};
    use crate::status::{AttributionVerification, BuildVerification, Status};
    use serde_json::json;
    #[test]
    fn output_is_private_unique_and_sanitized() {
        let d = tempfile::tempdir().unwrap();
        let r = TranscriptResult {
            status: Status::Success,
            run_id: Some("r".into()),
            dataset_id: Some("d".into()),
            source_url: "https://instagram.com/reel/abc".into(),
            text: Some("caption".into()),
            segments: vec![json!({"start":1,"text":"ok"})],
            raw_items: vec![json!({"token":"fake-secret","errMsg":"apiKey=private"})],
            error: None,
            stage: Some("done".into()),
            build_number: Some("0.0.50".into()),
            build_id: Some("id".into()),
            build_verification: BuildVerification::Verified,
            attribution_verification: AttributionVerification::Verified,
            dataset_complete: true,
        };
        let a = write_result(d.path(), &r).unwrap();
        let b = write_result(d.path(), &r).unwrap();
        assert_ne!(a, b);
        let saved = fs::read_to_string(&a).unwrap();
        assert!(!saved.contains("fake-secret"));
        assert!(saved.contains("[REDACTED]"));
        let direct = serde_json::to_string(&r).unwrap();
        assert!(!direct.contains("fake-secret"));
        assert!(direct.contains("[REDACTED]"));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(fs::metadata(a).unwrap().permissions().mode() & 0o777, 0o600);
        }
    }

    #[test]
    fn persisted_text_secrets_are_absent_and_business_text_is_preserved() {
        let d = tempfile::tempdir().unwrap();
        let long_tail = "ordinary-transcript-content ".repeat(80);
        let transcript = format!(
            "token=SYNTHETIC_SECRET_TOKEN token=\"SYNTHETIC_SECRET_TOKEN_QUOTED\" password='SYNTHETIC_SECRET_PASSWORD' api_key: SYNTHETIC_SECRET_API Authorization: Bearer SYNTHETIC_SECRET_AUTH Bearer SYNTHETIC_SECRET_BEARER Bearer \"SYNTHETIC_SECRET_BEARER_QUOTED\" {{\"token\":\"SYNTHETIC_SECRET_JSON\"}} upstream error: {{\"sessionid\":\"SYNTHETIC_SECRET_SESSION\"}} opening words password=\"SYNTHETIC_SECRET_PASSWORD_2\" middle {{\"token\":\"SYNTHETIC_SECRET_JSON_2\"}} closing words {long_tail}"
        );
        let result = TranscriptResult {
            status: Status::Success,
            run_id: Some("run-1".into()),
            dataset_id: Some("dataset-1".into()),
            source_url: "https://www.instagram.com/reel/abc/".into(),
            text: Some(transcript),
            segments: vec![json!({"text":"api_key: SYNTHETIC_SECRET_SEGMENT"})],
            raw_items: vec![json!({
                "errMsg":"Authorization: Bearer SYNTHETIC_SECRET_AUTH",
                "caption":"api_key='SYNTHETIC_SECRET_RAW'"
            })],
            error: Some("password='SYNTHETIC_SECRET_ERROR'".into()),
            stage: Some("done".into()),
            build_number: Some("0.0.50".into()),
            build_id: Some("build-id".into()),
            build_verification: BuildVerification::Verified,
            attribution_verification: AttributionVerification::Verified,
            dataset_complete: true,
        };
        let path = write_result(d.path(), &result).unwrap();
        let saved = fs::read_to_string(path).unwrap();
        assert!(!saved.contains("SYNTHETIC_SECRET"), "secret persisted");
        let parsed: serde_json::Value = serde_json::from_str(&saved).expect("saved JSON parses");
        let saved_text = parsed["text"]
            .as_str()
            .expect("transcript remains a string");
        assert!(saved_text.contains("opening words"));
        assert!(saved_text.contains("middle"));
        assert!(saved_text.contains("closing words"));
        assert!(saved_text.ends_with(&long_tail));
        assert!(
            saved_text.len() > 1200,
            "non-sensitive transcript was truncated"
        );
        assert!(parsed["segments"][0]["text"]
            .as_str()
            .unwrap()
            .contains("[REDACTED]"));
        assert!(parsed["rawItems"][0]["errMsg"]
            .as_str()
            .unwrap()
            .contains("[REDACTED]"));
    }

    #[test]
    fn persisted_prefixed_credentials_are_absent_and_json_stays_intact() {
        let d = tempfile::tempdir().unwrap();
        let secrets = [
            "SECRET_A", "SECRET_B", "SECRET_C", "SECRET_D", "SECRET_E", "SECRET_F", "SECRET_G",
            "SECRET_H", "SECRET_I", "SECRET_J", "SECRET_K", "SECRET_L",
        ];
        let result = TranscriptResult {
            status: Status::Success,
            run_id: Some("run-r2".into()),
            dataset_id: Some("dataset-r2".into()),
            source_url: "https://www.instagram.com/reel/abc/".into(),
            text: Some(format!(
                "ordinary tokenizer remains; access_token={} refresh_token={} id_token={} auth_token={}",
                secrets[0], secrets[1], secrets[2], secrets[3]
            )),
            segments: vec![json!({"text":format!("user_password={} db_password={}", secrets[4], secrets[5])})],
            raw_items: vec![json!({
                "errMsg":format!("session_token={} x-api-key: {} session-token={}", secrets[6], secrets[7], secrets[8]),
                "caption":format!("X-Cookie: {} and ordinary caption", secrets[9]),
                "shortCode":"AbC123",
                "count":42,
                "active":true,
                "nothing":null
            })],
            error: Some(format!(
                "查询参数token={}；用户password={}",
                secrets[10], secrets[11]
            )),
            stage: Some("dataset_classification".into()),
            build_number: Some("0.0.50".into()),
            build_id: Some("synthetic-build".into()),
            build_verification: BuildVerification::Verified,
            attribution_verification: AttributionVerification::Verified,
            dataset_complete: true,
        };

        let path = write_result(d.path(), &result).unwrap();
        let saved = fs::read_to_string(path).unwrap();
        for secret in secrets {
            assert!(!saved.contains(secret), "secret persisted: {secret}");
        }
        let parsed: serde_json::Value = serde_json::from_str(&saved).expect("saved JSON parses");
        assert!(parsed["text"]
            .as_str()
            .unwrap()
            .contains("ordinary tokenizer remains"));
        assert!(parsed["segments"][0]["text"]
            .as_str()
            .unwrap()
            .contains("[REDACTED]"));
        assert!(parsed["rawItems"][0]["caption"]
            .as_str()
            .unwrap()
            .contains("ordinary caption"));
        assert_eq!(parsed["rawItems"][0]["shortCode"], "AbC123");
        assert_eq!(parsed["rawItems"][0]["count"], 42);
        assert_eq!(parsed["rawItems"][0]["active"], true);
        assert!(parsed["rawItems"][0]["nothing"].is_null());
        assert!(parsed["error"].as_str().unwrap().contains("查询参数token="));
        assert!(parsed["error"].as_str().unwrap().contains("[REDACTED]"));
    }

    #[test]
    fn persisted_nested_sensitive_keys_are_removed_without_damaging_business_fields() {
        let d = tempfile::tempdir().unwrap();
        let secrets = [
            "BARE_ID_TOKEN_SECRET",
            "BARE_AUTH_TOKEN_SECRET",
            "BARE_SESSION_TOKEN_SECRET",
            "BARE_ACCESS_TOKEN_SECRET",
            "BARE_REFRESH_TOKEN_SECRET",
            "BARE_USER_PASSWORD_SECRET",
            "BARE_DB_PASSWORD_SECRET",
            "BARE_X_API_KEY_SECRET",
            "BARE_SESSION_DASH_TOKEN_SECRET",
            "BARE_X_COOKIE_SECRET",
        ];
        let result = TranscriptResult {
            status: Status::Success,
            run_id: Some("run-key-test".into()),
            dataset_id: Some("dataset-key-test".into()),
            source_url: "https://www.instagram.com/reel/AbC123/".into(),
            text: Some("business transcript remains exactly intact".into()),
            segments: vec![json!({"start": 1.25, "text": "segment remains intact"})],
            raw_items: vec![json!({
                "id_token": secrets[0],
                "nested": [
                    {"auth_token": secrets[1]},
                    [
                        {"session_token": secrets[2]},
                        {"access_token": secrets[3]},
                        {"refresh_token": secrets[4]},
                        {"user_password": secrets[5]},
                        {"db_password": secrets[6]},
                        {"x-api-key": secrets[7]},
                        {"session-token": secrets[8]},
                        {"X-Cookie": secrets[9]}
                    ]
                ],
                "token_count": 17,
                "password_policy": "minimum length",
                "tokenizer": "whitespace",
                "shortCode": "AbC123",
                "count": 3,
                "active": true
            })],
            error: None,
            stage: Some("dataset_classification".into()),
            build_number: Some("0.0.50".into()),
            build_id: Some("synthetic-build".into()),
            build_verification: BuildVerification::Verified,
            attribution_verification: AttributionVerification::Verified,
            dataset_complete: true,
        };

        let path = write_result(d.path(), &result).unwrap();
        let saved = fs::read_to_string(path).unwrap();
        for secret in secrets {
            assert!(!saved.contains(secret), "secret persisted: {secret}");
        }
        let parsed: serde_json::Value = serde_json::from_str(&saved).expect("saved JSON parses");
        let raw = &parsed["rawItems"][0];
        assert!(raw.get("id_token").is_none());
        assert!(raw["nested"][0].get("auth_token").is_none());
        let nested = raw["nested"][1]
            .as_array()
            .expect("nested sensitive-key array remains an array");
        assert_eq!(nested.len(), 8, "sanitization preserves array shape");
        for (index, key) in [
            "session_token",
            "access_token",
            "refresh_token",
            "user_password",
            "db_password",
            "x-api-key",
            "session-token",
            "X-Cookie",
        ]
        .iter()
        .enumerate()
        {
            assert!(
                nested[index]
                    .as_object()
                    .expect("nested entry is an object")
                    .is_empty(),
                "sensitive field {key} was not removed"
            );
        }
        assert_eq!(raw["token_count"], 17);
        assert_eq!(raw["password_policy"], "minimum length");
        assert_eq!(raw["tokenizer"], "whitespace");
        assert_eq!(raw["shortCode"], "AbC123");
        assert_eq!(raw["count"], 3);
        assert_eq!(raw["active"], true);
        assert_eq!(parsed["text"], "business transcript remains exactly intact");
        assert_eq!(parsed["segments"][0]["start"], 1.25);
        assert_eq!(parsed["segments"][0]["text"], "segment remains intact");
    }

    #[test]
    fn persisted_common_credential_keys_are_removed_at_output_boundaries() {
        let d = tempfile::tempdir().unwrap();
        let secrets = [
            "Q7M2V9K4A1",
            "R8N3W5L0B2",
            "S9P4X6M1C3",
            "T0Q5Y7N2D4",
            "U1R6Z8P3E5",
            "V2S7A9Q4F6",
            "W3T8B0R5G7",
            "X4U9C1S6H8",
            "Y5V0D2T7J9",
            "Z6W1E3U8K0",
            "A7X2F4V9L1",
        ];
        let top_level = crate::sanitize::sanitize_value(&json!({
            "client_secret": secrets[0],
            "token_count": 12,
            "password_policy": "minimum length"
        }));
        let top_level_json = serde_json::to_string(&top_level).unwrap();
        assert!(
            !top_level_json.contains(secrets[0]),
            "top-level secret persisted"
        );
        assert!(top_level.get("client_secret").is_none());
        assert_eq!(top_level["token_count"], 12);
        assert_eq!(top_level["password_policy"], "minimum length");

        let raw = json!({
            "client_secret": secrets[0],
            "nested": [
                {"api_token": secrets[1]},
                [
                    {"x-auth-token": secrets[2]},
                    {"proxy-authorization": secrets[3]},
                    {"set-cookie": secrets[4]},
                    {"private_key": secrets[5]},
                    {"secret_key": secrets[6]},
                    {"passwd": secrets[7]},
                    {"pwd": secrets[8]},
                    {"bearer": secrets[9]},
                    {"credential": secrets[10]}
                ]
            ],
            "token_count": 12,
            "password_policy": "minimum length",
            "tokenizer": "whitespace",
            "tokens": [1, 2, 3],
            "token_budget": 300,
            "password_hint": "favorite color",
            "access_token_ttl": 3600,
            "cookie_notice": true,
            "authorization_level": 4,
            "secret_santa": "holiday",
            "shortCode": "AbC123",
            "duration": 9.5,
            "count": 3,
            "active": true
        });
        let result = TranscriptResult {
            status: Status::Success,
            run_id: Some("run-key-suffix-test".into()),
            dataset_id: Some("dataset-key-suffix-test".into()),
            source_url: "https://www.instagram.com/reel/AbC123/".into(),
            text: Some("ordinary transcript remains verbatim".into()),
            segments: vec![json!({"start": 1.25, "text": "ordinary segment remains verbatim"})],
            raw_items: vec![raw],
            error: None,
            stage: Some("dataset_classification".into()),
            build_number: Some("0.0.50".into()),
            build_id: Some("synthetic-build".into()),
            build_verification: BuildVerification::Verified,
            attribution_verification: AttributionVerification::Verified,
            dataset_complete: true,
        };

        let debug = format!("{result:?}");
        for secret in secrets {
            assert!(!debug.contains(secret), "debug secret persisted: {secret}");
        }

        let path = write_result(d.path(), &result).unwrap();
        let saved = fs::read_to_string(path).unwrap();
        for secret in secrets {
            assert!(!saved.contains(secret), "secret persisted: {secret}");
        }
        let parsed: serde_json::Value = serde_json::from_str(&saved).expect("saved JSON parses");
        let saved_raw = &parsed["rawItems"][0];
        assert!(saved_raw.get("client_secret").is_none());
        assert!(saved_raw["nested"][0].get("api_token").is_none());
        let nested = saved_raw["nested"][1]
            .as_array()
            .expect("nested array preserved");
        assert_eq!(nested.len(), 9);
        for (index, key) in [
            "x-auth-token",
            "proxy-authorization",
            "set-cookie",
            "private_key",
            "secret_key",
            "passwd",
            "pwd",
            "bearer",
            "credential",
        ]
        .iter()
        .enumerate()
        {
            assert!(
                nested[index]
                    .as_object()
                    .expect("entry remains an object")
                    .is_empty(),
                "sensitive field {key} was not removed"
            );
        }
        for (key, expected) in [
            ("token_count", json!(12)),
            ("password_policy", json!("minimum length")),
            ("tokenizer", json!("whitespace")),
            ("tokens", json!([1, 2, 3])),
            ("token_budget", json!(300)),
            ("password_hint", json!("favorite color")),
            ("access_token_ttl", json!(3600)),
            ("cookie_notice", json!(true)),
            ("authorization_level", json!(4)),
            ("secret_santa", json!("holiday")),
        ] {
            assert_eq!(saved_raw[key], expected, "business field changed: {key}");
        }
        assert_eq!(saved_raw["shortCode"], "AbC123");
        assert_eq!(saved_raw["duration"], 9.5);
        assert_eq!(saved_raw["count"], 3);
        assert_eq!(saved_raw["active"], true);
        assert_eq!(parsed["text"], "ordinary transcript remains verbatim");
        assert_eq!(parsed["segments"][0]["start"], 1.25);
        assert_eq!(
            parsed["segments"][0]["text"],
            "ordinary segment remains verbatim"
        );

        let journal = InMemoryJournal::default();
        let record = JournalRecord {
            stage: "intent".into(),
            mode: "single".into(),
            actor_id: "synthetic-actor".into(),
            source_url: None,
            run_id: None,
            dataset_id: None,
            run_status: None,
            build_number: None,
            build_id: None,
            build_verification: "pending".into(),
            cap: None,
            input_digest: None,
            context: Some(json!({
                "outer": [{"client_secret": secrets[0], "child": {"api_token": secrets[1]}}],
                "token_count": 12
            })),
            error: None,
        };
        assert!(!format!("{record:?}").contains(secrets[0]));
        journal.append(&record).unwrap();
        let records = journal.records();
        let saved_journal = serde_json::to_string(&records).unwrap();
        for secret in secrets.iter().take(2) {
            assert!(
                !saved_journal.contains(secret),
                "journal secret persisted: {secret}"
            );
        }
        assert_eq!(records[0].context.as_ref().unwrap()["token_count"], 12);
    }
    #[test]
    fn result_path_does_not_overwrite_existing() {
        let d = tempfile::tempdir().unwrap();
        let r = TranscriptResult::empty("u", Status::Unknown, "x", None);
        let a = write_result(d.path(), &r).unwrap();
        let old = fs::read(&a).unwrap();
        let b = write_result(d.path(), &r).unwrap();
        assert_ne!(a, b);
        assert_eq!(fs::read(a).unwrap(), old);
    }
}
