package com.apismith.instagram.transcriptapi;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.locks.ReentrantLock;

/** Append-only JSONL journal. Each append is forced to disk before returning. */
public final class JsonlFileJournal implements Journal, AutoCloseable {
    private static final ObjectMapper MAPPER=new ObjectMapper().findAndRegisterModules();
    private final Path path; private final ReentrantLock lock=new ReentrantLock();
    private JsonlFileJournal(Path path){this.path=path;}
    public static JsonlFileJournal open(Path path) throws IOException {
        Path absolute=path.toAbsolutePath().normalize(); Path parent=absolute.getParent(); if(parent!=null) Files.createDirectories(parent);
        if(Files.isSymbolicLink(absolute))throw new IOException("Journal path must not be a symbolic link");
        if(!Files.exists(absolute)) {try{Files.createFile(absolute,PosixFilePermissions.asFileAttribute(EnumSet.of(PosixFilePermission.OWNER_READ,PosixFilePermission.OWNER_WRITE)));}catch(UnsupportedOperationException ex){Files.createFile(absolute);}}
        setPrivatePermissions(absolute);
        return new JsonlFileJournal(absolute);
    }
    private static void setPrivatePermissions(Path p) throws IOException { try { Set<PosixFilePermission> perms=EnumSet.of(PosixFilePermission.OWNER_READ,PosixFilePermission.OWNER_WRITE); Files.setPosixFilePermissions(p,perms); } catch(UnsupportedOperationException ignored) { /* Windows ACLs are platform-managed; do not claim POSIX 0600. */ } }
    public Path path(){return path;}
    @Override public void append(JournalRecord record) throws IOException {byte[] bytes=(MAPPER.writeValueAsString(record)+"\n").getBytes(StandardCharsets.UTF_8);lock.lock();try(FileChannel channel=FileChannel.open(path,StandardOpenOption.WRITE,StandardOpenOption.APPEND,StandardOpenOption.CREATE)){ByteBuffer buffer=ByteBuffer.wrap(bytes);while(buffer.hasRemaining())channel.write(buffer);channel.force(true);}finally{lock.unlock();}}
    @Override public Optional<JournalRecord> latest(String runId) throws IOException {JournalRecord found=null;for(JournalRecord r:readAll())if(runId!=null&&runId.equals(r.runId()))found=r;return Optional.ofNullable(found);}
    @Override public List<JournalRecord> readAll() throws IOException {lock.lock();try{List<JournalRecord> out=new ArrayList<>();int line=0;for(String raw:Files.readAllLines(path,StandardCharsets.UTF_8)){line++;if(raw.isBlank())throw new IOException("invalid empty JSONL Journal record at line "+line);try{out.add(MAPPER.readValue(raw,JournalRecord.class));}catch(Exception e){throw new IOException("invalid JSONL Journal record at line "+line,e);}}return List.copyOf(out);}finally{lock.unlock();}}
    @Override public void close() { }
}
