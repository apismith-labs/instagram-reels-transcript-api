use crate::{
    error::{Error, ErrorKind, Result},
    sanitize::diagnostic,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    fmt,
    fs::{self, File, OpenOptions},
    io::{BufRead, BufReader, Read, Seek, SeekFrom, Write},
    path::{Path, PathBuf},
    sync::Mutex,
};

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
    #[serde(rename = "inputContext", alias = "context")]
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
    fn all(&self) -> Result<Vec<JournalRecord>> {
        Err(Error::new(
            ErrorKind::Journal,
            "journal",
            "journal does not support record enumeration",
        ))
    }
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
    fn all(&self) -> Result<Vec<JournalRecord>> {
        self.records
            .lock()
            .map(|r| r.clone())
            .map_err(|_| Error::new(ErrorKind::Journal, "journal", "journal lock poisoned"))
    }
}

/// Append-only JSONL journal. A stale inter-process lock is intentionally fail-closed.
pub struct JsonlFileJournal {
    path: PathBuf,
    process_lock: Mutex<()>,
}

impl JsonlFileJournal {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let requested_path = path.as_ref().to_path_buf();
        let parent = requested_path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        let absolute_parent = if parent.is_absolute() {
            parent.to_path_buf()
        } else {
            std::env::current_dir()
                .map_err(|_| journal_io("could not resolve journal directory"))?
                .join(parent)
        };
        // Check the caller's path before canonicalization, which would erase
        // evidence that an input component was a symbolic link.
        reject_symlink_components(&absolute_parent)?;
        fs::create_dir_all(parent).map_err(|_| journal_io("could not create journal directory"))?;
        let canonical_parent = fs::canonicalize(parent)
            .map_err(|_| journal_io("could not resolve journal directory"))?;
        reject_symlink_components(&canonical_parent)?;
        let file_name = requested_path
            .file_name()
            .ok_or_else(|| journal_io("journal path must name a file"))?;
        let path = canonical_parent.join(file_name);
        if let Ok(meta) = fs::symlink_metadata(&path) {
            if meta.file_type().is_symlink() || !meta.is_file() {
                return Err(journal_io(
                    "journal path must be a regular non-symlink file",
                ));
            }
        }
        let mut options = OpenOptions::new();
        options.read(true).append(true).create(true);
        set_journal_permissions(&mut options);
        set_nofollow(&mut options);
        let file = options
            .open(&path)
            .map_err(|_| journal_io("could not safely open journal"))?;
        if !file
            .metadata()
            .map_err(|_| journal_io("could not inspect journal"))?
            .is_file()
        {
            return Err(journal_io("journal path is not a regular file"));
        }
        set_file_private(&file)?;
        Ok(Self {
            path,
            process_lock: Mutex::new(()),
        })
    }

    fn read_records(&self) -> Result<Vec<JournalRecord>> {
        let mut read_options = OpenOptions::new();
        read_options.read(true);
        set_nofollow(&mut read_options);
        let file = match read_options.open(&self.path) {
            Ok(f) => f,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
            Err(_) => return Err(journal_io("could not read journal")),
        };
        let length = file
            .metadata()
            .map_err(|_| journal_io("could not inspect journal length"))?
            .len();
        if length > 0 {
            let mut tail_options = OpenOptions::new();
            tail_options.read(true);
            set_nofollow(&mut tail_options);
            let mut tail = tail_options
                .open(&self.path)
                .map_err(|_| journal_io("could not inspect journal tail"))?;
            tail.seek(SeekFrom::End(-1))
                .map_err(|_| journal_io("could not inspect journal tail"))?;
            let mut byte = [0u8; 1];
            tail.read_exact(&mut byte)
                .map_err(|_| journal_io("could not inspect journal tail"))?;
            if byte[0] != b'\n' {
                return Err(journal_io("journal ends with an incomplete JSONL record"));
            }
        }
        let mut records = Vec::new();
        for (index, line) in BufReader::new(file).lines().enumerate() {
            let line = line.map_err(|_| journal_io("could not read journal line"))?;
            if line.trim().is_empty() {
                return Err(journal_line_error(index + 1));
            }
            let record: JournalRecord =
                serde_json::from_str(&line).map_err(|_| journal_line_error(index + 1))?;
            records.push(record);
        }
        Ok(records)
    }
}

impl Journal for JsonlFileJournal {
    fn append(&self, record: &JournalRecord) -> Result<()> {
        let _process = self
            .process_lock
            .lock()
            .map_err(|_| journal_io("journal lock poisoned"))?;
        let lock_path = PathBuf::from(format!("{}.lock", self.path.display()));
        let mut lock_options = OpenOptions::new();
        lock_options.write(true).create_new(true);
        set_journal_permissions(&mut lock_options);
        set_nofollow(&mut lock_options);
        let _lock_file = lock_options
            .open(&lock_path)
            .map_err(|_| journal_io("journal is locked; refusing concurrent or stale writer"))?;
        let guard = LockFileGuard(lock_path);

        // Never append after a malformed or partially-written prior line.
        self.read_records()?;

        let mut safe = record.clone();
        safe.error = safe.error.as_deref().map(diagnostic);
        safe.context = safe.context.as_ref().map(crate::sanitize::sanitize_value);
        if safe.context.as_ref().is_some_and(contains_sensitive_key) {
            return Err(journal_io("journal context contains a credential key"));
        }
        let encoded = serde_json::to_vec(&safe)
            .map_err(|_| journal_io("could not serialize journal record"))?;
        let mut options = OpenOptions::new();
        options.append(true).write(true);
        set_journal_permissions(&mut options);
        set_nofollow(&mut options);
        let mut file = options
            .open(&self.path)
            .map_err(|_| journal_io("could not safely append journal"))?;
        if !file
            .metadata()
            .map_err(|_| journal_io("could not inspect journal"))?
            .is_file()
        {
            return Err(journal_io("journal path is not a regular file"));
        }
        set_file_private(&file)?;
        file.write_all(&encoded)
            .and_then(|_| file.write_all(b"\n"))
            .and_then(|_| file.sync_all())
            .map_err(|_| journal_io("journal append was not durably synchronized"))?;
        sync_parent(&self.path)?;
        drop(guard);
        Ok(())
    }

    fn latest(&self, run_id: &str) -> Result<Option<JournalRecord>> {
        Ok(self
            .read_records()?
            .into_iter()
            .rev()
            .find(|r| r.run_id.as_deref() == Some(run_id)))
    }

    fn all(&self) -> Result<Vec<JournalRecord>> {
        self.read_records()
    }
}

struct LockFileGuard(PathBuf);
impl Drop for LockFileGuard {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn journal_io(message: &str) -> Error {
    Error::new(ErrorKind::Journal, "journal", message)
}
fn journal_line_error(line: usize) -> Error {
    Error::new(
        ErrorKind::Journal,
        "journal",
        format!("journal contains malformed JSONL at line {line}"),
    )
}

fn reject_symlink_components(path: &Path) -> Result<()> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|_| journal_io("could not resolve journal directory"))?
            .join(path)
    };
    let mut cursor = PathBuf::new();
    for component in absolute.components() {
        cursor.push(component);
        if let Ok(meta) = fs::symlink_metadata(&cursor) {
            // macOS exposes its system temporary directory through /var -> /private/var.
            // Permit only that OS-owned root alias; reject caller-selected symlinks below it.
            let macos_var_alias = cfg!(target_os = "macos") && cursor == Path::new("/var");
            if meta.file_type().is_symlink() && !macos_var_alias {
                return Err(journal_io("journal directory contains a symbolic link"));
            }
        }
    }
    Ok(())
}

#[cfg(unix)]
fn set_journal_permissions(options: &mut OpenOptions) {
    use std::os::unix::fs::OpenOptionsExt;
    options.mode(0o600);
}
#[cfg(not(unix))]
fn set_journal_permissions(_options: &mut OpenOptions) {}
#[cfg(unix)]
fn set_file_private(file: &File) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    file.set_permissions(fs::Permissions::from_mode(0o600))
        .map_err(|_| journal_io("could not set journal permissions"))
}
#[cfg(not(unix))]
fn set_file_private(_file: &File) -> Result<()> {
    Ok(())
}
#[cfg(unix)]
fn set_nofollow(options: &mut OpenOptions) {
    use std::os::unix::fs::OpenOptionsExt;
    options.custom_flags(0x00000100);
}
#[cfg(not(unix))]
fn set_nofollow(_options: &mut OpenOptions) {}
#[cfg(unix)]
fn sync_parent(path: &Path) -> Result<()> {
    let parent = path.parent().unwrap_or(Path::new("."));
    File::open(parent)
        .and_then(|f| f.sync_all())
        .map_err(|_| journal_io("could not sync journal directory"))
}
#[cfg(not(unix))]
fn sync_parent(_path: &Path) -> Result<()> {
    Ok(())
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

    #[test]
    fn jsonl_file_journal_persists_and_reopens_with_private_permissions() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("nested/journal.jsonl");
        let record = JournalRecord {
            stage: "run_created".into(),
            mode: "single".into(),
            actor_id: "actor".into(),
            source_url: Some("https://instagram.com/reel/a".into()),
            run_id: Some("synthetic-run".into()),
            dataset_id: None,
            run_status: None,
            build_number: None,
            build_id: None,
            build_verification: "pending".into(),
            cap: Some("0.10".into()),
            input_digest: None,
            context: Some(
                serde_json::json!({"mode":"single","input":{"videoUrl":"https://instagram.com/reel/a"}}),
            ),
            error: None,
        };
        JsonlFileJournal::open(&path)
            .unwrap()
            .append(&record)
            .unwrap();
        let reopened = JsonlFileJournal::open(&path).unwrap();
        assert!(
            reopened.latest("synthetic-run").unwrap().is_some(),
            "durable row must survive reopening"
        );
        assert_eq!(
            reopened.latest("synthetic-run").unwrap().unwrap().mode,
            "single"
        );
        let raw = fs::read_to_string(&path).unwrap();
        assert!(raw.contains("inputContext"));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(path).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
    }

    #[test]
    fn jsonl_file_journal_rejects_corrupt_lines_and_symlinks() {
        let dir = tempfile::tempdir().unwrap();
        let bad = dir.path().join("bad.jsonl");
        fs::write(&bad, b"{broken}\n").unwrap();
        let journal = JsonlFileJournal::open(&bad).unwrap();
        assert!(journal.latest("x").is_err());
        let real = dir.path().join("real.jsonl");
        fs::write(&real, b"").unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::symlink;
            let link = dir.path().join("link.jsonl");
            symlink(&real, &link).unwrap();
            assert!(JsonlFileJournal::open(link).is_err());
        }
    }

    #[test]
    fn jsonl_file_journal_fails_closed_when_writer_lock_exists() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("journal.jsonl");
        let journal = JsonlFileJournal::open(&path).unwrap();
        fs::write(format!("{}.lock", path.display()), b"another writer").unwrap();
        let record = JournalRecord {
            stage: "intent".into(),
            mode: "single".into(),
            actor_id: "actor".into(),
            source_url: None,
            run_id: None,
            dataset_id: None,
            run_status: None,
            build_number: None,
            build_id: None,
            build_verification: "pending".into(),
            cap: Some("0.10".into()),
            input_digest: None,
            context: None,
            error: None,
        };
        assert!(
            journal.append(&record).is_err(),
            "concurrent or stale writers must fail closed"
        );
        assert_eq!(
            fs::read(&path).unwrap(),
            b"",
            "failed lock acquisition must not create a journal row"
        );
    }

    #[cfg(unix)]
    #[test]
    fn jsonl_file_journal_rejects_symlinked_parent_before_creating_file() {
        use std::os::unix::fs::symlink;
        let dir = tempfile::tempdir().unwrap();
        let target = dir.path().join("target");
        let link = dir.path().join("link");
        fs::create_dir(&target).unwrap();
        symlink(&target, &link).unwrap();
        assert!(JsonlFileJournal::open(link.join("new.jsonl")).is_err());
        assert!(!target.join("new.jsonl").exists());
    }

    #[test]
    fn jsonl_file_journal_rejects_incomplete_tail_before_append() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("partial.jsonl");
        fs::write(&path, b"{\"stage\":\"broken\"").unwrap();
        let journal = JsonlFileJournal::open(&path).unwrap();
        let record = JournalRecord {
            stage: "intent".into(),
            mode: "single".into(),
            actor_id: "actor".into(),
            source_url: None,
            run_id: None,
            dataset_id: None,
            run_status: None,
            build_number: None,
            build_id: None,
            build_verification: "pending".into(),
            cap: Some("0.10".into()),
            input_digest: None,
            context: None,
            error: None,
        };
        assert!(
            journal.append(&record).is_err(),
            "partial history must never be followed by a trusted row"
        );
        assert_eq!(fs::read(&path).unwrap(), b"{\"stage\":\"broken\"");
    }
}
