# Govee LAN: what works on real controllers

Notes from testing on real H806A controllers (called A, B and C here), to decide how the
setup wizard shows its test patterns. Nothing here is implemented until it is confirmed on
all three.

## Commands

| What | How it is sent | Result on A |
|---|---|---|
| Plain on/off, 1 s each | `turn` 3 times per change | Dims and brightens only: the controller fades |
| Plain on/off, 3 s each | `turn` 3 times per change | Blinks, with a slow fade |
| Plain color change (white / orange, 3 s) | `colorwc` twice per change | Slow wave from one color to the next |
| Stream, "start" resent every second | razer on 3x, then every 1 s; frames twice at 10 fps | Sharp changes, but 2-3 extra flashes per color |
| Stream, "start" only at the beginning | razer on 3x at the start; frames at 10-15 fps | Sharp, no flashes |
| Stream end | razer off 3x | Once the last frame (white) stayed on: all 3 lost |

## How a stream frame maps to the lights

A frame of N colors is spread over the whole run in N equal parts (it is not one color
per light from light 1):

- 50 white colors: the whole run lit, not just the first 50 lights.
- 3 colors as thirds (red, green, blue of a 50-color frame): thirds of the whole run.
- 10 colors, red and green in turn: 10 blocks of about 10-12 lights.
- 120 colors, red and green in turn: every light alternates (A probably has 120 lights).

## Wizard patterns on A

| Pattern | Frame | Result |
|---|---|---|
| Blink, 1 s on / 1 s off | 50 | Steady blink |
| Blink, 2 s on / 2 s off | 120 | 1st try: stayed white (stream never started). 2nd try: blinks |
| Colors: red, green, blue thirds | 50 | Thirds of the whole run |
| Check: light 1 red, last blue, rest dim white | 120 | Not seen yet |
| Direction: dot from light 1 | | Not tried yet |
| Ruler: every 10th light white | | Not tried yet |
| Segment groups | | Not tried yet |
| Count: 10 blocks | 10 | 10 blocks, red and green |
| Count: every light red or green | 120 | Every light alternates |
| Segment command: segments 1, 3, 5... green on white | (ptReal, mask for 56) | Blocks of 5 white / 5 green: segments are 5 lights. 12 greens (23-24 segments). After the stream stops, the segment colors come back |
| Stream: 4 white, 1 red, repeated | 255 | All off: a 255-color frame isn't shown |
| Segment command: green, white, red, yellow per segment, repeated | (ptReal) | Ends on yellow, 6 yellows: 4 x 5 + 4 = 24 segments |
| Segment command: segments 1-23 white, segment 24 red | (ptReal) | 5 red, then 1 light still green after them: a 25th segment, missed in the 4-color count (one light is easy to miss) |
| Segment command: 1-24 white, 25 red, 26+ blue | (ptReal) | All white, the one extra light still green: A drives 24 segments = 120 lights; the extra light is past its count and keeps an old color |

Counting on Govee (works on A):
1. Segments green, white, red, yellow, repeated: the last color and how many blocks of it
   give the segments: 4 x (blocks - 1) + place (green 1, white 2, red 3, yellow 4).
2. All white, the last segment red: count the red lights. Lights = 5 x (segments - 1) + red.
3. A light that never changes is past the controller's count (set in the Govee app).

| Controller | Blink | Last color x blocks | Segments | Red in last | Lights |
|---|---|---|---|---|---|
| A | works | yellow x 6 | 24 | 5 | 120 |
| B | works | white x 3 | 10 | 5 | 50 (confirmed: stream of 50, light 1 blue, light 50 red: one light each) |
| C | works | red x 4 | 15 | 3 | 73 (confirmed: stream of 73, light 1 blue, light 73 red: one light each) |

## The wizard flow for Govee (confirmed on A, B and C)

1. Blink (stream, "start" 3x at the beginning only): 2 s white, 2 s dark. Which run is it?
2. Segments green, white, red, yellow, repeated (segment command, every segment set):
   last color and how many blocks of it -> segments.
3. All segments white, the last red, any past it blue (segment command): count the red
   lights -> lights = 5 x (segments - 1) + red. Blue means the segment count was wrong.
4. Confirm (stream of exactly that many colors): light 1 red, the last light blue, the rest
   white (tested with blue first, red last; the wizard swapped them to match WLED's check).
   Each must be a single light; the red end is light 1. Nothing past the count can be shown:
   the controller spreads the frame over the lights it drives.

Lesson: a test must set every segment it might reach (up to the most the controller takes),
or an old color stays on a segment it didn't set and looks like part of the pattern.

## What the documentation says

- Govee's official LAN guide (app-h5.govee.com/user-manual/wlan-guide) has only `turn`,
  `brightness`, `colorwc` and `devStatus`. Nothing about streaming or single lights.
- `razer` streaming is reverse-engineered (DreamView / SignalRGB projects):
  `BB len_hi len_lo B0 gradient N [R G B]*N xor`. gradient 00 = solid parts, 01 = blended.
  N is a number of segments: the controller splits the run into N parts. Most projects send
  10; one user reports a 15-segment strip froze to white with 14-15.
- So parts are only equal when N divides the light count; otherwise they differ by one light.

## Counting, given the stretching

- Markers (5, 15, 25... red; 10, 20... green; 50, 100... blue) can't count: you always see
  the markers sent, spread over the run.
- 10 blocks give an estimate (off by up to ~10 when the count isn't a multiple of 10).
- Red / green alternating is exact: every light alternates only when N = the light count.

## Open questions

- The stream sometimes doesn't start (all 3 "start" messages lost?). How often, and what
  makes it start every time without flashes?
- Same results on B and C?
