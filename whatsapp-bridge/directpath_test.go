package main

import "testing"

func TestExtractDirectPathFromURLKeepsQuery(t *testing.T) {
	url := "https://mmg.whatsapp.net/v/t62.7118-24/123_456_n.enc?ccb=11-4&oh=01_abc&oe=6A1B2C3D&_nc_sid=5e03e0&mms3=true"
	want := "/v/t62.7118-24/123_456_n.enc?ccb=11-4&oh=01_abc&oe=6A1B2C3D&_nc_sid=5e03e0&mms3=true"
	if got := extractDirectPathFromURL(url); got != want {
		t.Fatalf("extractDirectPathFromURL() = %q, want %q", got, want)
	}
}
