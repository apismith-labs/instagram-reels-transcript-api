package com.apismith.instagram.transcriptapi;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Clock;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.EnumSet;
import java.util.Map;

public final class OutputFiles {
    private static final DateTimeFormatter STAMP=DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmssSSS'Z'").withZone(ZoneOffset.UTC);
    private OutputFiles(){}
    public static Path writeUnique(Path directory,String prefix,Object document,Clock clock)throws IOException{
        Files.createDirectories(directory);String base=prefix+"-"+STAMP.format(clock.instant());Path chosen=null;
        for(int i=0;i<100;i++){Path candidate=directory.resolve(base+"-"+java.util.UUID.randomUUID()+".json");try{try{Files.createFile(candidate,PosixFilePermissions.asFileAttribute(EnumSet.of(PosixFilePermission.OWNER_READ,PosixFilePermission.OWNER_WRITE)));}catch(UnsupportedOperationException ex){Files.createFile(candidate);}chosen=candidate;break;}catch(java.nio.file.FileAlreadyExistsException ignored){}}
        if(chosen==null)throw new IOException("could not reserve a unique result path");
        try{try{Files.setPosixFilePermissions(chosen,EnumSet.of(PosixFilePermission.OWNER_READ,PosixFilePermission.OWNER_WRITE));}catch(UnsupportedOperationException ignored){}
            JsonNode tree=JsonSupport.MAPPER.valueToTree(document);JsonNode clean=JsonSupport.sanitizeForOutput(tree);byte[] bytes=(JsonSupport.MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(clean)+"\n").getBytes(StandardCharsets.UTF_8);
            try(FileChannel c=FileChannel.open(chosen,StandardOpenOption.WRITE)){ByteBuffer b=ByteBuffer.wrap(bytes);while(b.hasRemaining())c.write(b);c.force(true);}return chosen;
        }catch(Exception ex){if(ex instanceof IOException io)throw io;throw new IOException("result JSON could not be written",ex);}
    }
    public static Map<String,Object> singleDocument(TranscriptResult r){Map<String,Object> m=new java.util.LinkedHashMap<>();m.put("schemaVersion",1);m.put("mode","single_url");m.put("status",r.status());m.put("runStatus",r.runStatus());m.put("runId",r.runId());m.put("datasetId",r.datasetId());m.put("sourceUrl",r.sourceUrl());m.put("actorId",r.actorId());m.put("buildNumber",r.buildNumber());m.put("buildId",r.buildId());m.put("buildVerification",r.buildVerification());m.put("buildEvidenceSource",r.buildEvidenceSource());m.put("datasetComplete",r.datasetComplete());m.put("datasetCompleteKnown",r.datasetCompleteKnown());m.put("text",r.text());m.put("segments",r.segments());m.put("segmentsCount",r.segments().size());m.put("itemCount",r.rawItems().size());m.put("rawItems",r.rawItems());m.put("error",r.error());m.put("stage",r.stage());m.put("attributionVerification",r.attributionVerification());return m;}
}
