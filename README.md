# Anki-slicer

A utility to take an audio file (the most common filetypes) and 2 SRT files (original text &amp; translation), select the sentences you want to learn and then export them into Anki in bulk.  

Prerequisites:
 - Anki and AnkiConnect (must be running).
 - An audio file with two standard SRT (subtitle) files. One with transcription and one of translation.  

I use McWhisper (a paid app) to create the SRT files directly from a YouTube video, audio file or whatever. It also allows me to export the audio as a separate file. It's quick and easy. There are also other tools you can use to get SRT files from YouTube audio, then run them through AI etc. I find it's just a LOT easier to use McWhisper. 

**How to Use Anki-Slicer**

 - Ensure Anki (with the Anki-Connect) plugin is running.
 - Open **Anki-Slicer**.
 - Select your audio file and the two SRT format files (the transcription of the original and the  translation)
 - Click **Start**. 
 - Use the **Mode** button on the right to select **Continuous** or **Auto-pause** play.
 - Click **Play** to play the file or use the slider to play from a different location.
 - Click **Flag for Anki** to add a sentence to the queue.
 - Click the checkboxes to unselect/select a sentence.
 - Click Export Selection to Anki. Each line in the queue will become an Anki card.

In Anki, the cards will be created in the AnkiSlicer deck. You can rename the deck in Anki desktop if you want to create several different decks.  You could also enhance the translation SRT file by running it through AI and asking it to provide more explanations, transliterations (e.g. pinyin for Chinese), etc. Then when use it in Anki-slicer that extra information will be added to the answer side of the card. 


Anki-slicer has so far only been tested on a single Mac computer. YMMV

