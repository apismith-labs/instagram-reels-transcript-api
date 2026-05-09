package com.apismith.instagram;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
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
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;

public class BatchCsv {
    private static final String DEFAULT_ACTOR_ID = "apple_yang/instagram-transcripts-scraper";
    private static final String API_BASE_URL = "https://api.apify.com/v2";
    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final OkHttpClient HTTP = new OkHttpClient.Builder()
            .callTimeout(Duration.ofMinutes(10))
            .build();
    private static final int MAX_RETRIES = 2;

    public static void main(String[] args) throws Exception {
        Path repoRoot = repoRoot();
        Dotenv dotenv = Dotenv.configure().directory(repoRoot.toString()).ignoreIfMissing().load();

        String token = requireEnv(dotenv, "APIFY_TOKEN");
        String actorId = env(dotenv, "APIFY_ACTOR_ID", DEFAULT_ACTOR_ID);
        String sessionid = env(dotenv, "INSTAGRAM_SESSIONID", "");
        int maxConcurrency = parseMaxConcurrency(env(dotenv, "MAX_CONCURRENCY", "3"));
        Path csvPath = args.length > 0 ? Path.of(args[0]).toAbsolutePath().normalize() : repoRoot.resolve("sample-data/instagram-reel-urls.csv");
        List<String> urls = readUrls(csvPath);

        if (urls.isEmpty()) {
            throw new IllegalArgumentException("Error: CSV does not contain any videoUrl values.");
        }

        System.out.println("Actor ID: " + actorId);
        System.out.println("Total URLs: " + urls.size());
        System.out.println("Max concurrency: " + maxConcurrency);
        // Higher concurrency may increase Apify usage cost and rate-limit risk.

        List<ObjectNode> results = new ArrayList<>();
        List<String[]> errors = new ArrayList<>();
        AtomicInteger processed = new AtomicInteger();
        AtomicInteger success = new AtomicInteger();
        AtomicInteger failed = new AtomicInteger();

        ExecutorService executor = Executors.newFixedThreadPool(maxConcurrency);
        List<Future<?>> futures = new ArrayList<>();

        for (String url : urls) {
            futures.add(executor.submit(() -> {
                try {
                    ObjectNode result = processUrl(token, actorId, url, sessionid);
                    synchronized (results) {
                        results.add(result);
                    }
                    success.incrementAndGet();
                } catch (Exception ex) {
                    synchronized (errors) {
                        errors.add(new String[]{url, ex.getMessage() == null ? ex.toString() : ex.getMessage()});
                    }
                    failed.incrementAndGet();
                } finally {
                    int done = processed.incrementAndGet();
                    System.out.println("Progress: total=" + urls.size() + " processed=" + done
                            + " success=" + success.get() + " failed=" + failed.get());
                }
            }));
        }

        for (Future<?> future : futures) {
            future.get();
        }
        executor.shutdown();

        Path outputDir = repoRoot.resolve("sample-output/generated");
        Files.createDirectories(outputDir);
        writeJsonl(outputDir.resolve("java-batch-results.jsonl"), results);
        writeErrorsCsv(outputDir.resolve("java-batch-errors.csv"), errors);

        System.out.println("Results path: " + outputDir.resolve("java-batch-results.jsonl"));
        System.out.println("Errors path: " + outputDir.resolve("java-batch-errors.csv"));
    }

    private static ObjectNode processUrl(String token, String actorId, String videoUrl, String sessionid) throws Exception {
        Exception lastError = null;
        for (int attempt = 0; attempt <= MAX_RETRIES; attempt++) {
            try {
                JsonNode items = callActorOnce(token, actorId, videoUrl, sessionid);
                return buildResult(videoUrl, items);
            } catch (Exception ex) {
                lastError = ex;
                if (attempt < MAX_RETRIES) {
                    Thread.sleep((long) Math.pow(2, attempt) * 1_000L);
                }
            }
        }
        throw lastError == null ? new IllegalStateException("Unknown error") : lastError;
    }

    private static JsonNode callActorOnce(String token, String actorId, String videoUrl, String sessionid) throws Exception {
        JsonNode run = startActorRun(token, actorId, videoUrl, sessionid);
        String runId = textAt(run, "id");
        if (runId.isBlank()) {
            throw new IllegalStateException("Actor run response did not include an id.");
        }

        JsonNode finishedRun = waitForRun(token, runId);
        String status = textAt(finishedRun, "status");
        if (!"SUCCEEDED".equals(status)) {
            throw new IllegalStateException("Actor run finished with status " + status + ".");
        }

        String datasetId = textAt(finishedRun, "defaultDatasetId");
        if (datasetId.isBlank()) {
            throw new IllegalStateException("Actor run completed without a defaultDatasetId.");
        }
        return fetchDatasetItems(token, datasetId);
    }

    private static ObjectNode buildResult(String sourceUrl, JsonNode items) {
        String text = firstText(items, "text");
        JsonNode segments = firstNode(items, "segments");
        String errMsg = firstText(items, "errMsg");
        int itemCount = items.isArray() ? items.size() : 0;

        String status = "success";
        if (!errMsg.isBlank()) {
            status = "actor_error";
        } else if (itemCount == 0) {
            status = "empty";
        }

        ObjectNode result = MAPPER.createObjectNode();
        result.put("sourceUrl", sourceUrl);
        result.put("status", status);
        result.put("itemCount", itemCount);
        result.put("text", text);
        result.set("segments", segments != null && segments.isArray() ? segments : MAPPER.createArrayNode());
        result.put("errMsg", errMsg);
        result.set("rawItems", items.isArray() ? items : MAPPER.createArrayNode());
        return result;
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
        throw new IllegalStateException("Timed out waiting for Actor run to finish.");
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

    private static List<String> readUrls(Path csvPath) throws IOException {
        if (!Files.exists(csvPath)) {
            throw new IOException("Error: CSV file not found: " + csvPath);
        }
        List<String> lines = Files.readAllLines(csvPath, StandardCharsets.UTF_8).stream()
                .filter(line -> !line.isBlank())
                .toList();
        if (lines.isEmpty()) {
            throw new IllegalArgumentException("Error: CSV is empty.");
        }

        List<String> headers = parseCsvLine(lines.get(0));
        int videoUrlIndex = headers.indexOf("videoUrl");
        if (videoUrlIndex < 0) {
            throw new IllegalArgumentException("Error: CSV must include a videoUrl column.");
        }

        List<String> urls = new ArrayList<>();
        for (int i = 1; i < lines.size(); i++) {
            List<String> values = parseCsvLine(lines.get(i));
            if (videoUrlIndex < values.size() && !values.get(videoUrlIndex).isBlank()) {
                urls.add(values.get(videoUrlIndex).trim());
            }
        }
        return urls;
    }

    private static List<String> parseCsvLine(String line) {
        List<String> values = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        boolean inQuotes = false;
        for (int i = 0; i < line.length(); i++) {
            char ch = line.charAt(i);
            char next = i + 1 < line.length() ? line.charAt(i + 1) : '\0';
            if (ch == '"' && inQuotes && next == '"') {
                current.append('"');
                i++;
            } else if (ch == '"') {
                inQuotes = !inQuotes;
            } else if (ch == ',' && !inQuotes) {
                values.add(current.toString().trim());
                current.setLength(0);
            } else {
                current.append(ch);
            }
        }
        values.add(current.toString().trim());
        return values;
    }

    private static void writeJsonl(Path path, List<ObjectNode> results) throws IOException {
        StringBuilder builder = new StringBuilder();
        for (ObjectNode result : results) {
            builder.append(MAPPER.writeValueAsString(result)).append('\n');
        }
        Files.writeString(path, builder.toString(), StandardCharsets.UTF_8);
    }

    private static void writeErrorsCsv(Path path, List<String[]> errors) throws IOException {
        StringBuilder builder = new StringBuilder("sourceUrl,error\n");
        for (String[] error : errors) {
            builder.append(csvEscape(error[0])).append(',').append(csvEscape(error[1])).append('\n');
        }
        Files.writeString(path, builder.toString(), StandardCharsets.UTF_8);
    }

    private static String csvEscape(String value) {
        String text = value == null ? "" : value;
        if (text.contains(",") || text.contains("\"") || text.contains("\n") || text.contains("\r")) {
            return "\"" + text.replace("\"", "\"\"") + "\"";
        }
        return text;
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

    private static int parseMaxConcurrency(String rawValue) {
        try {
            int value = Integer.parseInt(rawValue);
            if (value < 1) {
                throw new IllegalArgumentException("Error: MAX_CONCURRENCY must be at least 1.");
            }
            return value;
        } catch (NumberFormatException ex) {
            throw new IllegalArgumentException("Error: MAX_CONCURRENCY must be an integer.", ex);
        }
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
