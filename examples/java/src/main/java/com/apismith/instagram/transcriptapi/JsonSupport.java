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
    private static final Set<String> DIAGNOSTIC_KEYS=Set.of("error","exception","diagnostic","fatal","stage");
    private static final Pattern SECRET_TEXT=Pattern.compile("(?i)(?:authorization\\s*[=:]\\s*)?bearer\\s+[A-Za-z0-9._~+/-]+=*|(?:token|sessionid|authorization|cookie)\\s*[=:]\\s*[^\\s,;]+" );
    private JsonSupport(){}
    /** Removes known secret-bearing fields while preserving ordinary business text verbatim. */
    public static JsonNode sanitize(JsonNode input){return sanitize(input,false,false);}
    /** Output serialization also redacts diagnostics, while preserving raw Actor data text. */
    public static JsonNode sanitizeForOutput(JsonNode input){return sanitize(input,false,true);}
    private static JsonNode sanitize(JsonNode input,boolean rawActorData,boolean redactDiagnostics){if(input==null)return null;if(input.isObject()){var out=MAPPER.createObjectNode();Iterator<Map.Entry<String,JsonNode>> it=input.fields();while(it.hasNext()){var e=it.next();String key=normalize(e.getKey());if(SECRET_KEYS.contains(key))continue;JsonNode value=e.getValue();boolean raw=rawActorData||"rawitems".equals(key);if(redactDiagnostics&&!raw&&DIAGNOSTIC_KEYS.contains(key)&&value!=null&&value.isTextual())out.set(e.getKey(),MAPPER.getNodeFactory().textNode(redact(value.asText())));else out.set(e.getKey(),sanitize(value,raw,redactDiagnostics));}return out;}if(input.isArray()){var out=MAPPER.createArrayNode();for(JsonNode n:input)out.add(sanitize(n,rawActorData,redactDiagnostics));return out;}return input.deepCopy();}
    public static String redact(String value){if(value==null)return null;return SECRET_TEXT.matcher(value).replaceAll("[REDACTED]");}
    private static String normalize(String key){return key.toLowerCase(Locale.ROOT).replace("_","").replace("-","");}
}
