package com.apismith.instagram.transcriptapi;
import java.io.IOException;
import java.util.List;
import java.util.Optional;
public interface Journal {
    /** Non-thread-safe by contract; callers must serialize operations. */
    void append(JournalRecord record) throws IOException;
    Optional<JournalRecord> latest(String runId) throws IOException;
    List<JournalRecord> readAll() throws IOException;
}
