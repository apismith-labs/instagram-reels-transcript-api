package com.apismith.instagram.transcriptapi;

public class TranscriptClientException extends RuntimeException {
    private final String runId, datasetId, stage;
    public TranscriptClientException(String message, String stage, String runId, String datasetId) { super(message); this.stage=stage; this.runId=runId; this.datasetId=datasetId; }
    public TranscriptClientException(String message, String stage, String runId, String datasetId, Throwable cause) { super(message,cause); this.stage=stage; this.runId=runId; this.datasetId=datasetId; }
    public String stage(){return stage;} public String runId(){return runId;} public String datasetId(){return datasetId;}
}
