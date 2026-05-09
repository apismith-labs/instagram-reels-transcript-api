package com.apismith.instagram;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.github.cdimascio.dotenv.Dotenv;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;

public class SingleUrl {
    private static final String DEFAULT_ACTOR_ID = "apple_yang/instagram-transcripts-scraper";
    private static final String API_BASE_URL = "https://api.apify.com/v2";
    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final OkHttpClient HTTP = new OkHttpClient.Builder()
            .callTimeout(Duration.ofMinutes(10))
            .build();

    public static void main(String[] args) throws Exception {
        Path repoRoot = repoRoot();
        Dotenv dotenv = Dotenv.configure().directory(repoRoot.toString()).ignoreIfMissing().load();

        String token = requireEnv(dotenv, "APIFY_TOKEN");
        String actorId = env(dotenv, "APIFY_ACTOR_ID", DEFAULT_ACTOR_ID);
        String sessionid = env(dotenv, "INSTAGRAM_SESSIONID", "");
        env(dotenv, "MAX_CONCURRENCY", "3");
        String reelUrl = args.length > 0 ? args[0] : env(dotenv, "INSTAGRAM_REEL_URL", "");

        if (reelUrl.isBlank()) {
            throw new IllegalArgumentException("Error: INSTAGRAM_REEL_URL is required. Set it in .env or pass it as a CLI argument.");
        }

        System.out.println("Actor ID: " + actorId);
        System.out.println("Running request...");

        JsonNode run = startActorRun(token, actorId, reelUrl, sessionid);
        String runId = textAt(run, "id");
        if (runId.isBlank()) {
            throw new IllegalStateException("Error: Actor run response did not include an id.");
        }

        JsonNode finishedRun = waitForRun(token, runId);
        String status = textAt(finishedRun, "status");
        if (!"SUCCEEDED".equals(status)) {
            throw new IllegalStateException("Error: Actor run finished with status " + status + ".");
        }

        String datasetId = textAt(finishedRun, "defaultDatasetId");
        if (datasetId.isBlank()) {
            throw new IllegalStateException("Error: Actor run completed without a defaultDatasetId.");
        }

        JsonNode items = fetchDatasetItems(token, datasetId);
        Path outputDir = repoRoot.resolve("sample-output/generated");
        Path outputFile = outputDir.resolve("java-single-url-response.json");
        Files.createDirectories(outputDir);
        Files.writeString(outputFile, MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(items) + "\n", StandardCharsets.UTF_8);

        String text = firstText(items, "text");
        JsonNode segments = firstNode(items, "segments");
        String errMsg = firstText(items, "errMsg");

        System.out.println("Output path: " + outputFile);
        System.out.println("Items: " + (items.isArray() ? items.size() : 0));
        System.out.println("Transcript characters: " + text.length());
        System.out.println("Segments: " + (segments != null && segments.isArray() ? segments.size() : 0));
        if (!errMsg.isBlank()) {
            System.out.println("errMsg: " + errMsg);
        }
    }

    private static JsonNode startActorRun(String token, String actorId, String reelUrl, String sessionid) throws IOException {
        ObjectNode input = MAPPER.createObjectNode();
        input.put("videoUrl", reelUrl);
        input.put("sessionid", sessionid);

        String actorIdForUrl = actorId.replace("/", "~");
        Request request = authorizedBuilder(token, API_BASE_URL + "/acts/" + actorIdForUrl + "/runs")
                .post(RequestBody.create(MAPPER.writeValueAsString(input), JSON))
                .build();
        return dataNode(executeJson(request));
    }

    private static JsonNode waitForRun(String token, String runId) throws InterruptedException, IOException {
        for (int attempt = 0; attempt < 150; attempt++) {
            Request request = authorizedBuilder(token, API_BASE_URL + "/actor-runs/" + runId).get().build();
            JsonNode run = dataNode(executeJson(request));
            String status = textAt(run, "status");
            if ("SUCCEEDED".equals(status) || "FAILED".equals(status) || "TIMED-OUT".equals(status) || "ABORTED".equals(status)) {
                return run;
            }
            Thread.sleep(2_000);
        }
        throw new IllegalStateException("Error: Timed out waiting for Actor run to finish.");
    }

    private static JsonNode fetchDatasetItems(String token, String datasetId) throws IOException {
        Request request = authorizedBuilder(token, API_BASE_URL + "/datasets/" + datasetId + "/items").get().build();
        return executeJson(request);
    }

    private static JsonNode executeJson(Request request) throws IOException {
        try (Response response = HTTP.newCall(request).execute()) {
            String body = response.body() == null ? "" : response.body().string();
            if (!response.isSuccessful()) {
                throw new IOException("HTTP " + response.code() + " from Apify API: " + body);
            }
            return body.isBlank() ? MAPPER.createArrayNode() : MAPPER.readTree(body);
        }
    }

    private static Request.Builder authorizedBuilder(String token, String url) {
        return new Request.Builder()
                .url(url)
                .header("Authorization", "Bearer " + token)
                .header("Content-Type", "application/json");
    }

    private static JsonNode dataNode(JsonNode response) {
        return response.has("data") ? response.get("data") : response;
    }

    private static String firstText(JsonNode items, String field) {
        JsonNode node = firstNode(items, field);
        return node != null && node.isTextual() ? node.asText() : "";
    }

    private static JsonNode firstNode(JsonNode items, String field) {
        if (!items.isArray()) {
            return null;
        }
        for (JsonNode item : items) {
            JsonNode value = item.get(field);
            if (value != null && !value.isNull() && !(value.isTextual() && value.asText().isBlank())) {
                return value;
            }
        }
        return null;
    }

    private static String textAt(JsonNode node, String field) {
        JsonNode value = node == null ? null : node.get(field);
        return value == null || value.isNull() ? "" : value.asText("");
    }

    private static String requireEnv(Dotenv dotenv, String name) {
        String value = env(dotenv, name, "");
        if (value.isBlank()) {
            throw new IllegalArgumentException("Error: " + name + " is required. Set it in .env or your environment.");
        }
        return value;
    }

    private static String env(Dotenv dotenv, String name, String defaultValue) {
        String value = System.getenv(name);
        if (value != null && !value.isBlank()) {
            return value;
        }
        value = dotenv.get(name);
        return value == null ? defaultValue : value;
    }

    private static Path repoRoot() {
        Path current = Path.of("").toAbsolutePath().normalize();
        while (current != null) {
            if (Files.exists(current.resolve(".env.example")) && Files.exists(current.resolve("sample-data"))) {
                return current;
            }
            current = current.getParent();
        }
        throw new IllegalStateException("Error: Could not locate repository root.");
    }
}
