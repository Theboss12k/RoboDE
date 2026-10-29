import { useEffect, useRef, useState } from "react";
type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult:
    | ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void)
    | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};
type VoiceWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};
export function useVoice(
  text: string,
  onText: (text: string) => void,
  onError: (error: string) => void,
) {
  const engine = useRef<Recognition | null>(null);
  const [listening, setListening] = useState(false);
  const browser = window as VoiceWindow;
  const supported = !!(
    browser.SpeechRecognition ?? browser.webkitSpeechRecognition
  );
  useEffect(
    () => () => {
      if (engine.current) {
        engine.current.onresult = null;
        engine.current.onend = null;
        engine.current.onerror = null;
        engine.current.abort();
      }
    },
    [],
  );
  function toggle() {
    if (listening) {
      engine.current?.stop();
      return;
    }
    const Constructor =
      browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
    if (!Constructor) {
      onError(
        "Voice input is not supported in this browser. You can still type or use your keyboard’s microphone.",
      );
      return;
    }
    if (!window.isSecureContext) {
      onError(
        "Microphone input needs HTTPS or localhost. Ask your administrator for the secure workspace link.",
      );
      return;
    }
    const recognition = new Constructor();
    engine.current = recognition;
    recognition.lang = navigator.language || "en-US";
    recognition.interimResults = true;
    recognition.continuous = false;
    const prefix = text.trim();
    recognition.onresult = (e) => {
      const transcript = Array.from(e.results)
        .map((r) => r[0]?.transcript ?? "")
        .join(" ");
      onText(((prefix ? prefix + " " : "") + transcript).slice(0, 4000));
    };
    recognition.onend = () => {
      setListening(false);
      engine.current = null;
    };
    recognition.onerror = (e) => {
      setListening(false);
      onError(
        e.error === "not-allowed"
          ? "Microphone access was denied. Allow it in your browser settings, or type your command."
          : e.error === "no-speech"
            ? "No speech was heard. Try again, or type your command."
            : "Voice input is unavailable right now. You can type your command.",
      );
    };
    try {
      recognition.start();
      setListening(true);
    } catch {
      onError(
        "The microphone could not start. Check your browser permissions.",
      );
    }
  }
  return { supported, listening, toggle, stop: () => engine.current?.stop() };
}
