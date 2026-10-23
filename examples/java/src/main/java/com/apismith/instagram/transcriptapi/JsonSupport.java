package com.apismith.instagram.transcriptapi;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.MapperFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import java.util.Iterator;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

public final class JsonSupport {
    public static final ObjectMapper MAPPER=new ObjectMapper()
            .configure(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS,false)
            .configure(MapperFeature.SORT_PROPERTIES_ALPHABETICALLY,true)
            .configure(JsonParser.Feature.STRICT_DUPLICATE_DETECTION,true);
    private static final Set<String> SECRET_KEYS=Set.of("token","sessionid","cookie","authorization","password","secret","accesstoken","refreshtoken","apikey");
    private static final Pattern SECRET_TEXT=Pattern.compile("(?i)(bearer\\s+)[A-Za-z0-9._~+/-]+=*|((?:token|sessionid|authorization|cookie)\\s*[=:]\\s*)[^\\s,;]+" );
    private JsonSupport(){}
    public static JsonNode sanitize(JsonNode input){if(input==null)return null;if(input.isObject()){var out=MAPPER.createObjectNode();Iterator<Map.Entry<String,JsonNode>> it=input.fields();while(it.hasNext()){var e=it.next();if(!SECRET_KEYS.contains(normalize(e.getKey())))out.set(e.getKey(),sanitize(e.getValue()));}return out;}if(input.isArray()){var out=MAPPER.createArrayNode();for(JsonNode n:input)out.add(sanitize(n));return out;}if(input.isTextual())return MAPPER.getNodeFactory().textNode(redact(input.asText()));return input.deepCopy();}
    public static String redact(String value){if(value==null)return null;return SECRET_TEXT.matcher(value).replaceAll("[REDACTED]");}
    private static String normalize(String key){return key.toLowerCase(Locale.ROOT).replace("_","").replace("-","");}
}
