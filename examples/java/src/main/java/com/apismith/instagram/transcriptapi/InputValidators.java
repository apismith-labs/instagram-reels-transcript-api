package com.apismith.instagram.transcriptapi;

import java.net.URI;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class InputValidators {
    private static final Pattern VIDEO_PATH=Pattern.compile("^/(?:reel|reels|p)/([A-Za-z0-9_-]+)/?$",Pattern.CASE_INSENSITIVE);
    private static final Pattern USERNAME=Pattern.compile("^[A-Za-z0-9._]{1,30}$");
    private static final Pattern PERIOD=Pattern.compile("^[1-9][0-9]* (?:days?|weeks?|months?|years?)$",Pattern.CASE_INSENSITIVE);
    private InputValidators(){}
    public static String validateVideoUrl(String value){
        if(value==null||value.isBlank()||!value.equals(value.trim())||value.contains(" ")||value.startsWith("<")||value.endsWith(">")||value.startsWith("[")||value.endsWith(")"))throw new ConfigurationException("video URL must be a bare Instagram Reel URL");
        try{URI u=URI.create(value);String host=u.getHost();if(!"https".equalsIgnoreCase(u.getScheme())||host==null||!(host.equalsIgnoreCase("instagram.com")||host.equalsIgnoreCase("www.instagram.com"))||u.getRawQuery()!=null||u.getRawFragment()!=null||u.getUserInfo()!=null||u.getPort()!=-1||!value.equals(u.toASCIIString()))throw new IllegalArgumentException();Matcher m=VIDEO_PATH.matcher(u.getPath());if(!m.matches())throw new IllegalArgumentException();return "https://www.instagram.com/"+u.getPath().replaceFirst("^/","");}catch(RuntimeException e){throw new ConfigurationException("video URL must be a bare HTTPS Instagram Reel URL without query or fragment");}
    }
    public static List<String> validateBulkInput(List<String> urls){if(urls==null||urls.isEmpty())throw new ConfigurationException("at least one URL is required");List<String> out=new ArrayList<>();Set<String> seen=new HashSet<>(),shortcodes=new HashSet<>();for(String raw:urls){String url=validateVideoUrl(raw);String id=identity(url),code=shortcode(url);if(!seen.add(id)||!shortcodes.add(code))throw new ConfigurationException("duplicate or aliased URL in bulk input");out.add(url);}return List.copyOf(out);}
    public static List<String> validateUsernames(List<String> names){if(names==null||names.isEmpty())throw new ConfigurationException("at least one username is required");List<String> out=new ArrayList<>();Set<String> seen=new HashSet<>();for(String n:names){if(n==null||!n.equals(n.trim())||n.startsWith("@")||!USERNAME.matcher(n).matches()||n.startsWith(".")||n.endsWith(".")||n.contains("..")||n.chars().noneMatch(Character::isLetterOrDigit)||!seen.add(n.toLowerCase(Locale.ROOT)))throw new ConfigurationException("username is invalid or duplicated");out.add(n);}return List.copyOf(out);}
    public static String validateOnlyPostsNewerThan(String value){if(value==null)return null;if(value.isBlank())throw new ConfigurationException("onlyPostsNewerThan must not be empty");if(PERIOD.matcher(value).matches())return value;try{return LocalDate.parse(value).toString();}catch(DateTimeParseException e){throw new ConfigurationException("onlyPostsNewerThan must be YYYY-MM-DD or N days; ISO timestamps are not accepted");}}
    public static String identity(String url){String canonical=validateVideoUrl(url);String path=canonical.substring("https://www.instagram.com".length()).replaceAll("/$","");return path.replaceFirst("^/reels/","/reel/");}
    public static String shortcode(String url){Matcher m=VIDEO_PATH.matcher(URI.create(validateVideoUrl(url)).getPath());return m.matches()?m.group(1):null;}
}
