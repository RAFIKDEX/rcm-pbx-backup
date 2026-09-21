# DEXTER Phone Architecture

## Overview
DEXTER Phone is a production-grade WebRTC/SIP softphone built on SIP.js, integrating natively with Asterisk PBX via SIP over Secure WebSockets (WSS).

## Subsystems

### SIP Signaling Layer
- **Library**: `sip.js` v0.21.2
- **Transport**: WSS (WebSocket Secure) on port 8088/8089 (proxied via Apache `/ws`).
- **Registration**: SIP Digest Authentication.
- **Dialog Management**: Native SIP INVITE, re-INVITE (Hold), REFER (Transfer).

### WebRTC Media Layer
- **Engine**: Browser RTCPeerConnection API.
- **Audio Codecs**: G.722 (HD), PCMU/PCMA, Opus.
- **Security**: DTLS-SRTP for all media streams.
- **ICE**: Native browser ICE gathering.

### Conference & Audio Processing Layer
- **Engine**: Web Audio API `AudioContext`.
- **Topology**: Client-side Mix-Minus Bridge.
- **Mechanism**: Extracts remote `MediaStream` tracks, mixes them with local microphone input via `MediaStreamAudioDestinationNode`, and seamlessly hot-swaps the outbound `RTCRtpSender` tracks without interrupting the SIP dialogs.

### UI & State Layer
- **Stack**: Vanilla JS + HTML5 + CSS3 (No heavy frameworks).
- **Theme**: Dark/Light mode, responsive constraints.
- **Reactivity**: DOM updates are strictly bound to SIP.js `SessionState` event listeners (Established, Terminated, etc.). The UI never assumes call state; it only reflects the SIP engine's reality.
