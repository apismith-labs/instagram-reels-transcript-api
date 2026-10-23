package com.apismith.instagram.transcriptapi;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
/** In-process journal only; it does not survive process exit. */
public final class InMemoryJournal implements Journal {
    private final List<JournalRecord> records=new ArrayList<>();
    @Override public void append(JournalRecord record){records.add(record);}
    @Override public Optional<JournalRecord> latest(String runId){for(int i=records.size()-1;i>=0;i--){if(runId!=null&&runId.equals(records.get(i).runId()))return Optional.of(records.get(i));}return Optional.empty();}
    @Override public List<JournalRecord> readAll(){return List.copyOf(records);}
}
