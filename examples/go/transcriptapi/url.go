package transcriptapi

import (
	"net/url"
	"regexp"
	"strings"
)

var shortcodePattern = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

// ValidateVideoURL accepts explicit HTTPS Instagram Reel, Reels, and post URLs only.
func ValidateVideoURL(raw string) (string, error) {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" || trimmed != raw || strings.ContainsAny(trimmed, " \t\r\n") {
		return "", ErrInvalidURL
	}
	u, err := url.Parse(trimmed)
	if err != nil || u == nil || u.Scheme != "https" || u.User != nil || u.Port() != "" || u.RawQuery != "" || u.Fragment != "" {
		return "", ErrInvalidURL
	}
	host := strings.ToLower(u.Hostname())
	if host != "instagram.com" && host != "www.instagram.com" {
		return "", ErrInvalidURL
	}
	parts := strings.Split(strings.Trim(u.Path, "/"), "/")
	if len(parts) != 2 || (parts[0] != "reel" && parts[0] != "reels" && parts[0] != "p") || !shortcodePattern.MatchString(parts[1]) {
		return "", ErrInvalidURL
	}
	return trimmed, nil
}
