package com.apismith.instagram.transcriptapi;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.Files;
import java.nio.file.Path;
import static org.junit.jupiter.api.Assertions.*;
class CsvParserTest {
 @TempDir Path temp;
 @Test void readsUtf8BomAndCrLf()throws Exception{Path p=temp.resolve("in.csv");Files.writeString(p,"\uFEFFvideoUrl,note\r\nhttps://www.instagram.com/reel/a/,测试 😀\r\n");var r=CsvParser.read(p);assertEquals(1,r.size());assertEquals("https://www.instagram.com/reel/a/",r.get(0).url());}
 @Test void allowsQuotedCommaAndEscapedQuotes()throws Exception{Path p=temp.resolve("in.csv");Files.writeString(p,"videoUrl,note\nhttps://www.instagram.com/reel/a/,\"a,b \"\"c\"\"\"\n");assertEquals(1,CsvParser.read(p).size());}
 @Test void missingHeaderFailsClosed()throws Exception{Path p=temp.resolve("in.csv");Files.writeString(p,"username\nalice\n");assertThrows(ConfigurationException.class,()->CsvParser.read(p));}
 @Test void invalidUrlErrorCarriesCsvLine()throws Exception{Path p=temp.resolve("in.csv");Files.writeString(p,"url\nhttps://www.instagram.com/reel/a/\nhttp://bad.test/a\n");var e=assertThrows(ConfigurationException.class,()->CsvParser.read(p));assertTrue(e.getMessage().contains("line 3"));}
 @Test void multilineCsvRowErrorUsesItsStartingPhysicalLine()throws Exception{Path p=temp.resolve("in.csv");Files.writeString(p,"url,note\nhttp://bad.test/a,\"first\nsecond\"\n");var e=assertThrows(ConfigurationException.class,()->CsvParser.read(p));assertTrue(e.getMessage().contains("line 2"));}
 @Test void emptyUrlIsSkipped()throws Exception{Path p=temp.resolve("in.csv");Files.writeString(p,"url\n\nhttps://www.instagram.com/reel/a/\n");assertEquals(1,CsvParser.read(p).size());}
 @Test void unterminatedQuoteRejected()throws Exception{Path p=temp.resolve("in.csv");Files.writeString(p,"url,n\nhttps://www.instagram.com/reel/a/,\"broken\n");assertThrows(ConfigurationException.class,()->CsvParser.read(p));}
 @Test void duplicateHeaderUsesLastUrlHeader()throws Exception{Path p=temp.resolve("in.csv");Files.writeString(p,"url,videoUrl\n,https://www.instagram.com/reel/a/\n");assertEquals(1,CsvParser.read(p).size());}
 @Test void blankInputRejected()throws Exception{Path p=temp.resolve("in.csv");Files.writeString(p,"");assertThrows(ConfigurationException.class,()->CsvParser.read(p));}
 @Test void fileRowsKeepPhysicalLineNumber()throws Exception{Path p=temp.resolve("in.csv");Files.writeString(p,"videoUrl\n\nhttps://www.instagram.com/reel/a/\n");assertEquals("3",CsvParser.read(p).get(0).rowNumber());}
 @Test void parserDoesNotTrimInternalUrlWhitespace()throws Exception{Path p=temp.resolve("in.csv");Files.writeString(p,"url\nhttps://www.instagram.com/reel/a/ x\n");assertThrows(ConfigurationException.class,()->CsvParser.read(p));}
}
