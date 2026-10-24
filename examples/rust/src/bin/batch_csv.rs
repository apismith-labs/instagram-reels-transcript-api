//! Compatibility shim. All CSV behavior delegates to the single reviewed CLI implementation.
use std::{
    env,
    process::{self, Command},
};

fn main() {
    let current = match env::current_exe() {
        Ok(path) => path,
        Err(_) => {
            eprintln!("CSV compatibility shim cannot locate its executable");
            process::exit(2);
        }
    };
    let name = if cfg!(windows) {
        "instagram-transcripts.exe"
    } else {
        "instagram-transcripts"
    };
    let direct = current.with_file_name(name);
    let from_deps = current
        .parent()
        .and_then(|parent| parent.parent())
        .map(|parent| parent.join(name));
    let executable = [Some(direct), from_deps]
        .into_iter()
        .flatten()
        .find(|path| path.is_file());
    let Some(executable) = executable else {
        eprintln!("CSV compatibility shim cannot locate instagram-transcripts");
        process::exit(2);
    };
    let mut command = Command::new(executable);
    command.arg("csv").args(env::args_os().skip(1));
    match command.status() {
        Ok(status) => process::exit(status.code().unwrap_or(2)),
        Err(_) => {
            eprintln!("CSV compatibility shim could not start instagram-transcripts csv");
            process::exit(2);
        }
    }
}
