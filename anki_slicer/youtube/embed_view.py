"""YouTube embed view with simple playback controls via WebChannel."""

from __future__ import annotations

import json

from PyQt6.QtCore import QUrl, QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtWebChannel import QWebChannel


class YouTubeBridge(QObject):
    ready = pyqtSignal()
    durationChanged = pyqtSignal(float)
    timeChanged = pyqtSignal(float)
    stateChanged = pyqtSignal(int)

    @pyqtSlot()
    def signalReady(self) -> None:
        self.ready.emit()

    @pyqtSlot(float)
    def reportDuration(self, seconds: float) -> None:
        self.durationChanged.emit(seconds)

    @pyqtSlot(float)
    def reportTime(self, seconds: float) -> None:
        self.timeChanged.emit(seconds)

    @pyqtSlot(int)
    def reportState(self, state: int) -> None:
        self.stateChanged.emit(state)


class YouTubeEmbedView(QWebEngineView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.settings().setAttribute(self.settings().WebAttribute.PluginsEnabled, True)
        self._ensure_user_agent()

        self.bridge = YouTubeBridge()
        self.bridge.ready.connect(self._on_js_ready)

        self._channel = QWebChannel(self.page())
        self._channel.registerObject("youtubeBridge", self.bridge)
        self.page().setWebChannel(self._channel)

        self._ready = False
        self._pending_video: tuple[str, bool] | None = None
        self._last_seek_seconds: float | None = None

        self.setHtml(self._html_shell(), QUrl("https://www.youtube-nocookie.com"))

    # ------------------------------------------------------------------
    @property
    def is_ready(self) -> bool:
        return self._ready

    def load_video(self, video_id: str, autoplay: bool = False) -> None:
        self._pending_video = (video_id, autoplay)
        if self._ready:
            self._invoke_load(video_id, autoplay)

    def seek_to(self, seconds: float, force: bool = False) -> None:
        if not self._ready:
            return
        if not force and self._last_seek_seconds is not None:
            if abs(self._last_seek_seconds - seconds) < 0.1:
                return
        self._last_seek_seconds = seconds
        self._run_js(f"seekTo({json.dumps(seconds)})")

    def set_playing(self, playing: bool) -> None:
        if not self._ready:
            return
        self._run_js(f"setPlaybackState({json.dumps(bool(playing))})")

    def _invoke_load(self, video_id: str, autoplay: bool) -> None:
        self._last_seek_seconds = None
        self._run_js(
            f"loadVideo({json.dumps(video_id)}, {1 if autoplay else 0})"
        )

    def _run_js(self, script: str) -> None:
        self.page().runJavaScript(script)

    def _on_js_ready(self) -> None:
        self._ready = True
        if self._pending_video:
            vid, auto = self._pending_video
            self._invoke_load(vid, auto)

    @staticmethod
    def _ensure_user_agent() -> None:
        profile = QWebEngineProfile.defaultProfile()
        ua = profile.httpUserAgent()
        if "Chrome" in ua and "anki-slicer" not in ua:
            profile.setHttpUserAgent(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"  # trimmed UA avoids YouTube embed error 15
            )

    def _html_shell(self) -> str:
        return """
<!DOCTYPE html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <style>
      html, body {
        margin: 0;
        padding: 0;
        height: 100%;
        background-color: #000;
      }
      #player {
        width: 100%;
        height: 100%;
      }
    </style>
    <script src=\"https://www.youtube.com/iframe_api\"></script>
    <script src=\"qrc:///qtwebchannel/qwebchannel.js\"></script>
  </head>
  <body>
    <div id=\"player\"></div>
    <script>
      var bridge = null;
      var player = null;
      var channelReady = false;
      var apiReady = false;
      var pendingLoad = null;

      new QWebChannel(qt.webChannelTransport, function(channel) {
        bridge = channel.objects.youtubeBridge;
        channelReady = true;
        maybeSignalReady();
      });

      function onYouTubeIframeAPIReady() {
        apiReady = true;
        maybeSignalReady();
      }

      function maybeSignalReady() {
        if (channelReady && apiReady && bridge && bridge.signalReady) {
          bridge.signalReady();
        }
      }

      function ensurePlayer(videoId, autoplay) {
        if (player) {
          if (autoplay) {
            player.loadVideoById(videoId);
          } else {
            player.cueVideoById(videoId);
          }
          return;
        }
            player = new YT.Player('player', {
          videoId: videoId,
          width: '100%',
          height: '100%',
          host: 'https://www.youtube-nocookie.com',
          playerVars: {
            'autoplay': autoplay ? 1 : 0,
            'controls': 1,
            'rel': 0,
            'modestbranding': 1,
            'playsinline': 1,
            'origin': 'https://www.youtube-nocookie.com'
          },
          events: {
            'onReady': onPlayerReady,
            'onStateChange': onPlayerStateChange
          }
        });
      }

      function loadVideo(videoId, autoplay) {
        if (!apiReady || !channelReady) {
          pendingLoad = {id: videoId, autoplay: autoplay};
          return;
        }
        ensurePlayer(videoId, autoplay);
      }

      function onPlayerReady(event) {
        if (player && player.mute) {
          player.mute();
        }
        if (bridge && bridge.reportDuration) {
          bridge.reportDuration(event.target.getDuration());
        }
        window.clearInterval(window.__ytTimeInterval);
        window.__ytTimeInterval = setInterval(function(){
          if (!player || !bridge || !bridge.reportTime) return;
          var current = player.getCurrentTime ? player.getCurrentTime() : 0;
          bridge.reportTime(current);
        }, 250);
        if (pendingLoad) {
          ensurePlayer(pendingLoad.id, pendingLoad.autoplay);
          if (!pendingLoad.autoplay && player) {
            player.pauseVideo();
          }
          pendingLoad = null;
        }
      }

      function onPlayerStateChange(event) {
        if (bridge && bridge.reportState) {
          bridge.reportState(event.data);
        }
      }

      function seekTo(seconds) {
        if (player && player.seekTo) {
          player.seekTo(seconds, true);
        }
      }

      function setPlaybackState(shouldPlay) {
        if (!player) return;
        if (shouldPlay) {
          player.playVideo();
        } else {
          player.pauseVideo();
        }
      }

      window.seekTo = seekTo;
      window.setPlaybackState = setPlaybackState;
      window.loadVideo = loadVideo;
    </script>
  </body>
</html>
"""
