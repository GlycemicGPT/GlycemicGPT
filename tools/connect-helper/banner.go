// Banner shown when the helper starts. Pure UTF-8 box-drawing + block
// characters. When stdout is a real TTY, the CGM-strip line briefly
// animates -- the wave rotates left like glucose data tracing across,
// then settles to the canonical frame. When stdout is not a TTY (piped,
// redirected to a file, captured by `script(1)`), no ANSI is emitted so
// the captured text is byte-identical to a static one-shot print.
//
// The block-letter "GG" is the GlycemicGPT mark. The CGM strip's pattern
// reads as glucose data over time, which keeps the helper's purpose
// visually obvious without any clinical iconography.
//
// Every inner line is exactly 71 cells wide; that lets the box render
// square on the default 80-column terminal with margin to spare. If you
// edit the art, count cells -- every character used here (█ ─ │ ╭ ╮ ╰ ╯
// ▃ ▄ ▅ ▆ ▇) is a single monospace cell.

package main

import (
	"fmt"
	"os"
	"time"
)

const helperBanner = "" +
	"\n" +
	"╭───────────────────────────────────────────────────────────────────────╮\n" +
	"│                                                                       │\n" +
	"│   ██████   ██████   GlycemicGPT                                       │\n" +
	"│   ██       ██       ─────────────                                     │\n" +
	"│   ██ ███   ██ ███   Medtronic CareLink Connector                      │\n" +
	"│   ██  ██   ██  ██                                                     │\n" +
	"│   ██████   ██████   Single-use pairing token.                         │\n" +
	"│                     Your CareLink refresh credential                  │\n" +
	"│   ▃▄▅▆▇▆▅▄▃▄▅▆▇▆▅   stays on your GlycemicGPT server.                 │\n" +
	"│                                                                       │\n" +
	"╰───────────────────────────────────────────────────────────────────────╯\n"

// waveBase is the canonical CGM-strip pattern (15 cells). The animation
// rotates this string left one cell per frame, then settles back here.
const waveBase = "▃▄▅▆▇▆▅▄▃▄▅▆▇▆▅"

// waveLineFmt redraws the wave line in place. The leading "│   " and the
// trailing label + padding + "│" match the static banner so the rewritten
// line is visually identical apart from the rotated wave glyphs. Keep this
// in sync with the corresponding line in helperBanner above.
const waveLineFmt = "│   %s   stays on your GlycemicGPT server.                 │"

// Animation tuning. 20 frames at ~100ms ≈ 2 seconds -- long enough for
// the eye to register the motion, short enough not to feel like a stall.
const (
	waveFrames        = 20
	waveFrameInterval = 100 * time.Millisecond
)

// stdoutIsTTY reports whether os.Stdout is connected to a terminal. Uses
// only stdlib (no x/term dependency) by checking the character-device
// mode flag on the Stat result -- pipes and regular files are not char
// devices, so they fall through to the no-animation path.
func stdoutIsTTY() bool {
	fi, err := os.Stdout.Stat()
	if err != nil {
		return false
	}
	return fi.Mode()&os.ModeCharDevice != 0
}

// printBanner emits the full static banner. On a TTY it then plays a short
// in-place animation on the CGM-strip line -- rotating the wave glyphs
// left -- before settling back to the canonical frame. Non-TTY output
// (pipes, redirects) skips the animation entirely so logs / file captures
// don't contain ANSI escape sequences.
func printBanner() {
	fmt.Print(helperBanner)
	if !stdoutIsTTY() {
		return
	}
	animateWave(os.Stdout)
}

// animateWave plays the in-place rotation animation on the CGM strip,
// then settles back to waveBase. The cursor is assumed to be at the line
// immediately after the closing box rule (where Print(helperBanner) leaves
// it), so the wave is exactly 3 lines above: closing ╰...╯ + blank pad +
// wave. We use \r (col 1) + \033[3A (up 3) to position, redraw the line,
// then \033[3B + \r to return the cursor to where we found it.
func animateWave(w *os.File) {
	runes := []rune(waveBase)
	n := len(runes)
	for shift := 1; shift <= waveFrames; shift++ {
		shifted := make([]rune, n)
		for i := 0; i < n; i++ {
			shifted[i] = runes[(i+shift)%n]
		}
		fmt.Fprintf(w, "\r\033[3A"+waveLineFmt+"\033[3B\r", string(shifted))
		time.Sleep(waveFrameInterval)
	}
	fmt.Fprintf(w, "\r\033[3A"+waveLineFmt+"\033[3B\r", waveBase)
}
