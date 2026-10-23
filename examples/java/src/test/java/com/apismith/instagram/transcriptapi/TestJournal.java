package com.apismith.instagram.transcriptapi;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
final class TestJournal implements Journal {
    private final List<JournalRecord> records=new ArrayList<>(); private final int failAppendNumber; private int appends;
    TestJournal(){this(-1);} TestJournal(int failAppendNumber){this.failAppendNumber=failAppendNumber;}
    @Override public void append(JournalRecord r)throws IOException{if(++appends==failAppendNumber)throw new IOException("disk full");records.add(r);}
    @Override public Optional<JournalRecord> latest(String id){for(int i=records.size()-1;i>=0;i--)if(id!=null&&id.equals(records.get(i).runId()))return Optional.of(records.get(i));return Optional.empty();}
    @Override public List<JournalRecord> readAll(){return List.copyOf(records);}
}
