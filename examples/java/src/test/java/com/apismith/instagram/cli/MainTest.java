package com.apismith.instagram.cli;

import com.apismith.instagram.transcriptapi.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.api.io.TempDir;
import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;

class MainTest {
    @TempDir Path temp;
    static final String URL="https://www.instagram.com/reel/abc/";
    static final class Env extends HashMap<String,String>{final AtomicInteger tokenReads=new AtomicInteger();@Override public String get(Object k){if("APIFY_TOKEN".equals(k))tokenReads.incrementAndGet();return super.get(k);}}
    private static TestTransport good(){return TestTransport.successful("[{\"url\":\"https://www.instagram.com/reel/abc/\",\"text\":\"ok\"}]");}
    private int run(String[] args,Map<String,String> env,TestTransport t,ByteArrayOutputStream stdout,ByteArrayOutputStream stderr){return Main.run(args,env,new PrintStream(stdout),new PrintStream(stderr),new Main.Dependencies(t,new InMemoryJournal(),java.time.Clock.systemUTC(),d->{}));}
    @Test void helpDoesNotReadToken(){var env=new Env();var o=new ByteArrayOutputStream();assertEquals(0,run(new String[]{"--help"},env,new TestTransport(),o,new ByteArrayOutputStream()));assertEquals(0,env.tokenReads.get());}
    @Test void versionDoesNotReadToken(){var env=new Env();assertEquals(0,run(new String[]{"--version"},env,new TestTransport(),new ByteArrayOutputStream(),new ByteArrayOutputStream()));assertEquals(0,env.tokenReads.get());}
    @Test void singleMissingUrlExitsTwoBeforeTokenRead(){var env=new Env();var err=new ByteArrayOutputStream();assertEquals(2,run(new String[]{"single"},env,new TestTransport(),new ByteArrayOutputStream(),err));assertEquals(0,env.tokenReads.get());}
    @Test void singleRejectsMultipleUrlsBeforeTokenRead(){var env=new Env();assertEquals(2,run(new String[]{"single",URL,URL},env,new TestTransport(),new ByteArrayOutputStream(),new ByteArrayOutputStream()));assertEquals(0,env.tokenReads.get());}
    @Test void singleRejectsInvalidUrlBeforeTokenRead(){var env=new Env();assertEquals(2,run(new String[]{"single","https://evil.test/reel/a/"},env,new TestTransport(),new ByteArrayOutputStream(),new ByteArrayOutputStream()));assertEquals(0,env.tokenReads.get());}
    @Test void profileMissingUsernamesExitsTwoBeforeTokenRead(){var env=new Env();assertEquals(2,run(new String[]{"profile"},env,new TestTransport(),new ByteArrayOutputStream(),new ByteArrayOutputStream()));assertEquals(0,env.tokenReads.get());}
    @Test void unsupportedProfileResumeFailsBeforeTokenRead(){var env=new Env();assertEquals(2,run(new String[]{"profile","alice","--resume","R1"},env,new TestTransport(),new ByteArrayOutputStream(),new ByteArrayOutputStream()));assertEquals(0,env.tokenReads.get());}
    @Test void csvPathRequiredBeforeTokenRead(){var env=new Env();assertEquals(2,run(new String[]{"csv"},env,new TestTransport(),new ByteArrayOutputStream(),new ByteArrayOutputStream()));assertEquals(0,env.tokenReads.get());}
    @Test void csvDefaultsToDryRunAndNeverReadsToken()throws Exception{Path csv=temp.resolve("input.csv");Files.writeString(csv,"videoUrl\n"+URL+"\n");var env=new Env();var out=new ByteArrayOutputStream();assertEquals(0,run(new String[]{"csv",csv.toString()},env,new TestTransport(),out,new ByteArrayOutputStream()));assertEquals(0,env.tokenReads.get());assertTrue(out.toString().contains("maximumActorRuns"));}
    @Test void csvDryRunDoesNotPostEvenWithSyntheticToken()throws Exception{Path csv=temp.resolve("input.csv");Files.writeString(csv,"url\n"+URL+"\n");var env=new Env();env.put("APIFY_TOKEN","synthetic");var t=new TestTransport();assertEquals(0,run(new String[]{"csv",csv.toString()},env,t,new ByteArrayOutputStream(),new ByteArrayOutputStream()));assertEquals(0,t.posts);}
    @Test void csvDryRunValidatesAllRowsWithoutToken()throws Exception{Path csv=temp.resolve("input.csv");Files.writeString(csv,"url\n"+URL+"\nhttp://bad.test/x\n");var env=new Env();assertEquals(2,run(new String[]{"csv",csv.toString()},env,new TestTransport(),new ByteArrayOutputStream(),new ByteArrayOutputStream()));assertEquals(0,env.tokenReads.get());}
    @Test void singleCliReturnsSummaryAndUniqueFile()throws Exception{var env=new Env();env.put("APIFY_TOKEN","synthetic");var out=new ByteArrayOutputStream();var t=good();assertEquals(0,run(new String[]{"single",URL,"--output-dir",temp.toString()},env,t,out,new ByteArrayOutputStream()));assertEquals(1,t.posts);assertTrue(out.toString().contains("runId"));assertEquals(1,Files.list(temp).count());}
    @Test void capRequiredFlagWithoutCapBlocksBeforePost(){var env=new Env();env.put("APIFY_TOKEN","synthetic");var t=new TestTransport();assertEquals(2,run(new String[]{"single",URL,"--require-charge-cap"},env,t,new ByteArrayOutputStream(),new ByteArrayOutputStream()));assertEquals(0,t.posts);}
    @Test void capInEnvIsPassedToQuery(){var env=new Env();env.put("APIFY_TOKEN","synthetic");env.put("APIFY_REQUIRE_MAX_TOTAL_CHARGE_USD","1");env.put("APIFY_MAX_TOTAL_CHARGE_USD","0.10");var t=good();assertEquals(0,run(new String[]{"single",URL,"--output-dir",temp.toString()},env,t,new ByteArrayOutputStream(),new ByteArrayOutputStream()));assertEquals("0.10",t.calls.get(0).query().get("maxTotalChargeUsd"));}
    @Test void duplicateCliOptionIsRejectedBeforePost(){var env=new Env();env.put("APIFY_TOKEN","synthetic");var t=new TestTransport();assertEquals(2,run(new String[]{"single",URL,"--max-total-charge-usd","0.1","--max-total-charge-usd","0.2"},env,t,new ByteArrayOutputStream(),new ByteArrayOutputStream()));assertEquals(0,t.posts);}

    @ParameterizedTest @CsvSource({"empty,5","no_transcript,6","actor_error,4","unknown,7"}) void singleExitCodesMatchPublicStatus(String kind,int expected)throws Exception{var env=new Env();env.put("APIFY_TOKEN","synthetic");String item=switch(kind){case "empty"->"[]";case "no_transcript"->"[{\"url\":\"https://www.instagram.com/reel/abc/\",\"text\":null}]";case "actor_error"->"[{\"url\":\"https://www.instagram.com/reel/abc/\",\"errMsg\":\"blocked\"}]";default->"[{\"url\":\"https://www.instagram.com/reel/abc/\",\"text\":7}]";};var t=TestTransport.successful(item);if("empty".equals(kind))t.reply(200,"[]").reply(200,"[]");assertEquals(expected,run(new String[]{"single",URL,"--output-dir",temp.toString()},env,t,new ByteArrayOutputStream(),new ByteArrayOutputStream()));}
    @Test void profileSuccessDoesNotRequireTranscriptFields()throws Exception{var env=new Env();env.put("APIFY_TOKEN","synthetic");var t=TestTransport.successful("[{\"ownerUsername\":\"alice\",\"type\":\"Video\"}]");var out=new ByteArrayOutputStream();assertEquals(0,run(new String[]{"profile","alice","--output-dir",temp.toString()},env,t,out,new ByteArrayOutputStream()));assertTrue(out.toString().contains("postCount"));}
    @Test void bulkCliUsesOneCreationForSeveralUrls()throws Exception{var env=new Env();env.put("APIFY_TOKEN","synthetic");var t=TestTransport.successful("[{\"url\":\"https://www.instagram.com/reel/a/\",\"text\":\"a\"},{\"url\":\"https://www.instagram.com/reel/b/\",\"text\":\"b\"}]");assertEquals(0,run(new String[]{"bulk","https://www.instagram.com/reel/a/","https://www.instagram.com/reel/b/","--output-dir",temp.toString()},env,t,new ByteArrayOutputStream(),new ByteArrayOutputStream()));assertEquals(1,t.posts);}
    @Test void errorOutputDoesNotEchoToken(){var env=new Env();env.put("APIFY_TOKEN","synthetic-secret");var t=new TestTransport().fail(new java.io.IOException("Authorization: Bearer synthetic-secret"));var err=new ByteArrayOutputStream();assertEquals(10,run(new String[]{"single",URL},env,t,new ByteArrayOutputStream(),err));assertFalse(err.toString().contains("synthetic-secret"));}
}
