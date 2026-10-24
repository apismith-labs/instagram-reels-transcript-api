//! Legacy entrypoint intentionally fails closed until the reviewed G3 CSV implementation.
fn main() {
    eprintln!("batch_csv is disabled: the legacy implementation could repeat billable Actor creation. Use the reviewed G3 CSV plan/execute CLI when available.");
    std::process::exit(2);
}
