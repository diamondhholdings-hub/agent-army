"""Real-time meeting service wrappers -- STT, TTS, and Avatar.

Provides thin async wrappers around external APIs for the real-time
meeting pipeline:
- DeepgramSTT: streaming speech-to-text with Nova-3 and endpointing
- ElevenLabsTTS: streaming text-to-speech with Flash v2.5
- HeyGenAvatar: animated avatar sessions with lip-sync via LiveKit
"""
