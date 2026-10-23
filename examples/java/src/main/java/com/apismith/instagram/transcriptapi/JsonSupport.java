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
    private static final Set<String> RAW_DATA_KEYS=Set.of("rawitems","raw","items","item");
    private static final Pattern SECRET_TEXT=Pattern.compile("(?i)(?:(authorization\\s*[=:]\\s*)?(bearer\\s+)[A-Za-z0-9._~+/-]+=*|((?:token|sessionid|authorization|cookie|password|api[_-]?key)\\s*[=:]\\s*[\\\"']?)[^\\s,;&\\\"']+)");
    private JsonSupport(){}
    /** Removes known secret-bearing fields while preserving ordinary business text verbatim. */
    public static JsonNode sanitize(JsonNode input){return sanitize(input,false,false);}
    /** Output serialization redacts diagnostics and recognized credentials in raw Actor text. */
    public static JsonNode sanitizeForOutput(JsonNode input){return sanitize(input,false,true);}
    private static JsonNode sanitize(JsonNode input,boolean rawActorData,boolean redactDiagnostics){if(input==null)return null;if(input.isObject()){var out=MAPPER.createObjectNode();Iterator<Map.Entry<String,JsonNode>> it=input.fields();while(it.hasNext()){var e=it.next();String key=normalize(e.getKey());if(SECRET_KEYS.contains(key))continue;JsonNode value=e.getValue();boolean raw=rawActorData||RAW_DATA_KEYS.contains(key);if(redactDiagnostics&&!rawActorData&&!raw&&DIAGNOSTIC_KEYS.contains(key)&&value!=null&&value.isTextual())out.set(e.getKey(),MAPPER.getNodeFactory().textNode(safeError(value.asText())));else out.set(e.getKey(),sanitize(value,raw,redactDiagnostics));}return out;}if(input.isArray()){var out=MAPPER.createArrayNode();for(JsonNode n:input)out.add(sanitize(n,rawActorData,redactDiagnostics));return out;}if(redactDiagnostics&&input.isTextual())return MAPPER.getNodeFactory().textNode(redact(input.asText()));return input.deepCopy();}
    public static String redact(String value){
        if(value==null)return null;
        var matcher=SECRET_TEXT.matcher(value);var out=new StringBuffer();
        while(matcher.find()){
            String replacement=matcher.group(2)!=null
                    ? (matcher.group(1)==null?"":matcher.group(1))+matcher.group(2)+"[REDACTED]"
                    : matcher.group(3)+"[REDACTED]";
            matcher.appendReplacement(out,java.util.regex.Matcher.quoteReplacement(replacement));
        }
        matcher.appendTail(out);return out.toString();
    }
    /** Redacts and bounds diagnostic text before it enters public results, logs, or persistence. */
    public static String safeError(String value){
        if(value==null)return null;
        String normalized=redact(value).replace("\r\n"," ").replace('\r',' ').replace('\n',' ');
        return normalized.length()>300?normalized.substring(0,300):normalized;
    }
    private static String normalize(String key){return key.toLowerCase(Locale.ROOT).replace("_","").replace("-","");}
}
