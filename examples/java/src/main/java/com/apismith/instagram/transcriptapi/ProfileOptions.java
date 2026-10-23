package com.apismith.instagram.transcriptapi;
public record ProfileOptions(Integer resultsLimit, String onlyPostsNewerThan, Boolean skipPinnedPosts, Boolean includeSharesCount) {
    public ProfileOptions { onlyPostsNewerThan=InputValidators.validateOnlyPostsNewerThan(onlyPostsNewerThan); }
    public static ProfileOptions defaults(){return new ProfileOptions(null,null,null,null);}
}
