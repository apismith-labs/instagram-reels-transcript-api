package com.apismith.instagram.transcriptapi;
import java.math.BigDecimal;
public record CsvPlan(String mode, int rows, int maximumActorRuns, int concurrency, String actorBuild,
        boolean requireChargeCap, BigDecimal perRunCapUsd, BigDecimal estimatedMaximumRunCapsTotalUsd, String csvPath) { }
