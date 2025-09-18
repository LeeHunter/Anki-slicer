# Feature Branch Plan – YouTube Workflow

> Working branch: `feature/youtube-workflow`

This document tracks our shared understanding for the YouTube workflow effort. Keep it current so we have a single source of truth even if assistant context resets.

## Standing Instructions
- Keep this plan synchronized with decisions, scope changes, and progress at the end of each working session.
- Log key Codex conversation snippets with `scripts/append_conversation_log.py` so we retain historical discussions.
- Update outstanding tasks when work is started, blocked, or completed.
- Development work is being done on a Apple Silicon Mac so Codex output (e.g. CLI instructions) should assume this platform. 

## Vision
Deliver Anki-Slicer as a truly cross-platform sentence-mining toolkit that runs wherever Anki does. Users should be able to pull YouTube content directly into the familiar slicing workflow, reuse their existing timestamp selections, and study seamlessly across macOS, Windows, Linux, iOS, and Android. Accessibility and localisation parity remain first-class goals so the experience satisfies learners across regions and abilities.

## High-Level Requirements
- [ ] Load YouTube videos via pasted URLs or mobile share intents and present video metadata within the app.
- [ ] Allow users to select subtitle language tracks, remember the last-used choice per user/profile, and fall back gracefully when unavailable.
- [ ] Maintain a watch history so previously used videos can be resumed quickly.
- [ ] Track favorites (starred videos) alongside history for quick access.
- [ ] When cards are exported from a video, surface saved timestamp ranges to jump through highlights.
- [ ] Reuse the existing `player.py` slicing UI for selecting new timestamp segments from YouTube playback.
- [ ] Provide a coherent cross-platform runtime strategy so the codebase builds and runs on Windows, macOS, Linux, iOS, and Android (decision: remain on PySide6/PyQt6 + Qt stack).
- [ ] Ensure new UI/UX components satisfy the accessibility criteria captured in `docs/accessibility_checklist.md`.
- [ ] Integrate localisation support for new strings/features so translations stay in sync with the existing i18n workflow.

## Project Plan
### Milestones & Activities
- **Milestone 1:** Framework decision & architecture spike.
  - Evaluate cross-platform options (Qt mobile, Kivy, Flutter bridge, React Native) and document trade-offs.
  - Prototype minimal YouTube playback wrapper against the preferred stack.
  - Status: ✅ Completed — proceed with PySide6/PyQt6 + Qt; keep Kivy as contingency.
- **Milestone 2:** YouTube URL ingestion + playback integration on desktop.
  - Allow users to paste/share a YouTube URL directly in the player.
  - Display the embedded video alongside the waveform while preserving slicing controls.
  - Add subtitle language selection with persistence.
- **Milestone 3:** Persistence of history, favorites, and card timestamp reuse.
  - Design storage schema for watched videos, favorites, and exported clip metadata.
  - Build UI affordances to revisit history/favorites and jump to saved segments.
- **Milestone 4:** Mobile platform enablement.
  - Port the agreed framework scaffolding to iOS and Android builds.
  - Address platform-specific controls, authentication, and media handling.
  - Run smoke tests across Windows/Linux/macOS to ensure parity.

### Framework Evaluation Criteria
- Maintain Python-centric codebase where possible (reuse existing PyQt/Qt logic).
- Ship on macOS, Windows, Linux, iOS, and Android with a single UI layer or minimal duplication.
- Provide YouTube playback with subtitle control via native APIs or embedded WebEngine.
- Meet accessibility expectations (screen readers, keyboard/touch navigation) in line with `docs/accessibility_checklist.md`.
- Integrate with current localisation workflow (`.ts`/`.qm` catalogs).
- Keep build/distribution tooling manageable (pip/pyproject for desktop, app bundles for mobile) without restrictive licensing.
- Allow reuse of existing Python business logic (audio slicing, Anki export) with minimal bridging.

### Framework Candidates Snapshot
- **PyQt6/PySide6 + Qt for Mobile** — Minimal rewrite, retains existing UI; must validate Qt mobile deployment licensing (PyQt commercial vs PySide LGPL), app store compliance, and binary size.
- **Kivy / KivyMD** — Python-native and mobile-friendly; entails wholesale UI rebuild, uncertain accessibility/i18n parity, but simplifies App Store/Play Store builds.
- **Flutter with Python bridge** — Rich UI and strong mobile support; requires Dart frontend plus Python service, increasing architectural complexity and testing surface.
- **React Native + Python API layer** — Large ecosystem, proven mobile capability; demands full rewrite in JS/TS and native module work for audio features.
- **Tauri (web UI + Rust shell)** — Lightweight desktop distribution; mobile story immature and would need web-based UI rewrite plus Rust/JS bridge to Python logic.

### Evaluation To-Do
- [x] Prototype minimal YouTube playback view using PyQt6 + Qt WebEngine (desktop).
- [x] Document Qt for iOS/Android deployment requirements (toolchains, signing, licensing) and highlight blockers.
- [x] Spike a slim Kivy proof-of-concept replicating key `player.py` interactions to estimate rewrite effort.
- [x] Compile comparison matrix mapping criteria to candidates and recommend a preferred approach.

#### Desktop Prototype Notes
- Script: `scripts/prototype_youtube_webengine.py` (requires `PyQt6` and `PyQt6-WebEngine`).
- Run via `python3 scripts/prototype_youtube_webengine.py <YouTube URL>` to validate playback, subtitle toggle UX, and assess resource usage.
- Observed behaviour (macOS): embedded player loads cleanly with minimal chrome; provides playback controls, captions toggle, and time scrubber. No native YouTube search box when using embed URLs—workflow relies on pasted URLs or mobile share actions.

#### Qt Mobile Deployment Findings
- **iOS toolchain:** Requires Xcode + command-line tools, Qt 6.5+ with iOS kit, and CMake-based build. Packaging/signing flows through Xcode with Apple Developer account (US$99/year) and provisioning profiles.
- **Android toolchain:** Needs Android Studio (SDK, NDK r25+, Java 11), Qt 6.5+ Android kit, and Gradle builds via `androiddeployqt`. Release builds require keystore signing for Play Store submission.
- **Licensing:** PyQt mobile deployment demands commercial license; PySide6 offers LGPL path but mandates dynamic linking, shipping Qt plugins, and providing license notices/relinking options.
- **Binary size/performance:** Qt WebEngine (Chromium) adds ~80–100 MB uncompressed; evaluate whether WebEngine ships on mobile or if we migrate to native webview.
- **Store compliance:** App Store disallows JIT; Python runtime must be statically embedded. Investigate PySide6 + Shiboken cross-compilation versus alternative runtimes if Qt proves too heavy.
- **Risks:** Build pipelines are complex (CMake + platform SDKs); CI needs macOS hosts (iOS) and Android SDK setups. Assess maintenance overhead before mobile beta.

#### Kivy Prototype Notes
- Script: `scripts/prototype_kivy_player.py` (requires `kivy[base]`). Shows subtitle text, translation editor, slider, waveform placeholder, start/end adjust buttons, extend button, and deck/source inputs.
- Layout mirrors touch-first interactions well, but accessibility (screen reader focus, keyboard navigation) will need manual wiring. Styling differs from Qt; would require custom theme work for desktop parity.
- Next checks: evaluate embedding audio playback/waveform rendering (e.g., `kivy_garden.graph`) and thread-safe integration with existing Python slicing logic.

### Framework Comparison Matrix (Desktop + Mobile)

| Criteria | PyQt6/PySide6 + Qt Mobile | Kivy / KivyMD | Flutter + Python bridge | React Native + Python API | Tauri (web UI + Rust shell) |
| --- | --- | --- | --- | --- | --- |
| **Code reuse** | Reuses current code extensively; minimal adjustments | Requires full UI rewrite | Python logic split behind Dart frontend | Complete UI rewrite; Python as backend | Requires web UI rewrite + Rust/JS bridge |
| **Platform reach** | Desktop + iOS/Android via Qt kits | Desktop + iOS/Android via Kivy buildozer | Strong on iOS/Android; desktop via Flutter | Strong mobile; desktop via Electron-like wrappers | Desktop focus; mobile story immature |
| **YouTube playback** | Qt WebEngine/ native webview integration available | Needs webview widget or native player bridging | WebView/YouTube Player plugins available | WebView/YouTube modules abundant | Relies on webview; limited mobile support |
| **Accessibility** | Qt has mature accessibility APIs | Kivy accessibility limited; extra work | Flutter supports accessibility but requires Dart | RN supports accessibility; need JS implementation | Depends on web accessibility; mobile limited |
| **Localisation** | Existing `.ts`/`.qm` pipeline works | Requires new localisation workflow | Flutter's intl packages; separate process | RN i18n libs; separate process | Web i18n libraries; separate process |
| **Licensing** | PyQt commercial or PySide LGPL obligations | MIT-friendly | Flutter/Dart (BSD) + extra Python bridge maintenance | MIT (RN) + bridging overhead | MIT-like; but Rust/JS rewrite |
| **Build complexity** | High (Qt Creator, CMake, iOS/Android toolchains) | Moderate (buildozer, Kivy packaging) | High (Dart/Flutter + Python integration) | High (JS/TS + native modules + Python services) | Moderate for desktop; mobile nascent |
| **Team familiarity** | Continuity with existing PyQt expertise | New framework & paradigms to learn | Dart/Flutter ramp-up required | JS/TS + native bridging knowledge needed | Requires web stack + Rust |
| **Binary size** | Large (Qt + WebEngine) | Moderate | Moderate to large | Moderate | Small (desktop), mobile unclear |
| **Recommendation** | **Leading option** if mobile licensing resolved | Secondary; consider if Qt mobile cost/risks block | Heavy rewrite; likely out of scope | Heavy rewrite; high complexity | Desktop only; not suitable for mobile |

Recommendation: Stay on the Qt stack (PySide6 preferred for LGPL-friendly mobile builds) unless mobile licensing or performance proves untenable. Kivy remains the fallback if Qt mobile packaging becomes impractical.

## YouTube Discovery & Playback
### YouTube URL Workflow Design
- Primary interaction: user pastes or shares a YouTube URL into the player. We parse the video ID, embed the YouTube player next to the waveform, and keep the slicing controls active on the local audio track.
- UI flow:
  1. URL field + Load button lives above the media panel; paste/enter triggers embed load.
  2. When a video is loaded, show the embedded player (autoplay optional) while leaving the waveform slider and segment controls visible for precise clipping.
  3. Persist the last-used URL in settings so the field restores between sessions.
- Auto-fetch captions via YouTube transcript API when available so the original subtitle column populates without manual SRT files; fall back gracefully if transcripts are disabled.
- Accessibility: label the URL input clearly, provide keyboard shortcut to focus it, and announce load failures (invalid URL, embed errors) through accessible dialogs/messages.
- Error handling: detect invalid/malformed IDs, handle YouTube playback errors (e.g., restricted embeds), and fall back to waveform-only mode if streaming fails.
- Future enhancements: detect when the share sheet on Android/iOS passes a URL, auto-load it into the field, and keep a per-video history for quick revisit.
- **Speech/translation automation (future):** Explore integrating online ASR (e.g., Qwen3-ASR or other speech APIs) plus translation services (DeepL, etc.) so users can generate transcripts/translations even when a YouTube video lacks subtitles. Requires API evaluation (latency, cost, quotas) and UI hooks to manage generated content.

#### Detailed Flow Mapping
- **UI Regions**
  - `MediaPanel`: stacked widget containing the waveform controls and the embedded player; defaults to waveform, switches to the embed when a video ID is loaded.
  - `MetadataForm`: retains deck/tags inputs; the prior “Source” field now acts as the URL text box in the media panel.
- **Primary Interactions**
  1. User pastes URL → click Load (or press Enter if we add it) → parse ID → embed video.
  2. User can toggle back to waveform-only mode (future enhancement) or continue slicing while the video provides reference context.
- **State Overview**
  - `Idle` (waveform only) → `LoadingVideo` (embed pending) → `VideoReady` once the iframe confirms load; error state displays friendly message and returns to waveform.
- **Data Storage**
  - Store the most recent URL per project/user in `QSettings` (`anki_source`). History/favorites and clip reuse will be captured in future persistence work (Milestone 3).
- **Edge Cases**
  - Invalid URL or blocked embeds (error 153) produce a warning dialog and keep the waveform active.
  - Missing network or embed failures fall back to waveform view automatically.

### YouTube API Usage Plan
- **Authentication:** Start with API key stored in user config (`~/.anki_slicer/config.json`) and optional environment override (`ANKI_SLICER_YT_API_KEY`). Plan for OAuth fallback if future features require write scopes (e.g., playlist management).
- **Quota management:** Loading by video ID uses `videos.list` (~1 unit per call) and optional `captions.list`. Cache metadata responses for 24 hours to avoid duplicate calls.
- **Rate limiting:** Implement exponential backoff and surface friendly error messages when quota exceeds limits. Encourage users to supply personal API keys for heavy usage.
- **Caching:** Store raw API payloads in SQLite (`yt_cache` table with response JSON + expiry). Use ETag headers to detect changes. For captions, cache language codes and download URLs when available.
- **Error handling:** Gracefully handle HTTP errors (403 quota, 429 rate limit, 404 deleted/geo-restricted). Mark history items with status flags so users understand unavailable content.
- **Telemetry:** Record request counts and quota consumption locally so users can gauge remaining daily usage.

## Dependencies & Risks
- YouTube API quotas & authentication — may require API key management and caching strategies; heavy usage could exhaust shared quotas.
- Subtitle availability varies per video — need fallback UX, warnings, or alternative subtitle fetching.
- Cross-platform framework choice impacts future velocity; risk of rework if decision shifts late.
- Mobile app distribution (App Store / Play Store) introduces signing and review requirements.
- Existing codebase is Python/Qt; bridging to mobile may demand additional tooling (PySide/Shiboken licensing, Pyodide, or alternative runtimes).
- Meeting accessibility standards across platforms may require platform-specific adjustments (screen reader labels, color contrast, focus handling).
- Localisation expansion increases translation overhead; need process to keep `.ts/.qm` files current.

## Outstanding Tasks
- [ ] Map current `player.py` functionality to required mobile touch interactions.
- [ ] Create data model for storing watch history, favorites, and timestamped clips.
- [ ] Review `docs/accessibility_checklist.md` updates for YouTube features and translate items into engineering work.
- [ ] Audit localisation workflow to ensure new video-related strings ship with translations.
- [ ] Outline a future Settings/Preferences screen (translation provider, API keys, responsive toggles).

## Done
- [x] Decide on cross-platform framework and document rationale. ✅ (Framework chosen; update once implementation notes are in place.)
- [x] Draft API usage limits and authentication strategy for YouTube access. ✅ (Documented above; convert to actionable implementation tasks.)

### Implementation Tasks – YouTube URL Flow
- [x] Add URL input and load button to player panel in place of the old Source field.
- [x] Parse YouTube IDs from common share links (`youtu.be`, `/watch`, `/shorts`, `/embed`).
- [x] Embed video via iframe with spoofed Chrome user agent and `nocookie` domain to avoid error 153.
- [x] Wire the original/translation caption widgets to load available tracks via the YouTube caption endpoints (yt-dlp-backed).
- [x] Sync embedded playback state with waveform slider (play/pause, position updates).
- [x] Filter caption dropdowns to hide same-language translation duplicates that cause misleading matches.
- [ ] Improve subtitle search accuracy when translation tracks drift out of sync (low priority polish).
- [x] Integrate Google Translate for on-demand sentence/word lookup (default provider).
- [ ] Expose translation provider configuration via future Settings screen.
- [ ] Audit player layouts for responsive breakpoints (desktop/tablet/phone) and capture follow-up adjustments.
- [ ] Trigger automatic loads from OS-level share intents (Android/iOS) when available.
- [ ] Persist per-video metadata (history, favorites, exported clips) in SQLite.
- [ ] Provide keyboard shortcut to focus the URL field and announce load failures via accessible dialogs.

### Accessibility Engineering Tasks
- [ ] Implement accessible captions/subtitle toggles in the YouTube player surface (expose ARIA roles + labels).
- [ ] Surface fallback messaging when subtitles are missing or delayed, including screen-reader friendly status updates.
- [ ] Ensure YouTube history/favorites lists announce counts and provide descriptive labels (title, channel, duration).
- [ ] Update favorites/star controls to expose toggled state via text or accessible description beyond icon color.
- [ ] Validate video playback controls for keyboard operation and non-drag adjustments across desktop/mobile.
- [ ] Extend automated QA checklist to include VoiceOver/NVDA/TalkBack smoke passes for video flows.
- [ ] Define responsive QA scenarios (narrow widths, portrait orientation, touch targets) and add to regression suites.

### Localisation Workflow Notes
- Current assets: `anki_slicer/locale/anki_slicer_en_US.ts`; treat as canonical source catalog. Former `anki_slicer_en.ts` removed after migration.
- Use Qt Linguist toolchain (`pylupdate6` / `lrelease`) to refresh translation catalogs after UI changes; helper script `scripts/update_translations.sh` added.
- Need a process to harvest new strings from YouTube features early to avoid translation debt.

### Localisation Action Items
- [x] Migrate any strings from `anki_slicer_en.ts` into `anki_slicer_en_US.ts` and remove the former.
- [x] Script a helper (Makefile/task runner) to regenerate `.ts`/`.qm` files post feature additions.
- [x] Audit `i18n.py` to ensure new YouTube UI strings are wrapped with `tr()`/`QCoreApplication.translate`.

## Notes & Decisions Log
- _2025-09-17:_ Feature scope confirmed to include YouTube search, subtitle selection persistence, history/favorites, clip reuse, localisation, and accessibility commitments across desktop & mobile. (Search later descoped on 2025-09-18.)
- _2025-09-17:_ Localisation inventory shows existing English `.ts` catalog only; tooling/process updates required when new YouTube strings land.
- _2025-09-17:_ Defer non-English translation work until post-YouTube release; maintain a single English source catalog in the interim.
- _2025-09-17:_ Removed redundant `anki_slicer_en.ts`; `anki_slicer_en_US.ts` now serves as the sole English catalog.
- _2025-09-17:_ Added `scripts/update_translations.sh` and verified Qt Linguist CLI tools via pip-installed PyQt6.
- _2025-09-17:_ Confirmed `i18n.tr()` helper is the standard entry point; new YouTube UI must continue using `self.tr(...)` wrappers.
- _2025-09-17:_ Framework decision: proceed with PySide6/PyQt6 + Qt stack; retain Kivy as fallback if mobile deployment becomes untenable.
- _2025-09-17:_ Removed YouTube search dock; player now embeds videos from pasted URLs alongside the waveform.
- _2025-09-18:_ In-app YouTube search permanently descoped; rely on pasted URLs and mobile share intents for video ingestion.
- _2025-09-17:_ Switched embed view to `youtube-nocookie` domain with Chrome user agent spoof and iframe wrapper (base URL `http://localhost`) to avoid YouTube error 153.
- _2025-09-18:_ Subtitle search still shows occasional translation drift false positives; track as polish item rather than blocking bug.
- _2025-09-18:_ Translate tool wired to Google Translate by default; Settings screen needed later for provider configuration.
