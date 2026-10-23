package com.apismith.instagram.transcriptapi;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.time.Instant;
import java.util.ArrayList;
import java.util.EnumMap;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/** Reusable Java 17 client. Construction performs no environment reads and no network I/O. */
public final class TranscriptClient {
    private static final String API="https://api.apify.com/v2";
    private final ClientConfig config;
    private final Transport transport;
    private final Sleeper sleeper;

    public TranscriptClient(ClientConfig config){
        this.config=config;
        this.transport=config.transport()!=null?config.transport():new JdkHttpTransport(config.token(),config.requestTimeout());
        if(!transport.guaranteesSingleShotPost())throw new ConfigurationException("Transport does not guarantee single-shot POST semantics");
        this.sleeper=config.sleeper()!=null?config.sleeper():d->Thread.sleep(d.toMillis());
    }

    /** Performs at most one Run-creation POST. */
    public TranscriptResult getTranscript(String url){return getTranscript(url,RequestOptions.defaults());}
    public TranscriptResult getTranscript(String url,RequestOptions options){return getTranscriptInternal(url,options,true);}
    private TranscriptResult getTranscriptInternal(String url,RequestOptions options,boolean includeSession){
        String valid=InputValidators.validateVideoUrl(url); EffectiveCap cap=cap(options);
        ObjectNode input=JsonSupport.MAPPER.createObjectNode().put("videoUrl",valid);
        if(includeSession&&config.sessionId()!=null&&!config.sessionId().isBlank())input.put("sessionid",config.sessionId());
        ObjectNode journalInput=JsonSupport.MAPPER.createObjectNode().put("videoUrl",valid);
        Execution e=execute("single",valid,input,context("single",journalInput),cap);
        if(e.status()!=Status.SUCCESS)return transcriptFailure(e,valid);
        return classifySingle(e,valid);
    }

    /** One Native Bulk Run for every validated URL. */
    public BulkResult getTranscripts(List<String> urls){return getTranscripts(urls,BulkOptions.defaults());}
    public BulkResult getTranscripts(List<String> urls,BulkOptions options){
        List<String> normalized=InputValidators.validateBulkInput(urls); ObjectNode input=bulkInput(normalized,options);
        EffectiveCap cap=cap(RequestOptions.defaults()); Execution e=execute("bulk","native_bulk:"+String.join(",",normalized),input,context("bulk",input),cap);
        return classifyBulk(e,normalized);
    }

    public ProfileResult getProfilePosts(String username){return getProfilePosts(List.of(username),ProfileOptions.defaults());}
    public ProfileResult getProfilePosts(List<String> usernames){return getProfilePosts(usernames,ProfileOptions.defaults());}
    public ProfileResult getProfilePosts(List<String> usernames,ProfileOptions options){
        List<String> valid=InputValidators.validateUsernames(usernames);ObjectNode input=profileInput(valid,options);
        EffectiveCap cap=cap(RequestOptions.defaults());Execution e=execute("profile","profile:"+String.join(",",valid),input,context("profile",input),cap);
        return classifyProfile(e,valid);
    }

    /** Zero-network CSV plan with exact BigDecimal cost-cap arithmetic. */
    public CsvPlan planCsv(List<CsvRow> rows){
        validateRows(rows);BigDecimal cap=config.maxTotalChargeUsd();BigDecimal total=cap==null?null:cap.multiply(BigDecimal.valueOf(rows.size())).setScale(2,RoundingMode.CEILING);
        return new CsvPlan("csv_batch_plan",rows.size(),rows.size(),1,config.buildNumber(),config.requireChargeCap(),cap,total,null);
    }

    /** Sequential CSV execution. A journal failure or unknown create outcome stops all later rows. */
    public CsvBatchResult getTranscriptsFromCsv(List<CsvRow> rows){
        validateRows(rows);cap(RequestOptions.defaults());List<CsvRowResult> results=new ArrayList<>();Map<String,Integer> counts=new LinkedHashMap<>();int planned=rows.size();boolean stopped=false;String fatal=null;
        for(int i=0;i<rows.size();i++){
            CsvRow row=rows.get(i);TranscriptResult result;
            try {result=getTranscriptInternal(row.url(),RequestOptions.defaults(),false);}
            catch(CreationUnknownException ex){results.add(csvError(row,Status.CREATION_UNKNOWN,ex));counts.merge(Status.CREATION_UNKNOWN.value(),1,Integer::sum);stopped=true;fatal=JsonSupport.redact(ex.getMessage());break;}
            catch(TranscriptClientException ex){boolean journalFailure=ex.stage()!=null&&ex.stage().startsWith("journal_");Status s=journalFailure?Status.STOPPED_UNKNOWN:Status.TRANSPORT_ERROR;results.add(csvError(row,s,ex));counts.merge(s.value(),1,Integer::sum);if(journalFailure||"creation_unknown".equals(ex.stage())){stopped=true;fatal=JsonSupport.redact(ex.getMessage());break;}continue;}
            results.add(new CsvRowResult(row.rowNumber(),row.url(),result.status(),result.runId(),result.datasetId(),result.text(),result.segments(),result.segments().size(),result.rawItems(),result.datasetCompleteKnown()?result.datasetComplete():null,result.error()));
            counts.merge(result.status().value(),1,Integer::sum);
            if(result.status()==Status.CREATION_UNKNOWN||(result.stage()!=null&&result.stage().startsWith("journal_"))){stopped=true;fatal=result.error();break;}
        }
        int unattempted=planned-results.size();String status=csvStatus(results,stopped);
        return new CsvBatchResult(status,stopped,planned,results.size(),unattempted,1,counts,List.copyOf(results),flattenRaw(results),fatal);
    }

    /** Single Resume uses only journal identity plus GET requests; it never invokes createRun. */
    public TranscriptResult resumeTranscript(String runId){
        JournalRecord r=resumeRecord(runId,"single");JsonNode in=r.inputContext().path("input");String source=r.sourceUrl();
        ObjectNode requested=JsonSupport.MAPPER.createObjectNode().put("videoUrl",source);
        if(!in.isObject()||!requested.equals(in))throw new ConfigurationException("Resume Journal inputContext does not match the recorded single URL");
        Execution e=resumeExecution(r);if(e.status()!=Status.SUCCESS)return transcriptFailure(e,source);return classifySingle(e,source);
    }
    public BulkResult resumeTranscripts(String runId,List<String> urls){return resumeTranscripts(runId,urls,BulkOptions.defaults());}
    public BulkResult resumeTranscripts(String runId,List<String> urls,BulkOptions options){
        List<String> valid=InputValidators.validateBulkInput(urls);JournalRecord r=resumeRecord(runId,"bulk");JsonNode expected=r.inputContext().path("input");
        ObjectNode requested=bulkInput(valid,options);
        if(!expected.equals(requested))throw new ConfigurationException("Resume Journal bulk input does not match");
        return classifyBulk(resumeExecution(r),valid);
    }

    public static String validateUrl(String url){return InputValidators.validateVideoUrl(url);}
    public static List<String> validateBulkInput(List<String> urls){return InputValidators.validateBulkInput(urls);}
    public static ObjectNode buildProfileInput(List<String> names,ProfileOptions opts){return profileInput(InputValidators.validateUsernames(names),opts);}

    private EffectiveCap cap(RequestOptions options){BigDecimal selected=options!=null&&options.maxTotalChargeUsd()!=null?options.maxTotalChargeUsd():config.maxTotalChargeUsd();boolean required=options!=null&&options.requireChargeCap()!=null?options.requireChargeCap():config.requireChargeCap();if(required&&(selected==null||selected.signum()<=0))throw new ConfigurationException("a positive maxTotalChargeUsd is required before creating a Run");if(selected!=null&&selected.signum()<=0)throw new ConfigurationException("maxTotalChargeUsd must be positive when supplied");return new EffectiveCap(selected,required);}
    private static ObjectNode bulkInput(List<String> urls,BulkOptions opts){ObjectNode in=JsonSupport.MAPPER.createObjectNode();ArrayNode a=in.putArray("bulkUrls");urls.forEach(a::add);if(opts!=null){if(opts.resultsLimit()!=null){if(opts.resultsLimit()<1)throw new ConfigurationException("resultsLimit must be positive");in.put("resultsLimit",opts.resultsLimit());}if(opts.skipPinnedPosts()!=null)in.put("skipPinnedPosts",opts.skipPinnedPosts());if(opts.includeSharesCount()!=null)in.put("includeSharesCount",opts.includeSharesCount());}return in;}
    private static ObjectNode profileInput(List<String> names,ProfileOptions opts){ObjectNode in=JsonSupport.MAPPER.createObjectNode();ArrayNode a=in.putArray("usernames");names.forEach(a::add);if(opts!=null){if(opts.resultsLimit()!=null){if(opts.resultsLimit()<1)throw new ConfigurationException("resultsLimit must be positive");in.put("resultsLimit",opts.resultsLimit());}String date=InputValidators.validateOnlyPostsNewerThan(opts.onlyPostsNewerThan());if(date!=null)in.put("onlyPostsNewerThan",date);if(opts.skipPinnedPosts()!=null)in.put("skipPinnedPosts",opts.skipPinnedPosts());if(opts.includeSharesCount()!=null)in.put("includeSharesCount",opts.includeSharesCount());}return in;}
    private static ObjectNode context(String mode,JsonNode input){ObjectNode c=JsonSupport.MAPPER.createObjectNode().put("mode",mode);c.set("input",input.deepCopy());return c;}
    private static void validateRows(List<CsvRow> rows){if(rows==null)throw new ConfigurationException("CSV rows are required");for(CsvRow row:rows){if(row==null||row.rowNumber()==null||row.rowNumber().isBlank())throw new ConfigurationException("CSV row number is missing");InputValidators.validateVideoUrl(row.url());}}

    private Execution execute(String mode,String source,JsonNode input,JsonNode inputContext,EffectiveCap cap){
        Journal journal=config.journal();String build=config.buildNumber();
        try{journal.append(record("intent",mode,source,null,null,null,null,build,config.buildId(),"unknown",cap,inputContext,null));}
        catch(IOException ex){throw new TransportException("Journal intent could not be persisted; no Run was created","journal_intent",null,null,ex);}
        Map<String,String> query=runQuery(cap);TransportResponse created;
        try{created=transport.send("POST",actorRunsPath(),input,query,config.requestTimeout());}
        catch(InterruptedException ex){Thread.currentThread().interrupt();throw creationUnknown(source,mode,inputContext,cap,ex);}
        catch(IOException|RuntimeException ex){throw creationUnknown(source,mode,inputContext,cap,ex);}
        if(created.statusCode()<200||created.statusCode()>=300){String message="Run creation returned HTTP "+created.statusCode();if(created.statusCode()==429||created.statusCode()>=500||created.statusCode()<400)throw creationUnknown(source,mode,inputContext,cap,new IOException(message));try{journal.append(record("create_failed",mode,source,null,null,null,null,build,config.buildId(),"unknown",cap,inputContext,message));}catch(IOException ex){throw new TransportException("Rejected Run response could not be persisted","journal_create_failed",null,null,ex);}throw new TransportException(message,"run_create_rejected",null,null);}
        JsonNode createdData;try{createdData=parseData(created.body(),"run_create_response",null,null);}catch(ProtocolException ex){throw creationUnknown(source,mode,inputContext,cap,ex);}String runId=text(createdData,"id"),datasetId=text(createdData,"defaultDatasetId"),runStatus=text(createdData,"status");
        if(runId==null||runId.isBlank())throw creationUnknown(source,mode,inputContext,cap,new IOException("Run creation response did not provide a verifiable Run ID"));
        try{journal.append(record("run_created",mode,source,runId,text(createdData,"actId", "actorId"),datasetId,runStatus, text(createdData,"buildNumber"),text(createdData,"buildId"),"unknown",cap,inputContext,null));}
        catch(IOException ex){return new Execution(Status.TRANSPORT_ERROR,"journal_run_created","Run was created but its identity could not be persisted",runId,datasetId,runStatus,text(createdData,"actId","actorId"),text(createdData,"buildNumber"),text(createdData,"buildId"),BuildVerification.UNKNOWN,false,false,List.of());}
        return completeExisting(mode,source,inputContext,cap,runId,datasetId,runStatus,text(createdData,"actId","actorId"),text(createdData,"buildNumber"),text(createdData,"buildId"),"create_response",true);
    }
    private CreationUnknownException creationUnknown(String source,String mode,JsonNode context,EffectiveCap cap,Throwable cause){try{config.journal().append(record("creation_unknown",mode,source,null,null,null,null,config.buildNumber(),config.buildId(),"unknown",cap,context,"Run creation outcome is unknown; reconcile before any retry"));}catch(IOException ignored){/* Preserve the primary unknown outcome; never repeat POST. */}return new CreationUnknownException("Run creation outcome is unknown; do not retry automatically",null,null,cause);}
    private Execution resumeExecution(JournalRecord record){
        try{config.journal().append(record("resuming",record.mode(),record.sourceUrl(),record.runId(),record.runActorId(),record.datasetId(),record.runStatus(),record.buildNumber(),record.buildId(),record.buildVerification(),new EffectiveCap(record.maxTotalChargeUsd(),false),record.inputContext(),null));}
        catch(IOException ex){throw new TransportException("Resume Journal write failed","journal_resuming",record.runId(),record.datasetId(),ex);}
        return completeExisting(record.mode(),record.sourceUrl(),record.inputContext(),new EffectiveCap(record.maxTotalChargeUsd(),false),record.runId(),record.datasetId(),record.runStatus(),record.runActorId(),record.buildNumber(),record.buildId(),"run_get",false);
    }
    private JournalRecord resumeRecord(String runId,String mode){if(runId==null||runId.isBlank())throw new ConfigurationException("runId is required for Resume");try{JournalRecord r=config.journal().latest(runId).orElseThrow(()->new ConfigurationException("Run ID is not present in Journal"));if(!runId.equals(r.runId())||!config.actorId().equals(r.actorId())||r.sourceUrl()==null||r.sourceUrl().isBlank()||r.inputContext()==null||!mode.equals(r.inputContext().path("mode").asText())||"mismatch".equals(r.buildVerification()))throw new ConfigurationException("Resume Journal identity or inputContext is incompatible");if(r.datasetId()==null||r.datasetId().isBlank())throw new ConfigurationException("Resume Journal is missing datasetId");return r;}catch(IOException ex){throw new ConfigurationException("Journal could not be read safely: "+JsonSupport.redact(ex.getMessage()),"resume_journal");}}
    private Execution completeExisting(String mode,String source,JsonNode inputContext,EffectiveCap cap,String runId,String originalDataset,String initialStatus,String actor,String initialBuild,String initialBuildId,String evidence,boolean journalRunCreated){
        long deadline=System.nanoTime()+config.overallDeadline().toNanos();JsonNode run=null;String status=initialStatus;String dataset=originalDataset;String build=initialBuild,buildId=initialBuildId,actorId=actor;String error=null,stage="run_poll";
        try{
            for(int i=0;i<config.maxPolls();i++){
                if(i>0){long left=deadline-System.nanoTime();if(left<=0)break; sleeper.sleep(Duration.ofNanos(Math.min(left,config.pollInterval().toNanos())));}
                if(System.nanoTime()>deadline)break;
                TransportResponse response=sendGet("/actor-runs/"+path(runId),Map.of(),deadline);
                if(response.statusCode()<200||response.statusCode()>=300)throw new IOException("Run query returned HTTP "+response.statusCode());
                run=parseData(response.body(),"run_get",runId,originalDataset);if(!runId.equals(text(run,"id")))throw new IOException("Run GET identity did not match requested Run ID");
                status=text(run,"status");String d=text(run,"defaultDatasetId");if(d!=null){if(dataset!=null&&!dataset.equals(d))throw new IdentityFailure("Run Dataset identity changed");dataset=d;}
                actorId=text(run,"actId","actorId");build=text(run,"buildNumber");buildId=text(run,"buildId");
                if(status!=null&&Set.of("SUCCEEDED","FAILED","TIMED-OUT","ABORTED").contains(status))break;
            }
        }catch(InterruptedException ex){Thread.currentThread().interrupt();error="Run polling interrupted";}catch(IdentityFailure ex){error=ex.getMessage();stage="dataset_identity";}catch(IOException|RuntimeException ex){error="Run polling or identity verification failed";}
        if(error!=null)return finish(mode,source,inputContext,cap,new Execution(Status.TRANSPORT_ERROR,stage,error,runId,dataset,status,actorId,build,buildId,BuildVerification.UNKNOWN,false,false,List.of()));
        if(status==null||!Set.of("SUCCEEDED","FAILED","TIMED-OUT","ABORTED").contains(status))return finish(mode,source,inputContext,cap,new Execution(Status.TRANSPORT_ERROR,"run_poll","Run did not reach a known terminal state before the deadline",runId,dataset,status,actorId,build,buildId,BuildVerification.UNKNOWN,false,false,List.of()));
        try{config.journal().append(record("run_finished",mode,source,runId,actorId,dataset,status,build,buildId,"unknown",cap,inputContext,null));}catch(IOException ex){return new Execution(Status.TRANSPORT_ERROR,"journal_terminal","Run terminal state could not be persisted",runId,dataset,status,actorId,build,buildId,BuildVerification.UNKNOWN,false,false,List.of());}
        if(!"SUCCEEDED".equals(status))return finish(mode,source,inputContext,cap,new Execution(Status.RUN_FAILED,"run_finished","Actor Run finished with status "+status,runId,dataset,status,actorId,build,buildId,BuildVerification.UNVERIFIED,false,false,List.of()));
        if(!ClientConfig.CONTROLLED_BUILD_NUMBER.equals(build)||!ClientConfig.CONTROLLED_BUILD_ID.equals(buildId))return finish(mode,source,inputContext,cap,new Execution(Status.TRANSPORT_ERROR,"build_mismatch","Actor Run Build identity did not match the controlled Build",runId,dataset,status,actorId,build,buildId,BuildVerification.MISMATCH,false,false,List.of()));
        if(dataset==null||dataset.isBlank())return finish(mode,source,inputContext,cap,new Execution(Status.TRANSPORT_ERROR,"dataset_identity","Successful Run did not provide a Dataset ID",runId,dataset,status,actorId,build,buildId,BuildVerification.VERIFIED,false,false,List.of()));
        try{config.journal().append(record("build_verified",mode,source,runId,actorId,dataset,status,build,buildId,"verified",cap,inputContext,null));}catch(IOException ex){return new Execution(Status.TRANSPORT_ERROR,"journal_terminal","Build verification could not be persisted",runId,dataset,status,actorId,build,buildId,BuildVerification.VERIFIED,false,false,List.of());}
        try{TransportResponse response=sendGet("/datasets/"+path(dataset)+"/items",Map.of("limit",Integer.toString(config.datasetPageLimit()),"offset","0"),deadline);if(response.statusCode()<200||response.statusCode()>=300)throw new IOException("Dataset query returned HTTP "+response.statusCode());JsonNode items=JsonSupport.MAPPER.readTree(response.body());if(items==null||!items.isArray())throw new IOException("Dataset response must be a JSON array");
            // Dataset visibility can lag Run completion; retry an empty read twice on this same Dataset.
            for(int emptyAttempt=0;items.isEmpty()&&emptyAttempt<2;emptyAttempt++){
                Duration delay=Duration.ofSeconds(emptyAttempt+1L);if(System.nanoTime()+delay.toNanos()>=deadline)break;sleeper.sleep(delay);
                TransportResponse confirm=sendGet("/datasets/"+path(dataset)+"/items",Map.of("limit",Integer.toString(config.datasetPageLimit()),"offset","0"),deadline);if(confirm.statusCode()<200||confirm.statusCode()>=300)throw new IOException("Dataset confirmation query returned HTTP "+confirm.statusCode());JsonNode second=JsonSupport.MAPPER.readTree(confirm.body());if(second==null||!second.isArray())throw new IOException("Dataset confirmation response must be a JSON array");items=second;
            }
            List<JsonNode> nodes=new ArrayList<>();items.forEach(n->nodes.add(n.deepCopy()));boolean complete=items.size()<config.datasetPageLimit();Execution done=new Execution(Status.SUCCESS,"complete",null,runId,dataset,status,actorId,build,buildId,BuildVerification.VERIFIED,true,complete,List.copyOf(nodes));return finish(mode,source,inputContext,cap,done);}catch(InterruptedException ex){Thread.currentThread().interrupt();return finish(mode,source,inputContext,cap,new Execution(Status.TRANSPORT_ERROR,"dataset_read","Dataset read interrupted",runId,dataset,status,actorId,build,buildId,BuildVerification.VERIFIED,false,false,List.of()));}catch(IOException|RuntimeException ex){return finish(mode,source,inputContext,cap,new Execution(Status.TRANSPORT_ERROR,"dataset_read","Dataset could not be read or parsed",runId,dataset,status,actorId,build,buildId,BuildVerification.VERIFIED,false,false,List.of()));}
    }
    private TransportResponse sendGet(String path,Map<String,String> query,long deadline)throws IOException,InterruptedException{
        IOException last=null;
        for(int attempt=0;attempt<4;attempt++){
            long remaining=deadline-System.nanoTime();if(remaining<=0)throw new IOException("overall deadline exceeded during GET");
            Duration timeout=config.requestTimeout().compareTo(Duration.ofNanos(remaining))<0?config.requestTimeout():Duration.ofNanos(remaining);
            TransportResponse response;
            try{response=transport.send("GET",path,null,query,timeout);}
            catch(IOException ex){last=ex;if(attempt==3)throw ex;pauseBeforeGetRetry(null,attempt,deadline);continue;}
            if(response.statusCode()!=429&&response.statusCode()<500)return response;
            last=new IOException("GET returned HTTP "+response.statusCode());
            if(attempt==3)throw last;
            pauseBeforeGetRetry(response,attempt,deadline);
        }
        throw last==null?new IOException("GET failed"):last;
    }
    private void pauseBeforeGetRetry(TransportResponse response,int attempt,long deadline)throws IOException,InterruptedException{
        long remaining=deadline-System.nanoTime();if(remaining<=0)throw new IOException("overall deadline exceeded during GET retry");
        Duration delay=retryAfter(response);
        if(delay==null){long millis=Math.min(8000L,250L<<attempt);delay=Duration.ofMillis(millis);}
        if(delay.compareTo(Duration.ofNanos(remaining))>0)delay=Duration.ofNanos(remaining);
        sleeper.sleep(delay);
    }
    private static Duration retryAfter(TransportResponse response){
        if(response==null)return null;String raw=response.firstHeader("Retry-After");if(raw==null||raw.isBlank())return null;
        try{long seconds=Long.parseLong(raw.trim());return seconds<0?null:Duration.ofSeconds(seconds);}catch(NumberFormatException ignored){}
        try{Instant when=ZonedDateTime.parse(raw.trim(),DateTimeFormatter.RFC_1123_DATE_TIME).toInstant();Duration delay=Duration.between(Instant.now(),when);return delay.isNegative()?Duration.ZERO:delay;}catch(RuntimeException ignored){return null;}
    }
    private Execution finish(String mode,String source,JsonNode ctx,EffectiveCap cap,Execution e){try{config.journal().append(record(e.status()==Status.TRANSPORT_ERROR&&e.stage().startsWith("build")?"build_mismatch":"complete",mode,source,e.runId(),e.actorId(),e.datasetId(),e.runStatus(),e.buildNumber(),e.buildId(),e.buildVerification().value(),cap,ctx,e.error()));return e;}catch(IOException ex){return new Execution(Status.TRANSPORT_ERROR,"journal_terminal","Final state could not be persisted",e.runId(),e.datasetId(),e.runStatus(),e.actorId(),e.buildNumber(),e.buildId(),e.buildVerification(),false,false,e.items());}}
    private JournalRecord record(String stage,String mode,String source,String runId,String runActor,String dataset,String runStatus,String build,String buildId,String verification,EffectiveCap cap,JsonNode context,String error){return new JournalRecord(config.clock().instant().toString(),stage,mode,config.actorId(),source,runId,runActor,dataset,runStatus,build,buildId,verification,cap.value(),false,context==null?null:context.deepCopy(),error==null?null:JsonSupport.redact(error).substring(0,Math.min(300,JsonSupport.redact(error).length())));}
    private Map<String,String> runQuery(EffectiveCap cap){Map<String,String> q=new LinkedHashMap<>();q.put("build",config.buildNumber());q.put("restartOnError","false");if(cap.value()!=null)q.put("maxTotalChargeUsd",cap.value().toPlainString());return q;}
    private String actorRunsPath(){return "/acts/"+config.actorId().replace("/","~")+"/runs";}
    private static String path(String value){return URLEncoder.encode(value,StandardCharsets.UTF_8).replace("+","%20");}
    private static String text(JsonNode n,String...keys){if(n==null)return null;for(String k:keys){JsonNode v=n.get(k);if(v!=null&&v.isTextual())return v.asText();}return null;}
    private static JsonNode parseData(String body,String stage,String runId,String datasetId){try{JsonNode root=JsonSupport.MAPPER.readTree(body);JsonNode d=root==null?null:root.get("data");if(d==null||!d.isObject())throw new IOException();return d;}catch(Exception e){throw new ProtocolException("Apify returned a malformed response",stage,runId,datasetId);}}

    private TranscriptResult transcriptFailure(Execution e,String url){return new TranscriptResult(e.status(),e.runStatus(),e.runId(),e.datasetId(),url,config.actorId(),e.buildNumber(),e.buildId(),e.buildVerification(),e.stage().equals("run_get")?"run_get":null,e.complete(),e.datasetKnown(),null,List.of(),e.items(),e.error(),e.stage(),AttributionVerification.UNKNOWN);}
    private TranscriptResult classifySingle(Execution e,String url){
        if(e.status()!=Status.SUCCESS)return transcriptFailure(e,url);JsonNode matched=null;AttributionVerification attribution=AttributionVerification.VERIFIED;
        for(JsonNode item:e.items()){
            if(!item.isObject())return transcript(e,url,Status.UNKNOWN,null,List.of(),AttributionVerification.UNKNOWN,"Dataset item was not an object");
            JsonNode rawUrl=item.get("url");if(rawUrl!=null&&!rawUrl.isNull()){if(!rawUrl.isTextual())return transcript(e,url,Status.UNKNOWN,null,List.of(),AttributionVerification.UNKNOWN,"Dataset URL had an unexpected type");try{if(!InputValidators.identity(url).equals(InputValidators.identity(rawUrl.asText())))return transcript(e,url,Status.UNKNOWN,null,List.of(),AttributionVerification.MISMATCH,"Dataset URL did not match requested input");}catch(RuntimeException ex){return transcript(e,url,Status.UNKNOWN,null,List.of(),AttributionVerification.UNKNOWN,"Dataset URL was invalid");}}else attribution=AttributionVerification.UNKNOWN;
            if(matched==null)matched=item;
        }
        if(matched==null)return transcript(e,url,e.complete()?Status.EMPTY:Status.UNKNOWN,null,List.of(),AttributionVerification.UNKNOWN,e.complete()?null:"Dataset completeness is unknown");
        Classification c=classifyTranscriptItem(matched);return transcript(e,url,c.status(),c.text(),c.segments(),attribution,c.error());
    }
    private static Classification classifyTranscriptItem(JsonNode item){JsonNode err=item.get("errMsg");if(err!=null&&!err.isNull()){if(!err.isTextual())return new Classification(Status.UNKNOWN,null,List.of(),"errMsg had an unexpected non-string type");if(!err.asText().isBlank())return new Classification(Status.ACTOR_ERROR,null,List.of(),err.asText());}JsonNode text=item.get("text");if(text==null||text.isNull())return new Classification(Status.NO_TRANSCRIPT,null,List.of(),null);if(!text.isTextual())return new Classification(Status.UNKNOWN,null,List.of(),"Transcript text had an unexpected type");if(text.asText().isBlank())return new Classification(Status.NO_TRANSCRIPT,null,List.of(),null);List<JsonNode> segments=new ArrayList<>();JsonNode s=item.get("segments");if(s!=null&&s.isArray())s.forEach(x->segments.add(x.deepCopy()));return new Classification(Status.SUCCESS,text.asText(),List.copyOf(segments),null);}
    private TranscriptResult transcript(Execution e,String url,Status s,String text,List<JsonNode> segments,AttributionVerification a,String error){if(!e.complete()&&s==Status.SUCCESS)s=Status.UNKNOWN;return new TranscriptResult(s,e.runStatus(),e.runId(),e.datasetId(),url,config.actorId(),e.buildNumber(),e.buildId(),e.buildVerification(),"run_get",e.complete(),e.datasetKnown(),s==Status.SUCCESS?text:null,s==Status.SUCCESS?segments:List.of(),e.items(),error,e.stage(),a);}
    private BulkResult classifyBulk(Execution e,List<String> urls){List<JsonNode> items=e.items();Map<String,List<JsonNode>> assigned=new HashMap<>();List<ExtraResult> extras=new ArrayList<>();Map<String,String> byCode=new HashMap<>();Set<String> ambiguous=new java.util.HashSet<>();for(String url:urls){String code=InputValidators.shortcode(url);String prev=byCode.putIfAbsent(code,url);if(prev!=null&&!prev.equals(url))ambiguous.add(code);}
        for(JsonNode item:items){if(!item.isObject()){extras.add(new ExtraResult("unknown","dataset_item_not_object",item));continue;}JsonNode u=item.get("url"),codeNode=item.get("code");String target=null,reason=null;
            if(u!=null&&!u.isNull()){if(!u.isTextual()){reason="invalid_output_url";}else try{String identity=InputValidators.identity(u.asText());for(String url:urls)if(InputValidators.identity(url).equals(identity)){target=url;break;}if(target==null)reason="output_url_not_in_input";if(codeNode!=null&&codeNode.isTextual()&&!InputValidators.shortcode(target==null?urls.get(0):target).equals(codeNode.asText())&&target!=null){reason="url_code_conflict";target=null;}}catch(RuntimeException ex){reason="invalid_output_url";}}
            else if(codeNode!=null&&codeNode.isTextual()){String code=codeNode.asText();if(ambiguous.contains(code))reason="ambiguous_url_code_mapping";else target=byCode.get(code);if(target==null&&reason==null)reason="missing_or_ambiguous_shortcode";}else reason="missing_mapping_identity";
            if(target==null)extras.add(new ExtraResult("unknown",reason==null?"unmapped_output":reason,item));else assigned.computeIfAbsent(target,k->new ArrayList<>()).add(item);
        }
        EnumMap<BulkItemStatus,Integer> counts=new EnumMap<>(BulkItemStatus.class);for(BulkItemStatus s:BulkItemStatus.values())counts.put(s,0);List<BulkInputResult> rows=new ArrayList<>();int success=0,knownFail=0;boolean unknown=!e.complete()||!extras.isEmpty()||e.status()!=Status.SUCCESS;
        for(String url:urls){List<JsonNode> found=assigned.getOrDefault(url,List.of());BulkItemStatus status;JsonNode item=null;String err=null,text=null;List<JsonNode> seg=List.of();List<JsonNode> rowItems=List.copyOf(found);
            if(e.status()!=Status.SUCCESS){status=BulkItemStatus.UNKNOWN;err=e.error();}
            else if(found.size()>1)status=BulkItemStatus.DUPLICATE_RESULT;
            else if(found.isEmpty())status=e.complete()?BulkItemStatus.MISSING_RESULT:BulkItemStatus.UNKNOWN;
            else{item=found.get(0);Classification c=classifyTranscriptItem(item);status=switch(c.status()){case SUCCESS->BulkItemStatus.SUCCESS_TRANSCRIPT;case ACTOR_ERROR->BulkItemStatus.ACTOR_ERROR;case NO_TRANSCRIPT,EMPTY->BulkItemStatus.NO_TRANSCRIPT;default->BulkItemStatus.UNKNOWN;};text=c.text();seg=c.segments();err=c.error();}
            counts.merge(status,1,Integer::sum);if(status==BulkItemStatus.SUCCESS_TRANSCRIPT)success++;else if(status==BulkItemStatus.UNKNOWN)unknown=true;else knownFail++;
            rows.add(new BulkInputResult(url,status,text,seg,rowItems,err));
        }
        BulkStatus overall=unknown?BulkStatus.UNKNOWN:success==urls.size()?BulkStatus.ALL_SUCCESS:success>0?BulkStatus.PARTIAL_SUCCESS:BulkStatus.ALL_FAILED;
        Status execution=e.status()==Status.SUCCESS?Status.SUCCESS:e.status();AttributionVerification attr=unknown?AttributionVerification.UNKNOWN:AttributionVerification.VERIFIED;
        return new BulkResult(overall,execution,List.copyOf(rows),List.copyOf(extras),Map.copyOf(counts),e.runId(),e.datasetId(),e.complete(),items,attr,e.error(),e.stage());
    }
    private ProfileResult classifyProfile(Execution e,List<String> usernames){if(e.status()==Status.RUN_FAILED)return new ProfileResult(ProfileStatus.RUN_FAILED,Status.RUN_FAILED,List.of(),usernames,e.runId(),e.datasetId(),false,e.error(),e.items());if(e.status()!=Status.SUCCESS)return new ProfileResult(ProfileStatus.UNKNOWN,e.status(),List.of(),usernames,e.runId(),e.datasetId(),false,e.error(),e.items());List<ProfilePost> posts=new ArrayList<>();boolean unknown=!e.complete(),actorError=false;for(JsonNode item:e.items()){if(!item.isObject()){unknown=true;continue;}JsonNode err=item.get("errMsg");if(err!=null&&!err.isNull()){if(!err.isTextual()){unknown=true;continue;}if(!err.asText().isBlank()){actorError=true;posts.add(new ProfilePost(text(item,"url"),text(item,"type"),text(item,"ownerUsername"),text(item,"caption"),item.get("timestamp"),text(item,"videoUrl"),item.get("videoDuration"),"actor_error",item,null));continue;}}
            String owner=text(item,"ownerUsername");boolean ownerConflict=owner!=null&&usernames.stream().noneMatch(owner::equals);if(ownerConflict||owner==null&&usernames.size()>1){unknown=true;posts.add(new ProfilePost(text(item,"url"),text(item,"type"),owner,text(item,"caption"),item.get("timestamp"),text(item,"videoUrl"),item.get("videoDuration"),"unknown",item,"Profile owner could not be verified"));}else posts.add(new ProfilePost(text(item,"url"),text(item,"type"),owner,text(item,"caption"),item.get("timestamp"),text(item,"videoUrl"),item.get("videoDuration"),"success",item,null));}
        ProfileStatus s=unknown?ProfileStatus.UNKNOWN:actorError?ProfileStatus.ACTOR_ERROR:posts.isEmpty()?ProfileStatus.EMPTY:ProfileStatus.SUCCESS;return new ProfileResult(s,Status.SUCCESS,List.copyOf(posts),usernames,e.runId(),e.datasetId(),e.complete(),unknown&&!e.complete()?"Dataset completeness is unknown":null,e.items());}
    private static CsvRowResult csvError(CsvRow r,Status s,TranscriptClientException ex){return new CsvRowResult(r.rowNumber(),r.url(),s,ex.runId(),ex.datasetId(),null,List.of(),0,List.of(),null,JsonSupport.redact(ex.getMessage()));}
    private static List<JsonNode> flattenRaw(List<CsvRowResult> rows){List<JsonNode> out=new ArrayList<>();for(CsvRowResult r:rows)out.addAll(r.rawItems());return List.copyOf(out);}
    private static String csvStatus(List<CsvRowResult> rows,boolean stopped){if(stopped)return "stopped_unknown";if(rows.isEmpty())return "empty";long success=rows.stream().filter(r->r.status()==Status.SUCCESS).count();if(success==rows.size())return "all_success";if(success>0)return "partial_success";return "all_failed";}
    private record EffectiveCap(BigDecimal value,boolean required){}
    private record Classification(Status status,String text,List<JsonNode> segments,String error){}
    private record Execution(Status status,String stage,String error,String runId,String datasetId,String runStatus,String actorId,String buildNumber,String buildId,BuildVerification buildVerification,boolean datasetKnown,boolean complete,List<JsonNode> items){Execution{if(items==null)items=List.of();if(stage==null)stage="";if(status==null)status=Status.UNKNOWN;if(buildVerification==null)buildVerification=BuildVerification.UNKNOWN;}}
    private static final class IdentityFailure extends IOException {IdentityFailure(String message){super(message);}}
}
