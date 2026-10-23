package com.apismith.instagram.transcriptapi;
public record BulkOptions(Integer resultsLimit, Boolean skipPinnedPosts, Boolean includeSharesCount) { public static BulkOptions defaults(){return new BulkOptions(null,null,null);} }
