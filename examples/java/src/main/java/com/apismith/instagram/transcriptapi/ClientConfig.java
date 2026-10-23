package com.apismith.instagram.transcriptapi;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Duration;
import java.util.Objects;

public final class ClientConfig {
    public static final String DEFAULT_ACTOR_ID="apple_yang/instagram-transcripts-scraper";
    public static final String CONTROLLED_BUILD_NUMBER="0.0.50";
    public static final String CONTROLLED_BUILD_ID="aJLRmMdQapLQRT4sJ";
    private final String token, actorId, buildNumber, buildId, sessionId;
    private final BigDecimal maxTotalChargeUsd;
    private final boolean requireChargeCap;
    private final Duration requestTimeout, overallDeadline, pollInterval;
    private final int datasetPageLimit, maxPolls;
    private final Journal journal;
    private final Transport transport;
    private final Sleeper sleeper;
    private final Clock clock;

    private ClientConfig(Builder b) {
        token=b.token; actorId=b.actorId; buildNumber=b.buildNumber; buildId=b.buildId; sessionId=b.sessionId;
        maxTotalChargeUsd=b.maxTotalChargeUsd; requireChargeCap=b.requireChargeCap;
        requestTimeout=b.requestTimeout; overallDeadline=b.overallDeadline; pollInterval=b.pollInterval;
        datasetPageLimit=b.datasetPageLimit; maxPolls=b.maxPolls;
        journal=b.journal == null ? new InMemoryJournal() : b.journal;
        transport=b.transport; sleeper=b.sleeper; clock=b.clock;
    }
    public static Builder builder(){return new Builder();}
    String token(){return token;} public String actorId(){return actorId;} public String buildNumber(){return buildNumber;} public String buildId(){return buildId;} public String sessionId(){return sessionId;}
    public BigDecimal maxTotalChargeUsd(){return maxTotalChargeUsd;} public boolean requireChargeCap(){return requireChargeCap;}
    public Duration requestTimeout(){return requestTimeout;} public Duration overallDeadline(){return overallDeadline;} public Duration pollInterval(){return pollInterval;}
    public int datasetPageLimit(){return datasetPageLimit;} public int maxPolls(){return maxPolls;} public Journal journal(){return journal;}
    Transport transport(){return transport;} Sleeper sleeper(){return sleeper;} Clock clock(){return clock;}

    public static final class Builder {
        private String token, actorId=DEFAULT_ACTOR_ID, buildNumber=CONTROLLED_BUILD_NUMBER, buildId=CONTROLLED_BUILD_ID, sessionId;
        private BigDecimal maxTotalChargeUsd; private boolean requireChargeCap;
        private Duration requestTimeout=Duration.ofSeconds(30), overallDeadline=Duration.ofSeconds(900), pollInterval=Duration.ofSeconds(2);
        private int datasetPageLimit=100, maxPolls=450; private Journal journal; private Transport transport; private Sleeper sleeper; private Clock clock=Clock.systemUTC();
        public Builder token(String v){token=v;return this;} public Builder actorId(String v){actorId=v;return this;}
        public Builder sessionId(String v){sessionId=v;return this;}
        public Builder buildNumber(String v){buildNumber=v;return this;} public Builder buildId(String v){buildId=v;return this;}
        public Builder maxTotalChargeUsd(BigDecimal v){maxTotalChargeUsd=v;return this;} public Builder requireChargeCap(boolean v){requireChargeCap=v;return this;}
        public Builder requestTimeout(Duration v){requestTimeout=v;return this;} public Builder overallDeadline(Duration v){overallDeadline=v;return this;}
        public Builder pollInterval(Duration v){pollInterval=v;return this;} public Builder datasetPageLimit(int v){datasetPageLimit=v;return this;}
        public Builder maxPolls(int v){maxPolls=v;return this;}
        /** Overrides the process-local InMemoryJournal. Production callers that need recovery
         * across client/process restarts should explicitly pass JsonlFileJournal.open(path). */
        public Builder journal(Journal v){journal=v;return this;}
        public Builder transport(Transport v){transport=v;return this;}
        public Builder sleeper(Sleeper v){sleeper=v;return this;} public Builder clock(Clock v){clock=v;return this;}
        public ClientConfig build(){
            if(token==null||token.isBlank()) throw new ConfigurationException("APIFY_TOKEN is required; pass token explicitly or through the process environment");
            if(actorId==null||actorId.isBlank()||!actorId.equals(actorId.trim())||actorId.contains("?")||actorId.contains("#")) throw new ConfigurationException("actorId is invalid");
            if(!Objects.equals(buildNumber,CONTROLLED_BUILD_NUMBER)||!Objects.equals(buildId,CONTROLLED_BUILD_ID)) throw new ConfigurationException("only the controlled Build 0.0.50 / aJLRmMdQapLQRT4sJ is accepted");
            if(requireChargeCap&&(maxTotalChargeUsd==null||maxTotalChargeUsd.signum()<=0)) throw new ConfigurationException("a positive maxTotalChargeUsd is required when requireChargeCap is enabled");
            if(maxTotalChargeUsd!=null&&maxTotalChargeUsd.signum()<=0) throw new ConfigurationException("maxTotalChargeUsd must be positive when supplied");
            if(requestTimeout==null||requestTimeout.isZero()||requestTimeout.isNegative()||overallDeadline==null||overallDeadline.isZero()||overallDeadline.isNegative()||pollInterval==null||pollInterval.isNegative()) throw new ConfigurationException("timeouts must be positive and pollInterval cannot be negative");
            if(datasetPageLimit<=0||maxPolls<=0) throw new ConfigurationException("datasetPageLimit and maxPolls must be positive");
            if(clock==null) clock=Clock.systemUTC();
            if(transport!=null&&!transport.guaranteesSingleShotPost()) throw new ConfigurationException("custom Transport must explicitly guarantee no redirects or POST replay");
            return new ClientConfig(this);
        }
    }
}
