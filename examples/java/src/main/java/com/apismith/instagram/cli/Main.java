package com.apismith.instagram.cli;

import com.apismith.instagram.transcriptapi.*;
import com.fasterxml.jackson.databind.JsonNode;
import java.io.PrintStream;
import java.math.BigDecimal;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.util.ArrayList;
import java.util.AbstractMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Testable CLI entry point. It never loads .env or exits the JVM from run(). */
public final class Main {
    private static final String HELP="""
        Instagram Reels Transcript API Java CLI
        Usage: java -jar target/instagram-reels-transcript-api-java-examples-0.1.0-shaded.jar <single|bulk|profile|csv> [options]
          single <url> | single --resume <runId>
          bulk <url>... | bulk --resume <runId> <url>...
          profile <username>...
          csv <path> [--execute|--dry-run]
        Global options: --output-dir <dir> --journal <path> --max-total-charge-usd <decimal> --require-charge-cap
        Bulk/Profile: --results-limit <n> --skip-pinned-posts true|false --include-shares-count true|false
        Profile: --only-posts-newer-than <YYYY-MM-DD|N days>
        CSV is plan-only by default; only --execute may create independent Runs.
        """;
    private Main(){}
    public static void main(String[] args){int code=run(args,processEnvironment(),System.out,System.err,Dependencies.defaults());if(code!=0)System.exit(code);}
    /** Resolve only requested variables, lazily. In particular CSV plan/help never reads APIFY_TOKEN. */
    private static Map<String,String> processEnvironment(){return new AbstractMap<>(){@Override public String get(Object key){return key instanceof String name?System.getenv(name):null;}@Override public java.util.Set<Entry<String,String>> entrySet(){return java.util.Set.of();}};}
    public static int run(String[] args,Map<String,String> env,PrintStream out,PrintStream err){return run(args,env,out,err,Dependencies.defaults());}
    public static int run(String[] args,Map<String,String> env,PrintStream out,PrintStream err,Dependencies dependencies){
        try {
            Parsed p=parse(args==null?new String[0]:args);
            if(p.help()){out.println(HELP);return 0;}if(p.version()){out.println("0.1.0");return 0;}
            if(p.command()==null)throw new ConfigurationException("command is required; use --help");
            return switch(p.command()){
                case "single" -> single(p,env,out,err,dependencies);
                case "bulk" -> bulk(p,env,out,err,dependencies);
                case "profile" -> profile(p,env,out,err,dependencies);
                case "csv" -> csv(p,env,out,err,dependencies);
                default -> throw new ConfigurationException("unsupported command: "+p.command());
            };
        }catch(CreationUnknownException e){return failure(err,"CreationUnknownException",e,10);}
        catch(ConfigurationException e){return failure(err,"ConfigurationException",e,2);}
        catch(TranscriptClientException e){int code="run_failed".equals(e.stage())?9:8;return failure(err,e.getClass().getSimpleName(),e,code);}
        catch(Exception e){return failure(err,"Error",new RuntimeException(JsonSupport.redact(e.getMessage())),8);}
    }
    private static int single(Parsed p,Map<String,String> env,PrintStream out,PrintStream err,Dependencies dep)throws Exception{
        requireOptions(p,"output-dir","journal","max-total-charge-usd","require-charge-cap","resume");boolean resume=p.options().containsKey("resume");if(resume&&!p.positionals().isEmpty())throw new ConfigurationException("single --resume cannot be combined with a URL");if(!resume&&p.positionals().size()!=1)throw new ConfigurationException("single requires exactly one explicit Reel URL");
        if(!resume)InputValidators.validateVideoUrl(p.positionals().get(0));
        ClientAndPaths cp=client(p,env,dep,true);TranscriptResult r=resume?cp.client().resumeTranscript(p.options().get("resume")):cp.client().getTranscript(p.positionals().get(0));
        Path file=OutputFiles.writeUnique(cp.outputDir(),"java-single-url",OutputFiles.singleDocument(r),cp.clock());Map<String,Object> summary=new LinkedHashMap<>();summary.put("status",r.status());summary.put("runId",r.runId());summary.put("datasetId",r.datasetId());summary.put("outputFile",file.toString());int code=singleCode(r.status());if(code==0)out.println(JsonSupport.MAPPER.writeValueAsString(summary));else err.println("ResultStatus: "+r.status()+"; outputFile="+file);return code;
    }
    private static int bulk(Parsed p,Map<String,String> env,PrintStream out,PrintStream err,Dependencies dep)throws Exception{
        requireOptions(p,"output-dir","journal","max-total-charge-usd","require-charge-cap","resume","results-limit","skip-pinned-posts","include-shares-count");List<String> urls=p.positionals();boolean resume=p.options().containsKey("resume");if(resume&&urls.isEmpty())throw new ConfigurationException("bulk --resume requires the original URL list");if(!resume&&urls.isEmpty())throw new ConfigurationException("bulk requires one or more explicit URLs");urls=InputValidators.validateBulkInput(urls);BulkOptions opts=new BulkOptions(integer(p.options(),"results-limit"),bool(p.options(),"skip-pinned-posts"),bool(p.options(),"include-shares-count"));ClientAndPaths cp=client(p,env,dep,true);BulkResult r=resume?cp.client().resumeTranscripts(p.options().get("resume"),urls,opts):cp.client().getTranscripts(urls,opts);
        Map<String,Object> doc=new LinkedHashMap<>();doc.put("schemaVersion",1);doc.put("mode","native_bulk");doc.put("status",r.status());doc.put("executionStatus",r.executionStatus());doc.put("runId",r.runId());doc.put("datasetId",r.datasetId());doc.put("datasetComplete",r.datasetComplete());doc.put("attributionVerification",r.attributionVerification());Map<String,Integer> counts=new LinkedHashMap<>();for(BulkItemStatus s:BulkItemStatus.values())counts.put(s.value(),r.counts().getOrDefault(s,0));doc.put("counts",counts);doc.put("results",r.results());doc.put("extras",r.extras());doc.put("rawItems",r.rawItems());doc.put("error",r.error());doc.put("stage",r.stage());Path file=OutputFiles.writeUnique(cp.outputDir(),"java-native-bulk",doc,cp.clock());int code=bulkCode(r);if(code==0)out.println(JsonSupport.MAPPER.writeValueAsString(Map.of("status",r.status(),"runId",nullSafe(r.runId()),"datasetId",nullSafe(r.datasetId()),"outputFile",file.toString())));else err.println("ResultStatus: "+r.status()+"; outputFile="+file);return code;
    }
    private static int profile(Parsed p,Map<String,String> env,PrintStream out,PrintStream err,Dependencies dep)throws Exception{
        requireOptions(p,"output-dir","journal","max-total-charge-usd","require-charge-cap","results-limit","skip-pinned-posts","include-shares-count","only-posts-newer-than");if(p.positionals().isEmpty())throw new ConfigurationException("profile requires one or more explicit usernames");List<String> names=InputValidators.validateUsernames(p.positionals());ProfileOptions opts=new ProfileOptions(integer(p.options(),"results-limit"),p.options().get("only-posts-newer-than"),bool(p.options(),"skip-pinned-posts"),bool(p.options(),"include-shares-count"));ClientAndPaths cp=client(p,env,dep,true);ProfileResult r=cp.client().getProfilePosts(names,opts);Map<String,Object> doc=new LinkedHashMap<>();doc.put("schemaVersion",1);doc.put("mode","profile_posts");doc.put("status",r.status());doc.put("executionStatus",r.executionStatus());doc.put("runId",r.runId());doc.put("datasetId",r.datasetId());doc.put("datasetComplete",r.datasetComplete());doc.put("usernames",r.usernames());doc.put("posts",r.posts());doc.put("rawItems",r.rawItems());doc.put("error",r.error());Path file=OutputFiles.writeUnique(cp.outputDir(),"java-profile",doc,cp.clock());int code=profileCode(r);if(code==0)out.println(JsonSupport.MAPPER.writeValueAsString(Map.of("status",r.status(),"postCount",r.posts().size(),"outputFile",file.toString())));else err.println("ResultStatus: "+r.status()+"; outputFile="+file);return code;
    }
    private static int csv(Parsed p,Map<String,String> env,PrintStream out,PrintStream err,Dependencies dep)throws Exception{
        requireOptions(p,"output-dir","journal","max-total-charge-usd","require-charge-cap","execute","dry-run");if(p.positionals().size()!=1)throw new ConfigurationException("csv requires exactly one CSV path");if(p.options().containsKey("execute")&&p.options().containsKey("dry-run"))throw new ConfigurationException("choose only one of --execute or --dry-run");Path csvPath=Path.of(p.positionals().get(0)).toAbsolutePath().normalize();List<CsvRow> rows=CsvParser.read(csvPath);
        if(!p.options().containsKey("execute")){BigDecimal c=selectedCap(p,env);boolean required=requireCap(p,env);if(required&&(c==null||c.signum()<=0))throw new ConfigurationException("a positive charge cap is required before any Run");BigDecimal total=c==null?null:c.multiply(BigDecimal.valueOf(rows.size())).setScale(2,java.math.RoundingMode.CEILING);Map<String,Object> plan=new LinkedHashMap<>();plan.put("mode","csv_batch_plan");plan.put("rows",rows.size());plan.put("maximumActorRuns",rows.size());plan.put("concurrency",1);plan.put("actorBuild",env.getOrDefault("APIFY_BUILD",ClientConfig.CONTROLLED_BUILD_NUMBER));plan.put("requireChargeCap",required);if(c!=null&&c.signum()>0){plan.put("perRunCapUsd",c.toPlainString());plan.put("estimatedMaximumRunCapsTotalUsd",total.toPlainString());}plan.put("csvPath",csvPath.toString());out.println(JsonSupport.MAPPER.writeValueAsString(plan));return 0;}
        ClientAndPaths cp=client(p,env,dep,true);CsvBatchResult r=cp.client().getTranscriptsFromCsv(rows);Map<String,Object> doc=new LinkedHashMap<>();doc.put("schemaVersion",1);doc.put("mode","csv_batch_independent_runs");doc.put("recordedAt",cp.clock().instant().toString());doc.put("status",r.status());doc.put("stopped",r.stopped());doc.put("plannedRows",r.plannedRows());doc.put("processedRows",r.processedRows());doc.put("unattemptedRows",r.unattemptedRows());doc.put("concurrency",1);doc.put("counts",r.counts());doc.put("rows",r.rows());doc.put("rawItems",r.rawItems());doc.put("error",r.error());Path file=OutputFiles.writeUnique(cp.outputDir(),"java-csv-batch",doc,cp.clock());int code=csvCode(r);if(code==0)out.println(JsonSupport.MAPPER.writeValueAsString(Map.of("status",r.status(),"processedRows",r.processedRows(),"outputFile",file.toString())));else err.println("ResultStatus: "+r.status()+"; outputFile="+file);return code;
    }
    private static ClientAndPaths client(Parsed p,Map<String,String> env,Dependencies dep,boolean persistent)throws Exception{
        String token=env.get("APIFY_TOKEN");if(token==null||token.isBlank())throw new ConfigurationException("APIFY_TOKEN is required in the process environment; .env is not loaded");String actor=env.getOrDefault("APIFY_ACTOR_ID",ClientConfig.DEFAULT_ACTOR_ID);String build=env.getOrDefault("APIFY_BUILD",ClientConfig.CONTROLLED_BUILD_NUMBER);if(!ClientConfig.CONTROLLED_BUILD_NUMBER.equals(build))throw new ConfigurationException("APIFY_BUILD must be the controlled Build 0.0.50");BigDecimal cap=selectedCap(p,env);boolean require=requireCap(p,env);if(require&&(cap==null||cap.signum()<=0))throw new ConfigurationException("a positive charge cap is required before any Run");
        Path outDir=Path.of(p.options().getOrDefault("output-dir","sample-output/generated")).toAbsolutePath().normalize();Path journalPath=Path.of(p.options().getOrDefault("journal",outDir.resolve("java-run-journal.jsonl").toString())).toAbsolutePath().normalize();Journal journal=dep.journal()!=null?dep.journal():persistent?JsonlFileJournal.open(journalPath):new InMemoryJournal();Clock clock=dep.clock()==null?Clock.systemUTC():dep.clock();ClientConfig.Builder b=ClientConfig.builder().token(token).actorId(actor).buildNumber(build).buildId(ClientConfig.CONTROLLED_BUILD_ID).maxTotalChargeUsd(cap).requireChargeCap(require).journal(journal).clock(clock).sessionId(env.get("INSTAGRAM_SESSIONID"));if(dep.transport()!=null)b.transport(dep.transport());if(dep.sleeper()!=null)b.sleeper(dep.sleeper());return new ClientAndPaths(new TranscriptClient(b.build()),outDir,clock);
    }
    private static BigDecimal selectedCap(Parsed p,Map<String,String> env){String raw=p.options().getOrDefault("max-total-charge-usd",env.get("APIFY_MAX_TOTAL_CHARGE_USD"));if(raw==null||raw.isBlank())return null;try{BigDecimal b=new BigDecimal(raw);if(b.signum()<=0)throw new NumberFormatException();return b;}catch(NumberFormatException e){throw new ConfigurationException("max-total-charge-usd must be a positive decimal");}}
    private static boolean requireCap(Parsed p,Map<String,String> env){if(p.options().containsKey("require-charge-cap"))return true;String v=env.get("APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD");if(v==null||v.isBlank())return false;if("1".equals(v))return true;if("0".equals(v))return false;throw new ConfigurationException("APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD must be 1 or 0");}
    private static Integer integer(Map<String,String> opts,String name){String v=opts.get(name);if(v==null)return null;try{int n=Integer.parseInt(v);if(n<1)throw new NumberFormatException();return n;}catch(NumberFormatException e){throw new ConfigurationException("--"+name+" must be a positive integer");}}
    private static Boolean bool(Map<String,String> o,String n){String v=o.get(n);if(v==null)return null;if("true".equals(v))return true;if("false".equals(v))return false;throw new ConfigurationException("--"+n+" must be true or false");}
    private static void requireOptions(Parsed p,String... allowed){List<String> a=List.of(allowed);for(String k:p.options().keySet())if(!a.contains(k))throw new ConfigurationException("option --"+k+" is not supported for "+p.command());}
    private static int failure(PrintStream err,String type,Throwable e,int code){String message=JsonSupport.redact(e.getMessage()==null?"operation failed":e.getMessage()).replace('\n',' ');err.println(type+": "+message);return code;}
    private static int singleCode(Status s){return switch(s){case SUCCESS->0;case ACTOR_ERROR->4;case EMPTY->5;case NO_TRANSCRIPT->6;case UNKNOWN->7;case TRANSPORT_ERROR->8;case RUN_FAILED->9;case CREATION_UNKNOWN->10;default->7;};}
    private static int bulkCode(BulkResult r){if(r.executionStatus()!=Status.SUCCESS)return singleCode(r.executionStatus());return switch(r.status()){case ALL_SUCCESS->0;case PARTIAL_SUCCESS->11;case ALL_FAILED->12;case UNKNOWN->13;};}
    private static int profileCode(ProfileResult r){if(r.executionStatus()!=Status.SUCCESS)return singleCode(r.executionStatus());return switch(r.status()){case SUCCESS->0;case ACTOR_ERROR->4;case EMPTY->5;case UNKNOWN->7;case RUN_FAILED->9;};}
    private static int csvCode(CsvBatchResult r){if("all_success".equals(r.status())||"empty".equals(r.status()))return 0;int code=11;for(CsvRowResult row:r.rows()){int c=switch(row.status()){case CREATION_UNKNOWN->10;case RUN_FAILED->9;case TRANSPORT_ERROR,STOPPED_UNKNOWN->8;default->11;};if(c==10)return 10;if(c==9)code=Math.min(code,9);else if(c==8&&code>8)code=8;}return code;}
    private static String nullSafe(String v){return v==null?"":v;}

    private static Parsed parse(String[] args){String command=null;Map<String,String> opts=new LinkedHashMap<>();List<String> pos=new ArrayList<>();boolean help=false,version=false,end=false;
        for(int i=0;i<args.length;i++){String a=args[i];if(command==null){if(a.equals("--help")||a.equals("-h")){help=true;continue;}if(a.equals("--version")){version=true;continue;}if(a.startsWith("-"))throw new ConfigurationException("command must precede options");command=a;continue;}
            if(end){pos.add(a);continue;}if("--".equals(a)){end=true;continue;}if("--help".equals(a)||"-h".equals(a)){help=true;continue;}if("--version".equals(a)){version=true;continue;}if(!a.startsWith("--")){pos.add(a);continue;}String name=a.substring(2);if(SetFlags.FLAG_OPTIONS.contains(name)){if(opts.putIfAbsent(name,"true")!=null)throw new ConfigurationException("duplicate option --"+name);continue;}if(i+1>=args.length||args[i+1].startsWith("--"))throw new ConfigurationException("option --"+name+" requires a value");if(opts.putIfAbsent(name,args[++i])!=null)throw new ConfigurationException("duplicate option --"+name);
        }return new Parsed(command,Map.copyOf(opts),List.copyOf(pos),help,version);}
    private record Parsed(String command,Map<String,String> options,List<String> positionals,boolean help,boolean version){}
    private record ClientAndPaths(TranscriptClient client,Path outputDir,Clock clock){}
    /** Public dependency seam for completely offline CLI tests and embedding applications. */
    public record Dependencies(Transport transport,Journal journal,Clock clock,Sleeper sleeper){public static Dependencies defaults(){return new Dependencies(null,null,null,null);}}
    private static final class SetFlags{static final java.util.Set<String> FLAG_OPTIONS=java.util.Set.of("require-charge-cap","execute","dry-run");}
}
