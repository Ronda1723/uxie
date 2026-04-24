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
    let sink: GainNode | null = null;
    let buffer: Float32Array[] = [];
    let bufferedSamples = 0;
    let watchdog: number | null = null;
    let active = false;
    const flushEvery = Math.floor((SAMPLE_RATE * CHUNK_MS) / 1000);

    async function start() {
      // Defensive cleanup: if a prior session leaked (e.g. sleep ate the
      // fn-release event, or the helper's event tap got disabled by macOS),
      // the previous stream/ctx/processor are still alive. Tearing them down
      // before acquiring a new mic prevents orange-dot-forever bugs.
      if (active || stream || ctx) {
        console.warn("[audio] start called with leftover state — cleaning up first");
        await stop();
      }
      active = true;
      setCapturing(true);
      watchdog = window.setTimeout(() => {
        console.warn("[audio] watchdog — forcing stop after", MAX_DICTATION_MS, "ms");
        stop().catch(console.error);
      }, MAX_DICTATION_MS);
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            sampleRate: SAMPLE_RATE,
            // EC/NS off — macOS's aggressive cancellation was scrubbing soft speech to silence.
            echoCancellation: false,
            noiseSuppression: false,
            // AGC on — normalizes voice level so transcription quality stays consistent
            // across different mic distances / speaker volumes.
            autoGainControl: true,
          },
        });
      } catch (e) {
        console.error("[audio] getUserMedia failed:", e);
        stop(); return;
      }
      ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
      source = ctx.createMediaStreamSource(stream);
      processor = ctx.createScriptProcessor(4096, 1, 1);
      let chunkIdx = 0;
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
          // Log energy of first few chunks to diagnose silent-mic issues.
          if (chunkIdx < 3) {
            let sumSq = 0;
            for (let i = 0; i < flat.length; i++) sumSq += flat[i] * flat[i];
            const rms = Math.sqrt(sumSq / flat.length);
            console.log(`[audio] chunk ${chunkIdx} rms=${rms.toFixed(4)} samples=${flat.length}`);
            chunkIdx++;
          }
          try { await window.miniflow.sendAudioChunk(base64(pcm16FromFloat32(flat))); }
          catch (err) { console.error("[audio] sendAudioChunk", err); }
        }
      };
      source.connect(processor);
      // IMPORTANT: do NOT connect to ctx.destination — that would loop the mic
      // to the speakers. We pipe audio out via our onaudioprocess handler and
      // send it to the Python backend. Keep the processor node alive via a
      // zero-gain sink so it continues to receive samples.
      sink = ctx.createGain();
      sink.gain.value = 0;
      processor.connect(sink);
      sink.connect(ctx.destination);
    }

    async function stop() {
      if (!active && !stream && !ctx) {
        setCapturing(false);
        return;
      }
      active = false;
      setCapturing(false);
      if (watchdog) { clearTimeout(watchdog); watchdog = null; }
      // Order matters for macOS to drop the orange mic indicator promptly.
      // 1) Suspend the context so onaudioprocess stops firing.
      try { if (ctx && ctx.state !== "closed") await ctx.suspend(); } catch {}
      // 2) Disconnect every node (including the sink → destination link that
      //    the old stop() forgot; Chromium treats a connected graph as "in
      //    use" and delays releasing the underlying MediaStream).
      try { processor?.disconnect(); } catch {}
      try { sink?.disconnect(); } catch {}
      try { source?.disconnect(); } catch {}
      if (processor) processor.onaudioprocess = null;
      // 3) Remove + stop each mic track explicitly. removeTrack() before
      //    stop() helps Chromium tear the MediaStream down.
      try {
        stream?.getTracks().forEach((t) => {
          try { stream?.removeTrack(t); } catch {}
          try { t.stop(); } catch {}
        });
      } catch {}
      // 4) Actually await ctx.close() so the resource is fully released
      //    before we drop the reference — otherwise macOS keeps the orange
      //    dot on until the GC eventually runs.
      try { if (ctx && ctx.state !== "closed") await ctx.close(); } catch {}
      stream = null; ctx = null; processor = null; source = null; sink = null;
      buffer = []; bufferedSamples = 0;
      console.log("[audio] mic released");
    }

    const offStart = window.miniflow.onStartCapture((p: any) => {
      setMode(p?.mode === "command" ? "command" : "dictation");
      start().catch(console.error);
    });
    const offStop  = window.miniflow.onStopCapture(() => { stop().catch(console.error); });

    return () => {
      offStart(); offStop();
      stop().catch(console.error);
    };
  }, []);

  return { capturing, mode };
}
