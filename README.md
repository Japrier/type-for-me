# type-for-me
It types your clipboard into any app, one keystroke at a time, the way a person would. 


To run it: put the three files in one folder, then run pip install -r requirements.txt and python type_for_me.py.

# How it works:

Paste your text into the field.
Click Type for me.
Click the text box you want it typed into. Clicks on the app’s own window are ignored, and typing starts about 0.7 seconds later.
Press Esc or Stop at any time to cancel.

Two sliders control speed (20–160 WPM) and mistake rate (0–15% of letters).

Mistakes it makes:

Neighbor key: it hits an adjacent key instead, and keeps the capitalization.
- Swapped letters: “teh” for “the”.
- Missing letter: “cndy” for “candy”.
- Doubled letter: “moovie” for “movie”. This is about four times more likely when the word already has a repeated letter.
- Stray key by Backspace: it hits =, - or \ by accident. When it fixes a mistake, its finger sometimes slips onto one of those instead of Backspace, so it needs one more press.

About 40% of mistakes are noticed only at the end of the word, and the rest within 0–3 characters. It keeps a counter of every character typed since the first wrong keystroke, including correct ones typed on top of the mistake, and presses Backspace exactly that many times before retyping.

In the headless test, a fake screen buffer matched the target text across 6,000 randomized runs, including at 100% mistake rate. A sample keystroke log (< is Backspace) looked like this:

  Thd<e mlv<<ovie ... comit<\<=<<mittee ... buulding<<<<<<ilding.
