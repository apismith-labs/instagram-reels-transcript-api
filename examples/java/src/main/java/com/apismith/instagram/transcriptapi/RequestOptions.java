package com.apismith.instagram.transcriptapi;
import java.math.BigDecimal;
public record RequestOptions(BigDecimal maxTotalChargeUsd, Boolean requireChargeCap) { public static RequestOptions defaults(){return new RequestOptions(null,null);} }
