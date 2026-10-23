package com.apismith.instagram.transcriptapi;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** Small RFC-4180 style UTF-8 parser with BOM and CRLF support. */
public final class CsvParser {
    private CsvParser(){}
    public static List<CsvRow> read(Path path) throws IOException {
        String source=Files.readString(path,StandardCharsets.UTF_8);if(source.startsWith("\uFEFF"))source=source.substring(1);
        List<Record> records=parse(source);if(records.isEmpty())throw new ConfigurationException("CSV is empty");
        List<String> header=records.get(0).fields();int video=-1,url=-1;for(int i=0;i<header.size();i++){String name=header.get(i).trim();if(name.equals("videoUrl"))video=i;if(name.equals("url"))url=i;}
        int index=video>=0?video:url;if(index<0)throw new ConfigurationException("CSV line 1: required url or videoUrl header is missing");
        List<CsvRow> rows=new ArrayList<>();for(int n=1;n<records.size();n++){Record r=records.get(n);List<String> fields=r.fields();if(fields.stream().allMatch(String::isBlank))continue;if(index>=fields.size())throw new ConfigurationException("CSV line "+r.line()+": URL field is missing");String value=fields.get(index);if(value==null||value.isBlank())continue;String valid;try{valid=InputValidators.validateVideoUrl(value.trim());}catch(ConfigurationException ex){throw new ConfigurationException("CSV line "+r.line()+": "+ex.getMessage());}rows.add(new CsvRow(Integer.toString(r.line()),valid));}
        return List.copyOf(rows);
    }
    private static List<Record> parse(String s){List<Record> out=new ArrayList<>();List<String> fields=new ArrayList<>();StringBuilder value=new StringBuilder();boolean quoted=false,afterQuote=false;int line=1,recordLine=1;
        for(int i=0;i<s.length();i++){char c=s.charAt(i);
            if(quoted){if(c=='"'){if(i+1<s.length()&&s.charAt(i+1)=='"'){value.append('"');i++;}else{quoted=false;afterQuote=true;}}else{value.append(c);if(c=='\n')line++;else if(c=='\r'&&(i+1>=s.length()||s.charAt(i+1)!='\n'))line++;}continue;}
            if(afterQuote&&c!=','&&c!='\r'&&c!='\n'&&!Character.isWhitespace(c))throw new ConfigurationException("CSV line "+line+": unexpected character after quoted value");
            if(c=='"'){if(value.length()!=0||afterQuote)throw new ConfigurationException("CSV line "+line+": quote inside unquoted value");quoted=true;continue;}
            if(c==','){fields.add(value.toString());value.setLength(0);afterQuote=false;continue;}
            if(c=='\r'||c=='\n'){fields.add(value.toString());value.setLength(0);out.add(new Record(List.copyOf(fields),recordLine));fields.clear();afterQuote=false;if(c=='\r'&&i+1<s.length()&&s.charAt(i+1)=='\n')i++;line++;recordLine=line;continue;}
            if(afterQuote&&Character.isWhitespace(c))continue;value.append(c);
        }
        if(quoted)throw new ConfigurationException("CSV line "+line+": unterminated quoted value");
        if(value.length()>0||!fields.isEmpty()||s.isEmpty()||!s.endsWith("\n")&&!s.endsWith("\r")){fields.add(value.toString());out.add(new Record(List.copyOf(fields),line));}
        return out;
    }
    private record Record(List<String> fields,int line){}
}
