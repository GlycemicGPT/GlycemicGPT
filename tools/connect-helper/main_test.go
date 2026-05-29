package main

import "testing"

func TestIsCaptureRedirect_MatchesCarePartnerWithCode(t *testing.T) {
	for _, status := range []int{301, 302, 303, 307, 308} {
		if !isCaptureRedirect(status, "com.medtronic.carepartner:/sso?code=abc&state=xyz") {
			t.Errorf("expected match for status %d", status)
		}
	}
}

func TestIsCaptureRedirect_RejectsNonRedirectStatus(t *testing.T) {
	if isCaptureRedirect(200, "com.medtronic.carepartner:/sso?code=abc") {
		t.Error("200 must not match")
	}
	if isCaptureRedirect(404, "com.medtronic.carepartner:/sso?code=abc") {
		t.Error("404 must not match")
	}
}

func TestIsCaptureRedirect_RejectsOtherSchemes(t *testing.T) {
	cases := []string{
		"https://carelink-login.minimed.com/u/login",
		"com.medtronic.carepartner:/sso?error=denied", // no code=
		"",
	}
	for _, c := range cases {
		if isCaptureRedirect(302, c) {
			t.Errorf("must not match: %q", c)
		}
	}
}

func TestExtractLocationHeader_CaseInsensitive(t *testing.T) {
	headers := map[string]interface{}{
		"Content-Type": "text/html",
		"Location":     "com.medtronic.carepartner:/sso?code=ok",
	}
	if got := extractLocationHeader(headers); got != "com.medtronic.carepartner:/sso?code=ok" {
		t.Errorf("title-case Location: got %q", got)
	}
	headers2 := map[string]interface{}{"location": "lower-case"}
	if got := extractLocationHeader(headers2); got != "lower-case" {
		t.Errorf("lower-case location: got %q", got)
	}
	if got := extractLocationHeader(map[string]interface{}{"X-Other": "v"}); got != "" {
		t.Errorf("missing -> %q (want empty)", got)
	}
}

func TestExtractLocationHeader_IgnoresNonStringValues(t *testing.T) {
	headers := map[string]interface{}{"location": 123} // chromedp can hand back non-string defensively
	if got := extractLocationHeader(headers); got != "" {
		t.Errorf("non-string -> %q (want empty)", got)
	}
}

func TestParseFlags_AcceptsRequiredFlags(t *testing.T) {
	got, err := parseFlags([]string{
		"--api", "https://x.test/",
		"--pair", "tok",
		"--username", "u",
	})
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if got.apiURL != "https://x.test" {
		t.Errorf("apiURL trailing slash not stripped: %q", got.apiURL)
	}
	if got.pair != "tok" || got.username != "u" {
		t.Errorf("required flags: %+v", got)
	}
	if got.region != "US" {
		t.Errorf("default region: %q", got.region)
	}
}

func TestParseFlags_NormalisesRegionUpper(t *testing.T) {
	got, err := parseFlags([]string{
		"--api", "https://x.test",
		"--pair", "tok",
		"--username", "u",
		"--region", "eu",
	})
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if got.region != "EU" {
		t.Errorf("region upper: %q", got.region)
	}
}

func TestParseFlags_RejectsMissingRequired(t *testing.T) {
	cases := [][]string{
		{},
		{"--api", "https://x.test"},
		{"--api", "https://x.test", "--pair", "t"},
		{"--pair", "t", "--username", "u"},
	}
	for _, c := range cases {
		if _, err := parseFlags(c); err == nil {
			t.Errorf("expected err for %v", c)
		}
	}
}
