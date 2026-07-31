package main

import (
	"embed"
	"fmt"
	"log"
	"net"
	"net/http"
	"os/exec"
)

//go:embed gaze-demo.html
var content embed.FS

func openBrowser(url string) {
	// macOS
	_ = exec.Command("open", url).Start()
}

func main() {
	html, err := content.ReadFile("gaze-demo.html")
	if err != nil {
		log.Fatal(err)
	}

	// Bind to a free localhost port (secure context -> camera works).
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		log.Fatal(err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	url := fmt.Sprintf("http://127.0.0.1:%d/", port)

	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write(html)
	})

	fmt.Printf("\n  Gaze demo running at %s\n", url)
	fmt.Println("  Your browser should open automatically.")
	fmt.Println("  Grant camera access when asked. Quit this app (Dock) or press Ctrl-C when done.\n")

	openBrowser(url)
	log.Fatal(http.Serve(ln, nil))
}
