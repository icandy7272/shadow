# Sentence boundaries and iPhone capture audio

## Sentence boundary

The six-second unit limit favored the comma in “We worked hard and in ten
years,”, leaving its main clause in the next unit. Temporal-unit commas now
have lower split priority. For segment 10, unit 5 extends through “in a garage”
(19 words, approximately 4.9 seconds in the regenerated reference clip).

Keep the legacy split when a revised sentence would change its unit count:
ordinal URLs and later recordings must not shift. Existing recordings remain
available, but a run with different reference text cannot receive appended takes;
the corrected phrase requires a new run.

## iPhone speaker playback

Reported environment: iPhone speaker, installed home-screen web app. Opening
the microphone can change the system audio category and its volume. Select
`play-and-record` before microphone/context initialization where Audio Session
API is supported, and restore the previous category after releasing capture.
Disable call-oriented echo cancellation, noise suppression and automatic gain
for this sequential listen-then-record flow. Keep the existing post-capture
analyser initialization required by iOS; never connect microphone input to the
speaker destination. Disconnect analysis nodes on cleanup.

References: https://www.w3.org/TR/audio-session/ and
https://bugs.webkit.org/show_bug.cgi?id=243897 . The browser controls support
for media constraints and output routing; volume and noise must still be
checked on the reported physical iPhone. No fixed gain compensation is applied.

## Verification

601 Python tests and 120 JavaScript tests pass, including temporal split,
changed-reference append rejection, capture category restoration and analyser
cleanup. Derived reference audio for 10/5 was regenerated; historical recordings
were not modified.
