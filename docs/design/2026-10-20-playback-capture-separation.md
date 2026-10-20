# Keep reference playback outside microphone capture

The user reported near-inaudible reference audio on an iPhone speaker in the
installed home-screen app after the October 19 session change. Explicitly
holding `play-and-record` throughout the round is not a reliable way to match
the ordinary listening volume. WebKit documents both routing and volume
changes while capture is active:
https://bugs.webkit.org/show_bug.cgi?id=236219 and
https://bugs.webkit.org/show_bug.cgi?id=218012 .

The round now selects `playback` for reference previews with no microphone
held. After all previews finish, acquire capture, prepare its analyser, and
then issue the recording cue. Release capture and restore playback after each
take, including retry and failure paths. Restore the prior session type when
the round exits. Do not set playback while an acquired capture track is active
or apply arbitrary gain compensation.

Tradeoff: device preparation can add a gap before the cue, especially for the
first permission prompt. Nothing preparing the microphone is awaited after
the cue. Update the practice instructions to describe this accurately.

Regression tests exercise zero, one and multiple previews, each of three
takes, normal playback/capture categories, partial failure, and cleanup.
They establish lifecycle order, not physical iPhone output loudness. A real
iPhone home-screen app test is still required to confirm perceived volume.
