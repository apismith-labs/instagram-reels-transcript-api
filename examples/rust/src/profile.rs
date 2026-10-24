//! Profile post metadata support. This API does not claim to produce transcripts.
use crate::{
    config::Config,
    error::{Error, ErrorKind, Result},
    execute::{get_dataset_page, poll_run, post_run, read_build_number},
    journal::JournalRecord,
    sanitize::{diagnostic, sanitize_value},
    status::BuildVerification,
    validators::{validate_only_posts_newer_than, validate_usernames},
};
use serde::{Serialize, Serializer};
use serde_json::{json, Value};
use std::{collections::HashSet, fmt};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProfileStatus {
    Success,
    Empty,
    ActorError,
    Unknown,
    RunFailed,
}

#[derive(Clone, Default, Debug)]
pub struct ProfileOptions {
    pub results_limit: Option<usize>,
    pub only_posts_newer_than: Option<String>,
    pub skip_pinned_posts: Option<bool>,
    pub include_shares_count: Option<bool>,
}

#[derive(Clone)]
pub struct ProfilePost {
    pub url: Option<String>,
    pub post_type: Option<String>,
    pub owner_username: Option<String>,
    pub caption: Option<String>,
    pub timestamp: Option<Value>,
    pub video_url: Option<String>,
    pub video_duration: Option<Value>,
    pub status: ProfileStatus,
    pub error: Option<String>,
    pub raw: Value,
}

impl fmt::Debug for ProfilePost {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let value = serde_json::to_value(self)
            .map(|v| sanitize_value(&v))
            .unwrap_or(Value::Null);
        f.debug_tuple("ProfilePost").field(&value).finish()
    }
}

impl Serialize for ProfilePost {
    fn serialize<S>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let safe = serde_json::json!({
            "url": self.url.as_ref().map(|s| crate::sanitize::redact_text(s)),
            "type": self.post_type.as_ref().map(|s| crate::sanitize::redact_text(s)),
            "ownerUsername": self.owner_username.as_ref().map(|s| crate::sanitize::redact_text(s)),
            "caption": self.caption.as_ref().map(|s| crate::sanitize::redact_text(s)),
            "timestamp": self.timestamp.as_ref().map(sanitize_value),
            "videoUrl": self.video_url.as_ref().map(|s| crate::sanitize::redact_text(s)),
            "videoDuration": self.video_duration.as_ref().map(sanitize_value),
            "status": self.status,
            "error": self.error.as_deref().map(diagnostic),
            "raw": sanitize_value(&self.raw),
        });
        // Serialize through the shared sanitizer to keep Raw Actor values safe.
        let bytes =
            serde_json::to_vec(&sanitize_value(&safe)).map_err(serde::ser::Error::custom)?;
        let value: Value = serde_json::from_slice(&bytes).map_err(serde::ser::Error::custom)?;
        value.serialize(serializer)
    }
}

#[derive(Clone)]
pub struct ProfileResult {
    pub status: ProfileStatus,
    pub usernames: Vec<String>,
    pub posts: Vec<ProfilePost>,
    pub raw_items: Vec<Value>,
    pub run_id: Option<String>,
    pub dataset_id: Option<String>,
    pub run_status: Option<String>,
    pub build_number: Option<String>,
    pub build_id: Option<String>,
    pub build_verification: BuildVerification,
    pub dataset_complete: bool,
    pub error: Option<String>,
}

impl fmt::Debug for ProfileResult {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let value = serde_json::to_value(self)
            .map(|v| sanitize_value(&v))
            .unwrap_or(Value::Null);
        f.debug_tuple("ProfileResult").field(&value).finish()
    }
}

impl Serialize for ProfileResult {
    fn serialize<S>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        #[derive(Serialize)]
        #[serde(rename_all = "camelCase")]
        struct SafeResult<'a> {
            status: ProfileStatus,
            usernames: &'a [String],
            posts: &'a [ProfilePost],
            raw_items: &'a [Value],
            run_id: &'a Option<String>,
            dataset_id: &'a Option<String>,
            run_status: &'a Option<String>,
            build_number: &'a Option<String>,
            build_id: &'a Option<String>,
            build_verification: BuildVerification,
            dataset_complete: bool,
            error: &'a Option<String>,
        }
        let value = serde_json::to_value(SafeResult {
            status: self.status,
            usernames: &self.usernames,
            posts: &self.posts,
            raw_items: &self.raw_items,
            run_id: &self.run_id,
            dataset_id: &self.dataset_id,
            run_status: &self.run_status,
            build_number: &self.build_number,
            build_id: &self.build_id,
            build_verification: self.build_verification,
            dataset_complete: self.dataset_complete,
            error: &self.error,
        })
        .map_err(serde::ser::Error::custom)?;
        sanitize_value(&value).serialize(serializer)
    }
}

pub(crate) fn get_profile_posts(
    config: &Config,
    usernames: &[String],
    options: ProfileOptions,
) -> Result<ProfileResult> {
    let usernames = validate_usernames(usernames)?;
    let date = validate_only_posts_newer_than(options.only_posts_newer_than.as_deref())?;
    let limit = options.results_limit.unwrap_or(12);
    if limit == 0 {
        return Err(Error::new(
            ErrorKind::Input,
            "input_validation",
            "resultsLimit must be positive",
        ));
    }
    let mut input = json!({ "usernames": usernames, "resultsLimit": limit,
        "skipPinnedPosts": options.skip_pinned_posts.unwrap_or(false),
        "includeSharesCount": options.include_shares_count.unwrap_or(false) });
    if let Some(date) = date {
        input["onlyPostsNewerThan"] = Value::String(date);
    }
    let intent = JournalRecord {
        stage: "intent".into(),
        mode: "profile".into(),
        actor_id: config.actor_id.clone(),
        source_url: None,
        run_id: None,
        dataset_id: None,
        run_status: None,
        build_number: Some(config.build_number.clone()),
        build_id: Some(config.build_id.clone()),
        build_verification: "pending".into(),
        cap: Some(config.charge_cap.clone()),
        input_digest: None,
        context: Some(json!({"mode":"profile","input":input})),
        error: None,
    };
    config.journal.append(&intent)?;
    let created = post_run(config, &input)?;
    let run_id = created
        .get("id")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| {
            Error::new(
                ErrorKind::CreationUnknown,
                "run_create",
                "creation response did not contain a run id",
            )
        })?
        .to_owned();
    let mut created_record = intent.clone();
    created_record.stage = "run_created".into();
    created_record.run_id = Some(run_id.clone());
    config
        .journal
        .append(&created_record)
        .map_err(|e| e.with_run(run_id.clone()))?;
    let deadline = config.clock.now() + config.poll_timeout;
    let run = poll_run(config, &run_id, deadline)?;
    let run_status = run
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("UNKNOWN")
        .to_owned();
    let dataset_id = run
        .get("defaultDatasetId")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let build_number = read_build_number(&run);
    let build_id = run
        .get("buildId")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let build_ok = build_number.as_deref() == Some(config.build_number.as_str())
        && build_id.as_deref() == Some(config.build_id.as_str());
    let mut terminal = created_record;
    terminal.stage = "run_terminal".into();
    terminal.run_status = Some(run_status.clone());
    terminal.dataset_id = dataset_id.clone();
    terminal.build_number = build_number.clone();
    terminal.build_id = build_id.clone();
    terminal.build_verification = if build_ok { "verified" } else { "mismatch" }.into();
    config
        .journal
        .append(&terminal)
        .map_err(|e| e.with_run(run_id.clone()))?;
    if run_status != "SUCCEEDED" {
        return Ok(ProfileResult {
            status: ProfileStatus::RunFailed,
            usernames,
            posts: vec![],
            raw_items: vec![],
            run_id: Some(run_id),
            dataset_id,
            run_status: Some(run_status),
            build_number,
            build_id,
            build_verification: if build_ok {
                BuildVerification::Verified
            } else {
                BuildVerification::Mismatch
            },
            dataset_complete: false,
            error: Some("Actor Run did not succeed".into()),
        });
    }
    if !build_ok {
        return Err(Error::new(
            ErrorKind::BuildMismatch,
            "build_verify",
            "Actor Build identity did not match the configured Build",
        )
        .with_run(run_id));
    }
    let dataset_id = dataset_id.ok_or_else(|| {
        Error::new(
            ErrorKind::Dataset,
            "run_poll",
            "successful Run omitted Dataset ID",
        )
        .with_run(run_id.clone())
    })?;
    let page = get_dataset_page(config, &dataset_id, deadline)
        .map_err(|e| e.with_run(run_id.clone()).with_dataset(dataset_id.clone()))?;
    let requested: HashSet<String> = usernames.iter().map(|u| u.to_ascii_lowercase()).collect();
    let mut actor_error = false;
    let mut unknown = false;
    let mut posts = Vec::new();
    for item in &page.items {
        let owner = item
            .get("ownerUsername")
            .and_then(Value::as_str)
            .map(str::to_owned);
        let valid_url = item
            .get("url")
            .and_then(Value::as_str)
            .and_then(|u| crate::validators::validate_video_url(u).ok())
            .is_some();
        let metadata = ["type", "caption", "timestamp", "id", "pk", "img"]
            .iter()
            .any(|key| {
                item.get(*key)
                    .is_some_and(|value| has_meaningful_profile_metadata(key, value))
            });
        let owner_ok = match owner.as_deref() {
            Some(owner) => requested.contains(&owner.to_ascii_lowercase()),
            None => usernames.len() == 1,
        };
        let err = item
            .get("errMsg")
            .and_then(Value::as_str)
            .filter(|s| !s.trim().is_empty())
            .map(diagnostic);
        let identifiable = valid_url && metadata && owner_ok;
        let status = if err.is_some() {
            actor_error = true;
            ProfileStatus::ActorError
        } else if !identifiable {
            unknown = true;
            ProfileStatus::Unknown
        } else {
            ProfileStatus::Success
        };
        posts.push(ProfilePost {
            url: item.get("url").and_then(Value::as_str).map(str::to_owned),
            post_type: item.get("type").and_then(Value::as_str).map(str::to_owned),
            owner_username: owner,
            caption: item
                .get("caption")
                .and_then(Value::as_str)
                .map(str::to_owned),
            timestamp: item.get("timestamp").cloned(),
            video_url: item
                .get("videoUrl")
                .and_then(Value::as_str)
                .map(str::to_owned),
            video_duration: item.get("videoDuration").cloned(),
            status,
            error: err,
            raw: item.clone(),
        });
    }
    let status = if actor_error {
        ProfileStatus::ActorError
    } else if !page.complete || unknown {
        ProfileStatus::Unknown
    } else if posts.is_empty() {
        ProfileStatus::Empty
    } else {
        ProfileStatus::Success
    };
    let result = ProfileResult {
        status,
        usernames,
        posts,
        raw_items: page.items,
        run_id: Some(run_id),
        dataset_id: Some(dataset_id),
        run_status: Some(run_status),
        build_number,
        build_id,
        build_verification: BuildVerification::Verified,
        dataset_complete: page.complete,
        error: None,
    };
    let mut classified = terminal;
    classified.stage = "classified".into();
    classified.error = result.error.clone();
    config
        .journal
        .append(&classified)
        .map_err(|e| e.with_run(result.run_id.clone().unwrap_or_default()))?;
    Ok(result)
}

fn has_meaningful_profile_metadata(key: &str, value: &Value) -> bool {
    match value {
        Value::String(value) => !value.trim().is_empty(),
        Value::Number(value) if matches!(key, "timestamp" | "id" | "pk") => value
            .as_f64()
            .is_some_and(|number| number.is_finite() && number > 0.0),
        Value::Number(_) => false,
        Value::Null | Value::Bool(_) | Value::Array(_) | Value::Object(_) => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        transport::{Request, Response, Transport, TransportError},
        Client, Config,
    };
    use reqwest::Method;
    use std::sync::{Arc, Mutex};
    struct Fake {
        responses: Mutex<Vec<Response>>,
        posts: std::sync::atomic::AtomicUsize,
    }
    impl Transport for Fake {
        fn send(&self, req: &Request) -> std::result::Result<Response, TransportError> {
            if req.method == Method::POST {
                self.posts.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            }
            Ok(self.responses.lock().unwrap().remove(0))
        }
        fn guarantees_single_shot_post(&self) -> bool {
            true
        }
    }
    fn fixture(items: Value) -> (Client, Arc<Fake>) {
        let mut responses = vec![
            Response::json(201, json!({"data":{"id":"r1"}})),
            Response::json(
                200,
                json!({"data":{"status":"SUCCEEDED","defaultDatasetId":"d1","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}),
            ),
        ];
        let reads = if items.as_array().is_some_and(Vec::is_empty) {
            3
        } else {
            1
        };
        responses.extend((0..reads).map(|_| Response::json(200, items.clone())));
        let fake = Arc::new(Fake {
            responses: Mutex::new(responses),
            posts: Default::default(),
        });
        let config = Config::builder()
            .token("synthetic")
            .max_total_charge_usd("0.10")
            .transport(fake.clone())
            .journal(Arc::new(crate::journal::InMemoryJournal::default()))
            .build()
            .unwrap();
        (Client::new(config), fake)
    }
    #[test]
    fn profile_requires_valid_nonduplicate_usernames_before_transport() {
        let (client, fake) = fixture(json!([]));
        assert!(client
            .get_profile_posts(
                &["@alice".into(), "alice".into()],
                ProfileOptions::default()
            )
            .is_err());
        assert_eq!(fake.posts.load(std::sync::atomic::Ordering::SeqCst), 0);
    }
    #[test]
    fn profile_attributes_posts_by_owner_not_dataset_position() {
        let (client, fake) = fixture(
            json!([{"url":"https://instagram.com/p/x/","ownerUsername":"bob","caption":"ok"}]),
        );
        let result = client
            .get_profile_posts(&["alice".into(), "bob".into()], ProfileOptions::default())
            .unwrap();
        assert_eq!(result.status, ProfileStatus::Success);
        assert_eq!(result.posts[0].owner_username.as_deref(), Some("bob"));
        assert_eq!(fake.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    }
    #[test]
    fn profile_missing_owner_in_multi_account_batch_is_unknown() {
        let (client, _) = fixture(json!([{"url":"https://instagram.com/p/x/","caption":"ok"}]));
        let result = client
            .get_profile_posts(&["alice".into(), "bob".into()], ProfileOptions::default())
            .unwrap();
        assert_eq!(result.status, ProfileStatus::Unknown);
    }
    #[test]
    fn profile_owner_outside_requested_accounts_is_unknown_not_positionally_assigned() {
        let (client, _) = fixture(
            json!([{"url":"https://instagram.com/p/x/","ownerUsername":"mallory","caption":"untrusted"}]),
        );
        let result = client
            .get_profile_posts(&["alice".into(), "bob".into()], ProfileOptions::default())
            .unwrap();
        assert_eq!(
            result.status,
            ProfileStatus::Unknown,
            "an owner outside the request set cannot be attributed"
        );
        assert_eq!(result.posts[0].status, ProfileStatus::Unknown);
        assert!(result.posts[0].raw.get("ownerUsername").is_some());
    }
    #[test]
    fn profile_actor_error_has_priority_over_unknown() {
        let (client, _) = fixture(json!([
            {"url":"https://instagram.com/p/x/","ownerUsername":"alice","caption":"","errMsg":"crawed empty"},
            {"caption":"unattributed"}
        ]));
        let result = client
            .get_profile_posts(&["alice".into()], ProfileOptions::default())
            .unwrap();
        assert_eq!(
            result.status,
            ProfileStatus::ActorError,
            "Actor errors outrank unrelated unknown rows"
        );
        assert_eq!(result.posts[0].error.as_deref(), Some("crawed empty"));
    }
    #[test]
    fn profile_actor_error_precedes_identifiability_and_preserves_sanitized_diagnostics() {
        let (client, _) = fixture(json!([
            {"errMsg":"crawed empty password=PROFILE_SYNTHETIC_SECRET"},
            {"url":"notaurl","ownerUsername":"alice","errMsg":"crawed empty"},
            {"url":"https://instagram.com/p/valid/","ownerUsername":"alice","caption":"caption"}
        ]));
        let result = client
            .get_profile_posts(&["alice".into()], ProfileOptions::default())
            .unwrap();
        assert_eq!(
            result.status,
            ProfileStatus::ActorError,
            "errMsg must take priority over URL identifiability"
        );
        assert_eq!(result.posts[0].status, ProfileStatus::ActorError);
        assert_eq!(result.posts[1].status, ProfileStatus::ActorError);
        assert_eq!(result.posts[2].status, ProfileStatus::Success);
        assert!(result.posts[0]
            .error
            .as_deref()
            .unwrap()
            .contains("crawed empty"));
        assert!(!serde_json::to_string(&result)
            .unwrap()
            .contains("PROFILE_SYNTHETIC_SECRET"));
        assert_eq!(
            result.posts[0].raw["errMsg"],
            "crawed empty password=PROFILE_SYNTHETIC_SECRET"
        );
        assert!(
            result.posts[0].raw.is_object(),
            "the source Actor item remains available"
        );
    }
    #[test]
    fn profile_only_nonempty_errmsg_is_actor_error_but_null_or_empty_is_not() {
        let (client, _) = fixture(json!([
            {"errMsg":"crawed empty"},
            {"url":"https://instagram.com/p/null/","ownerUsername":"alice","caption":"ok","errMsg":null},
            {"url":"https://instagram.com/p/empty/","ownerUsername":"alice","caption":"ok","errMsg":""}
        ]));
        let result = client
            .get_profile_posts(&["alice".into()], ProfileOptions::default())
            .unwrap();
        assert_eq!(result.status, ProfileStatus::ActorError);
        assert_eq!(result.posts[0].status, ProfileStatus::ActorError);
        assert_eq!(result.posts[1].status, ProfileStatus::Success);
        assert_eq!(result.posts[2].status, ProfileStatus::Success);
    }
    #[test]
    fn profile_null_empty_blank_and_wrong_type_metadata_are_not_credible() {
        let invalid_metadata = [
            json!({"caption":null}),
            json!({"caption":""}),
            json!({"caption":"   "}),
            json!({"timestamp":null}),
            json!({"timestamp":""}),
            json!({"timestamp":true}),
            json!({"caption":[]}),
            json!({"caption":{}}),
            json!({"caption":1}),
            json!({"type":1}),
        ];
        for metadata in invalid_metadata {
            let item = json!({"url":"https://instagram.com/p/meta/","ownerUsername":"alice"})
                .as_object()
                .unwrap()
                .iter()
                .map(|(k, v)| (k.clone(), v.clone()))
                .chain(
                    metadata
                        .as_object()
                        .unwrap()
                        .iter()
                        .map(|(k, v)| (k.clone(), v.clone())),
                )
                .collect::<serde_json::Map<_, _>>();
            let (client, _) = fixture(Value::Array(vec![Value::Object(item)]));
            let result = client
                .get_profile_posts(&["alice".into()], ProfileOptions::default())
                .unwrap();
            assert_eq!(
                result.status,
                ProfileStatus::Unknown,
                "empty profile metadata must not identify a post"
            );
        }
        for metadata in [
            json!({"caption":"meaningful caption"}),
            json!({"timestamp":1700000000}),
        ] {
            let mut item = json!({"url":"https://instagram.com/p/meta/","ownerUsername":"alice"});
            for (key, value) in metadata.as_object().unwrap() {
                item[key] = value.clone();
            }
            let (client, _) = fixture(json!([item]));
            assert_eq!(
                client
                    .get_profile_posts(&["alice".into()], ProfileOptions::default())
                    .unwrap()
                    .status,
                ProfileStatus::Success
            );
        }
    }
    #[test]
    fn profile_single_account_missing_owner_is_allowed_when_metadata_is_valid() {
        let (client, _) = fixture(
            json!([{"url":"https://instagram.com/p/no-owner/","caption":"visible metadata"}]),
        );
        let result = client
            .get_profile_posts(&["alice".into()], ProfileOptions::default())
            .unwrap();
        assert_eq!(result.status, ProfileStatus::Success,
            "single-account missing-owner policy must stay permissive when the item is otherwise identifiable");
    }
    #[test]
    fn profile_only_metadata_does_not_claim_transcript() {
        let (client, _) = fixture(
            json!([{"url":"https://instagram.com/p/x/","ownerUsername":"alice","caption":"caption"}]),
        );
        let result = client
            .get_profile_posts(&["alice".into()], ProfileOptions::default())
            .unwrap();
        let json = serde_json::to_value(result).unwrap();
        assert_eq!(json["status"], "success");
        assert!(json.get("text").is_none());
        assert_eq!(json["rawItems"].as_array().unwrap().len(), 1);
    }
    #[test]
    fn profile_empty_dataset_is_empty() {
        let (client, _) = fixture(json!([]));
        let result = client
            .get_profile_posts(&["alice".into()], ProfileOptions::default())
            .unwrap();
        assert_eq!(result.status, ProfileStatus::Empty);
    }
    #[test]
    fn profile_invalid_url_is_retained_as_unknown_without_claiming_success() {
        let (client, _) =
            fixture(json!([{"url":"notaurl","ownerUsername":"alice","caption":"retained"}]));
        let result = client
            .get_profile_posts(&["alice".into()], ProfileOptions::default())
            .unwrap();
        assert_eq!(result.status, ProfileStatus::Unknown);
        assert_eq!(result.posts[0].raw["caption"], "retained");
    }

    #[test]
    fn profile_owner_alone_does_not_identify_a_post() {
        let (client, _) =
            fixture(json!([{"url":"https://instagram.com/p/x/","ownerUsername":"alice"}]));
        let result = client
            .get_profile_posts(&["alice".into()], ProfileOptions::default())
            .unwrap();
        assert_eq!(
            result.status,
            ProfileStatus::Unknown,
            "owner metadata alone is insufficient to identify a post"
        );
        assert!(result.posts[0].raw.get("ownerUsername").is_some());
    }
    #[test]
    fn profile_failed_run_is_run_failed_and_has_no_posts() {
        let responses = vec![
            Response::json(201, json!({"data":{"id":"failed-profile"}})),
            Response::json(
                200,
                json!({"data":{"status":"FAILED","defaultDatasetId":"unused","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}}),
            ),
        ];
        let fake = Arc::new(Fake {
            responses: Mutex::new(responses),
            posts: Default::default(),
        });
        let config = Config::builder()
            .token("synthetic")
            .max_total_charge_usd("0.10")
            .transport(fake.clone())
            .journal(Arc::new(crate::journal::InMemoryJournal::default()))
            .build()
            .unwrap();
        let result = Client::new(config)
            .get_profile_posts(&["alice".into()], ProfileOptions::default())
            .unwrap();
        assert_eq!(result.status, ProfileStatus::RunFailed);
        assert_eq!(result.run_id.as_deref(), Some("failed-profile"));
        assert!(result.posts.is_empty());
        assert_eq!(fake.posts.load(std::sync::atomic::Ordering::SeqCst), 1);
    }
}
