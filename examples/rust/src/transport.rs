use reqwest::blocking::Client as HttpClient;
use reqwest::header::{HeaderName, HeaderValue, LOCATION, RETRY_AFTER};
use reqwest::{redirect::Policy, Method};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    fmt,
    time::{Duration, Instant},
};

#[derive(Clone, Eq, PartialEq)]
pub struct Request {
    pub method: Method,
    pub url: String,
    pub headers: BTreeMap<String, String>,
    pub body: Option<Value>,
}

impl fmt::Debug for Request {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let headers: BTreeMap<_, _> = self
            .headers
            .iter()
            .map(|(name, value)| {
                let safe = if crate::sanitize::is_sensitive_key(name) {
                    "[REDACTED]".to_owned()
                } else {
                    crate::sanitize::redact_text(value)
                };
                (name, safe)
            })
            .collect();
        let url = crate::sanitize::redact_text(&self.url);
        let body = self.body.as_ref().map(crate::sanitize::sanitize_value);
        f.debug_struct("Request")
            .field("method", &self.method)
            .field("url", &url)
            .field("headers", &headers)
            .field("body", &body)
            .finish()
    }
}

impl Request {
    pub fn new(method: Method, url: impl Into<String>) -> Self {
        Self {
            method,
            url: url.into(),
            headers: BTreeMap::new(),
            body: None,
        }
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct Response {
    pub status: u16,
    pub headers: BTreeMap<String, String>,
    pub body: String,
}

impl fmt::Debug for Response {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let headers: BTreeMap<_, _> = self
            .headers
            .iter()
            .map(|(name, value)| {
                let safe = if crate::sanitize::is_sensitive_key(name) {
                    "[REDACTED]".to_owned()
                } else {
                    crate::sanitize::redact_text(value)
                };
                (name, safe)
            })
            .collect();
        f.debug_struct("Response")
            .field("status", &self.status)
            .field("headers", &headers)
            .field("body", &crate::sanitize::sanitize_debug_payload(&self.body))
            .finish()
    }
}

impl Response {
    pub fn json(status: u16, value: Value) -> Self {
        Self {
            status,
            headers: BTreeMap::new(),
            body: value.to_string(),
        }
    }
    pub fn header(mut self, name: &str, value: &str) -> Self {
        self.headers
            .insert(name.to_ascii_lowercase(), value.to_owned());
        self
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TransportErrorKind {
    Timeout,
    Connection,
    InvalidRequest,
    Other,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TransportError {
    pub kind: TransportErrorKind,
}

impl TransportError {
    pub fn new(kind: TransportErrorKind) -> Self {
        Self { kind }
    }
}

pub trait Transport: Send + Sync {
    fn send(&self, request: &Request) -> std::result::Result<Response, TransportError>;
    fn guarantees_single_shot_post(&self) -> bool;
}

pub struct ReqwestTransport {
    client: HttpClient,
}

impl ReqwestTransport {
    pub fn new() -> std::result::Result<Self, TransportError> {
        let client = HttpClient::builder()
            .redirect(Policy::none())
            .timeout(Duration::from_secs(60))
            .build()
            .map_err(|_| TransportError::new(TransportErrorKind::Other))?;
        Ok(Self { client })
    }
}

impl Transport for ReqwestTransport {
    fn send(&self, request: &Request) -> std::result::Result<Response, TransportError> {
        let mut builder = self.client.request(request.method.clone(), &request.url);
        for (name, value) in &request.headers {
            let name = HeaderName::from_bytes(name.as_bytes())
                .map_err(|_| TransportError::new(TransportErrorKind::InvalidRequest))?;
            let value = HeaderValue::from_str(value)
                .map_err(|_| TransportError::new(TransportErrorKind::InvalidRequest))?;
            builder = builder.header(name, value);
        }
        if let Some(body) = &request.body {
            builder = builder.json(body);
        }
        let response = builder.send().map_err(|e| {
            if e.is_timeout() {
                TransportError::new(TransportErrorKind::Timeout)
            } else if e.is_connect() {
                TransportError::new(TransportErrorKind::Connection)
            } else {
                TransportError::new(TransportErrorKind::Other)
            }
        })?;
        let status = response.status().as_u16();
        let mut headers = BTreeMap::new();
        for (name, value) in response.headers() {
            if name == RETRY_AFTER || name == LOCATION {
                if let Ok(value) = value.to_str() {
                    headers.insert(name.as_str().to_ascii_lowercase(), value.to_owned());
                }
            }
        }
        let body = response
            .text()
            .map_err(|_| TransportError::new(TransportErrorKind::Other))?;
        Ok(Response {
            status,
            headers,
            body,
        })
    }
    fn guarantees_single_shot_post(&self) -> bool {
        true
    }
}

pub trait Clock: Send + Sync {
    fn now(&self) -> Instant;
    fn sleep(&self, duration: Duration);
}
pub struct SystemClock;
impl Clock for SystemClock {
    fn now(&self) -> Instant {
        Instant::now()
    }
    fn sleep(&self, d: Duration) {
        std::thread::sleep(d)
    }
}

pub fn bearer_headers(token: &str) -> BTreeMap<String, String> {
    BTreeMap::from([
        ("authorization".to_owned(), format!("Bearer {token}")),
        ("content-type".to_owned(), "application/json".to_owned()),
    ])
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn response_headers_are_case_normalized() {
        let r = Response::json(200, Value::Null).header("Retry-After", "4");
        assert_eq!(r.headers.get("retry-after").unwrap(), "4");
    }
    #[test]
    fn auth_header_is_never_a_url_parameter() {
        let h = bearer_headers("fake-secret");
        assert!(h.contains_key("authorization"));
        assert_eq!(h.len(), 2);
    }
    #[test]
    fn request_starts_without_body() {
        let r = Request::new(Method::GET, "https://example.invalid");
        assert!(r.body.is_none());
    }

    #[test]
    fn request_debug_redacts_authorization_secret() {
        let mut request = Request::new(
            Method::GET,
            "https://example.invalid/?token=URL_SECRET&access_token=URL_ACCESS_SECRET",
        );
        request.headers = bearer_headers("REQUEST_SECRET");
        let rendered = format!("{request:?}");
        assert!(!rendered.contains("REQUEST_SECRET"));
        assert!(!rendered.contains("URL_SECRET"));
        assert!(!rendered.contains("URL_ACCESS_SECRET"));
    }

    #[test]
    fn response_debug_redacts_json_and_text_secrets() {
        let response = Response::json(
            500,
            serde_json::json!({"message":"password=RESPONSE_SECRET"}),
        );
        let rendered = format!("{response:?}");
        assert!(!rendered.contains("RESPONSE_SECRET"));
    }
}
