// Mic capture via the Web Audio API. The stream is created ONLY after the
// native helper emits a "press" (start) event and is fully torn down on
// "release" or after a safety watchdog timeout. Nothing at mount time.

import { useEffect, useState } from "react";

const SAMPLE_RATE = 16000;
const CHUNK_MS = 100;
const MAX_DICTATION_MS = 60_000;  // safety cap: force-stop after 60s

function pcm16FromFloat32(floats: Float32Array): Uint8Array {
  const buf = new ArrayBuffer(floats.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < floats.length; i++) {
    let s = Math.max(-1, Math.min(1, floats[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Uint8Array(buf);
}

function base64(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s);
}

export type CaptureMode = "dictation" | "command";

export function useAudioCapture() {
  const [capturing, setCapturing] = useState(false);
  const [mode, setMode] = useState<CaptureMode>("dictation");

  useEffect(() => {
    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;
    let processor: ScriptProcessorNode | null = null;
    let source: MediaStreamAudioSourceNode | null = null;
    let buffer: Float32Array[] = [];
    let bufferedSamples = 0;
    let watchdog: number | null = null;
    let active = false;
    const flushEvery = Math.floor((SAMPLE_RATE * CHUNK_MS) / 1000);

    async function start() {
      if (active) return;  // ignore duplicate press events from the helper
      active = true;
      setCapturing(true);
      watchdog = window.setTimeout(() => {
        console.warn("[audio] watchdog — forcing stop after", MAX_DICTATION_MS, "ms");
        stop();
      }, MAX_DICTATION_MS);
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, sampleRate: SAMPLE_RATE, echoCancellation: true, noiseSuppression: true },
        });
      } catch (e) {
        console.error("[audio] getUserMedia failed:", e);
        stop(); return;
      }
      ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
      source = ctx.createMediaStreamSource(stream);
      processor = ctx.createScriptProcessor(4096, 1, 1);
      processor.onaudioprocess = async (e) => {
        if (!active) return;
        const input = e.inputBuffer.getChannelData(0);
        buffer.push(new Float32Array(input));
        bufferedSamples += input.length;
        if (bufferedSamples >= flushEvery) {
          const flat = new Float32Array(bufferedSamples);
          let off = 0;
          for (const b of buffer) { flat.set(b, off); off += b.length; }
          buffer = []; bufferedSamples = 0;
          try { await window.miniflow.sendAudioChunk(base64(pcm16FromFloat32(flat))); }
          catch (err) { console.error("[audio] sendAudioChunk", err); }
        }
      };
      source.connect(processor);
      // IMPORTANT: do NOT connect to ctx.destination — that would loop the mic
      // to the speakers. We pipe audio out via our onaudioprocess handler and
      // send it to the Python backend. Keep the processor node alive via a
      // zero-gain sink so it continues to receive samples.
      const sink = ctx.createGain();
      sink.gain.value = 0;
      processor.connect(sink);
      sink.connect(ctx.destination);
    }

    function stop() {
      if (!active && !stream && !ctx) {
        setCapturing(false);
        return;
      }
      active = false;
      setCapturing(false);
      if (watchdog) { clearTimeout(watchdog); watchdog = null; }
      try { processor?.disconnect(); } catch {}
      try { source?.disconnect(); } catch {}
      // Stop EVERY mic track explicitly so macOS drops the orange indicator.
      try { stream?.getTracks().forEach((t) => t.stop()); } catch {}
      try { ctx?.close(); } catch {}
      stream = null; ctx = null; processor = null; source = null;
      buffer = []; bufferedSamples = 0;
    }

    const offStart = window.miniflow.onStartCapture((p: any) => {
      setMode(p?.mode === "command" ? "command" : "dictation");
      start().catch(console.error);
    });
    const offStop  = window.miniflow.onStopCapture(() => stop());

    // If the window loses visibility (popover hides), force-stop the mic.
    const onVis = () => { if (document.hidden) stop(); };
    document.addEventListener("visibilitychange", onVis);

    return () => {
      offStart(); offStop();
      document.removeEventListener("visibilitychange", onVis);
      stop();
    };
  }, []);

  return { capturing, mode };
}
