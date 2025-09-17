# Accessibility Checklist

Track these items while building features (especially the upcoming YouTube workflow) so the UI stays inclusive. Check off each item before release.

## Screen Readers & Semantics
- [ ] Every interactive widget has meaningful `setAccessibleName`/`setAccessibleDescription` text.
- [ ] Custom widgets (e.g., waveform, segment adjuster) expose accessibility interfaces or alternative descriptions.
- [ ] Dialog titles and status messages use simple, descriptive language.

## Keyboard Navigation
- [ ] Tab order flows logically and reaches all controls (no mouse-only actions).
- [ ] Provide keyboard shortcuts for primary actions (play/pause, extend, create card, search, confirm dialogs).
- [ ] Visible focus indicator remains clear on all focusable elements.

## Visual Design
- [ ] Text and icon colors meet WCAG AA contrast requirements against their backgrounds.
- [ ] The layout adapts to larger system fonts / UI scaling without clipping text or controls.
- [ ] Color is never the sole means of conveying state; pair it with text, icon changes, or patterns.
- [ ] Provide (or plan for) a high-contrast theme toggle.

## Audio & Feedback
- [ ] Operations that take noticeable time show textual progress or status feedback.
- [ ] Success/error notifications have both visual and optional auditory cues.
- [ ] Audio playback controls support precise adjustments without drag gestures only.

## Content Presentation
- [ ] Subtitle editors support large fonts and expose zoom controls or shortcuts.
- [ ] Markdown/HTML output for Anki preserves semantic structure (headings, lists) for screen readers.
- [ ] Source/metadata fields display full text via tooltips or ellipsis with keyboard-accessible reveal.

## Documentation & Testing
- [ ] Document accessibility features and keyboard shortcuts in the README/user guide.
- [ ] Smoke test with at least one screen reader (VoiceOver/NVDA) before major releases.
- [ ] Include accessibility considerations in code review checklists.

Feel free to expand this document as new workflows (e.g., video integration) introduce additional requirements.
