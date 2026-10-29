"""
Human-style typing engine.

The engine never talks to the keyboard directly. It sends keystrokes to a
"sink" object with two methods:

    sink.type_char(ch)   - type one character ("\n" means Enter, "\t" means Tab)
    sink.backspace()     - press the Backspace key

That keeps the mistake logic testable without a real keyboard.
"""

import random
import threading


class StopTyping(Exception):
    """Raised inside the engine when the user cancels."""


# ---------------------------------------------------------------- keyboard map
QWERTY_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]


def _build_neighbors():
    """Letters physically next to each letter on a QWERTY keyboard."""
    result = {}
    for r, row in enumerate(QWERTY_ROWS):
        for c, ch in enumerate(row):
            near = set()
            if c > 0:
                near.add(row[c - 1])
            if c < len(row) - 1:
                near.add(row[c + 1])
            if r > 0:  # row above is shifted half a key to the left
                above = QWERTY_ROWS[r - 1]
                for k in (c, c + 1):
                    if k < len(above):
                        near.add(above[k])
            if r < len(QWERTY_ROWS) - 1:  # row below is shifted right
                below = QWERTY_ROWS[r + 1]
                for k in (c - 1, c):
                    if 0 <= k < len(below):
                        near.add(below[k])
            result[ch] = sorted(near)
    return result


NEIGHBORS = _build_neighbors()

# Keys that sit next to Backspace, and how likely each is to be hit by accident.
STRAY_KEYS = ["=", "-", "\\"]
STRAY_WEIGHTS = [60, 25, 15]


class HumanTyper:
    def __init__(
        self,
        sink,
        wpm=65,
        error_rate=0.04,
        stop_event=None,
        progress_cb=None,
        sleeper=None,
        rng=None,
    ):
        self.sink = sink
        self.wpm = max(5, wpm)
        self.error_rate = max(0.0, min(1.0, error_rate))
        self.stop_event = stop_event
        self.progress_cb = progress_cb
        self._sleeper = sleeper
        self.rng = rng or random.Random()
        self.mistakes = 0  # how many mistakes were made (and fixed)

        self.base_delay = 60.0 / (self.wpm * 5.0)  # seconds per character

    # ------------------------------------------------------------- plumbing
    def _check_stop(self):
        if self.stop_event is not None and self.stop_event.is_set():
            raise StopTyping()

    def _sleep(self, seconds):
        if self._sleeper is not None:
            self._check_stop()
            self._sleeper(seconds)
            return
        if self.stop_event is not None:
            if self.stop_event.wait(seconds):
                raise StopTyping()
        else:
            threading.Event().wait(seconds)

    def _emit(self, ch):
        self._check_stop()
        self.sink.type_char(ch)

    # --------------------------------------------------------------- timing
    def _char_delay(self, ch):
        d = max(0.02, self.rng.gauss(self.base_delay, self.base_delay * 0.35))
        if ch == " ":
            d *= self.rng.uniform(1.0, 1.5)
        elif ch in ".,;:!?\n":
            d *= self.rng.uniform(1.6, 2.8)
        if self.rng.random() < 0.015:  # occasional short thinking pause
            d += self.rng.uniform(0.3, 0.9)
        return d

    # ----------------------------------------------------------------- main
    def run(self, text):
        n = len(text)
        i = 0
        safe_until = 0  # no new mistakes while retyping a corrected region
        while i < n:
            self._check_stop()
            if i >= safe_until and self._should_err(text, i):
                i, safe_until = self._make_mistake(text, i)
                continue
            ch = text[i]
            self._emit(ch)
            self._sleep(self._char_delay(ch))
            i += 1
            if self.progress_cb:
                self.progress_cb(i, n)

    # ------------------------------------------------------------- mistakes
    def _should_err(self, text, i):
        return text[i].isalpha() and self.rng.random() < self.error_rate

    def _pick_kind(self, text, i):
        c = text[i]
        n = len(text)
        options = []  # (kind, weight)

        if c.lower() in NEIGHBORS:
            options.append(("neighbor", 40))
        if i + 1 < n and text[i + 1].isalpha() and text[i + 1].lower() != c.lower():
            options.append(("swap", 18))
        options.append(("skip", 14))

        # Doubled letters are most likely when the word already has a repeat.
        repeated = (i > 0 and text[i - 1].lower() == c.lower()) or (
            i + 1 < n and text[i + 1].lower() == c.lower()
        )
        options.append(("double", 48 if repeated else 12))
        options.append(("stray", 8))

        kinds = [k for k, _ in options]
        weights = [w for _, w in options]
        return self.rng.choices(kinds, weights=weights, k=1)[0]

    def _neighbor_of(self, c):
        pick = self.rng.choice(NEIGHBORS[c.lower()])
        return pick.upper() if c.isupper() else pick

    def _make_mistake(self, text, i):
        """
        Type something wrong, keep typing for a bit, then notice and fix it.

        `typed_since_error` is the counter that decides how many times to
        press Backspace: it counts every character typed from the first wrong
        keystroke onward, including correct ones typed on top of the mistake.

        Returns (index to resume from, index up to which no new mistakes occur).
        """
        n = len(text)
        c = text[i]
        kind = self._pick_kind(text, i)

        wrong = []
        consumed = 1  # how many target characters this mistake used up
        if kind == "neighbor":
            wrong = [self._neighbor_of(c)]
        elif kind == "swap":  # "the" -> "teh"
            wrong = [text[i + 1], c]
            consumed = 2
        elif kind == "skip":  # "candy" -> "cndy"
            wrong = []
        elif kind == "double":  # "movie" -> "moovie"
            wrong = [c, c]
        elif kind == "stray":  # finger lands on "=" next to Backspace
            wrong = [self.rng.choices(STRAY_KEYS, weights=STRAY_WEIGHTS, k=1)[0]]
            consumed = 0

        self.mistakes += 1
        typed_since_error = 0

        for ch in wrong:
            self._emit(ch)
            typed_since_error += 1
            self._sleep(self._char_delay(ch))

        j = i + consumed  # next target index still to be typed

        # How many more (correct) characters get typed before noticing?
        limit = self._room_before_line_break(text, j)
        if kind == "stray":
            extra = 0  # you see a stray symbol immediately
        elif self.rng.random() < 0.40:
            extra = min(self._to_word_end(text, j), 15)  # noticed late
        else:
            extra = self.rng.choice([0, 1, 1, 2, 3])  # noticed early
        if kind == "skip":
            extra = max(extra, 1)  # a missing letter only shows up after the next key
        extra = min(extra, limit)

        for k in range(extra):
            ch = text[j + k]
            self._emit(ch)
            typed_since_error += 1
            self._sleep(self._char_delay(ch))

        self._correct(typed_since_error)

        resume = i
        safe_until = max(j + extra, i + 1)
        return resume, safe_until

    def _to_word_end(self, text, j):
        k = j
        while k < len(text) and (text[k].isalnum() or text[k] == "'"):
            k += 1
        return k - j

    @staticmethod
    def _room_before_line_break(text, j):
        """Never type past a newline/tab while an error is pending (Enter could submit a form)."""
        k = j
        while k < len(text) and text[k] not in "\n\t":
            k += 1
        return k - j

    def _correct(self, count):
        """Pause, then press Backspace `count` times (sometimes missing the key)."""
        self._sleep(self.rng.uniform(0.15, 0.5))  # reaction time
        remaining = count
        while remaining > 0:
            if self.rng.random() < 0.05:
                # Finger slips onto the key next to Backspace: now one more to delete.
                stray = self.rng.choices(STRAY_KEYS, weights=STRAY_WEIGHTS, k=1)[0]
                self._emit(stray)
                remaining += 1
                self._sleep(self.rng.uniform(0.12, 0.3))
                continue
            self._check_stop()
            self.sink.backspace()
            remaining -= 1
            self._sleep(self.rng.uniform(0.04, 0.09))
        self._sleep(self.rng.uniform(0.05, 0.15))
