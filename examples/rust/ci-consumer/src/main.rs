use instagram_transcripts::{
    Client, Config, Request, Response, Status, Transport, TransportError, TransportErrorKind,
};
use serde_json::json;
use std::{collections::VecDeque, sync::{Arc, Mutex}};

struct ConsumerFake(Mutex<VecDeque<Response>>);
impl Transport for ConsumerFake {
    fn send(&self, _: &Request) -> Result<Response, TransportError> {
        self.0.lock().expect("fake response lock").pop_front()
            .ok_or_else(|| TransportError::new(TransportErrorKind::Other))
    }
    fn guarantees_single_shot_post(&self) -> bool { true }
}

fn main() {
    let responses = VecDeque::from([
        Response::json(201, json!({"data":{"id":"consumer-run"}})),
        Response::json(200, json!({"data":{"status":"SUCCEEDED","defaultDatasetId":"consumer-dataset","buildNumber":"0.0.50","buildId":"aJLRmMdQapLQRT4sJ"}})),
        Response::json(200, json!([{ "url":"https://instagram.com/reel/consumer", "text":"offline consumer transcript" }])),
    ]);
    let fake = Arc::new(ConsumerFake(Mutex::new(responses)));
    let config = Config::builder()
        .token("synthetic-consumer-token")
        .max_total_charge_usd("0.01")
        .transport(fake)
        .build()
        .expect("public ClientConfig API");
    let result = Client::new(config)
        .get_transcript("https://instagram.com/reel/consumer")
        .expect("public Client Single API");
    assert_eq!(result.status, Status::Success);
    assert_eq!(result.text.as_deref(), Some("offline consumer transcript"));
    println!("external consumer fake flow: PASS");
}
