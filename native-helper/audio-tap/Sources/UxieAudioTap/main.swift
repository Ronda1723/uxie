// uxie-audio-tap — captures mic + system audio on macOS, mixes to 16 kHz
// mono PCM (signed 16-bit little-endian), writes raw samples to stdout.
//
// Stops cleanly when stdin EOFs (i.e. the parent — meetings.py — closes the
// pipe). Errors go to stderr; stdout is reserved for the audio stream so the
// parent can read it without delimiters.
//
// Architecture:
//   ┌──────────────────────────────┐
//   │ AVAudioEngine (mic)          │──┐
//   └──────────────────────────────┘  │  resample → 16kHz mono Float32
//                                     ├──► ring buffer ──► mix ──► Int16 LE ──► stdout
//   ┌──────────────────────────────┐  │
//   │ ScreenCaptureKit (system)    │──┘
//   └──────────────────────────────┘
//
// The mixer drains the two ring buffers in lockstep — emits one mixed
// 10 ms frame (160 samples @ 16 kHz) every time both buffers have ≥ 160
// samples available. Skew between the two streams stays bounded.

import AVFoundation
import Foundation
import ScreenCaptureKit

let OUTPUT_SAMPLE_RATE: Double = 16_000
let OUTPUT_CHANNELS: AVAudioChannelCount = 1
let FRAME_SAMPLES: Int = 160  // 10 ms @ 16 kHz

// stderr helper — never write logs to stdout (that's the audio pipe).
func logErr(_ msg: String) {
    let line = "[audio-tap] \(msg)\n"
    if let data = line.data(using: .utf8) {
        FileHandle.standardError.write(data)
    }
}

// MARK: - Ring buffer

/// Lock-protected Float32 ring backing both mic + system audio queues.
final class FloatRing {
    private var buf: [Float] = []
    private let lock = NSLock()
    private let capacity: Int

    init(capacityFrames: Int) {
        self.capacity = capacityFrames
        buf.reserveCapacity(capacityFrames)
    }

    func append(_ samples: UnsafeBufferPointer<Float>) {
        lock.lock(); defer { lock.unlock() }
        buf.append(contentsOf: samples)
        // Drop oldest if we ever exceed capacity (catastrophic — happens
        // when the consumer can't keep up). Better than unbounded growth.
        if buf.count > capacity {
            buf.removeFirst(buf.count - capacity)
        }
    }

    /// Drain up to `n` samples. Returns however many were available; may
    /// be < n (caller decides whether to wait or proceed with what it has).
    func drain(_ n: Int) -> [Float] {
        lock.lock(); defer { lock.unlock() }
        guard !buf.isEmpty else { return [] }
        let take = min(n, buf.count)
        let out = Array(buf.prefix(take))
        buf.removeFirst(take)
        return out
    }

    var count: Int {
        lock.lock(); defer { lock.unlock() }
        return buf.count
    }
}

// MARK: - Resampling

/// Converts arbitrary input format → 16 kHz mono Float32. Reused per source
/// to avoid re-allocating AVAudioConverter on every buffer.
final class Resampler {
    let converter: AVAudioConverter
    let outFormat: AVAudioFormat

    init(inputFormat: AVAudioFormat) throws {
        guard let out = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: OUTPUT_SAMPLE_RATE,
            channels: OUTPUT_CHANNELS,
            interleaved: false
        ) else {
            throw NSError(domain: "uxie-audio-tap", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "couldn't create output format"])
        }
        self.outFormat = out
        guard let conv = AVAudioConverter(from: inputFormat, to: out) else {
            throw NSError(domain: "uxie-audio-tap", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "couldn't create AVAudioConverter from \(inputFormat) to \(out)"])
        }
        // Highest quality is fine — 16 kHz target is cheap.
        conv.sampleRateConverterQuality = .max
        self.converter = conv
    }

    /// Convert `inBuf` (any rate/channels) → mono Float32 @ 16 kHz.
    /// Returns nil if conversion errored.
    func convert(_ inBuf: AVAudioPCMBuffer) -> [Float]? {
        let inFrames = inBuf.frameLength
        // Output capacity scales by ratio of sample rates; pad a little.
        let ratio = outFormat.sampleRate / inBuf.format.sampleRate
        let outCapacity = AVAudioFrameCount(Double(inFrames) * ratio + 64)
        guard let outBuf = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: outCapacity) else {
            return nil
        }
        var error: NSError?
        var supplied = false
        let status = converter.convert(to: outBuf, error: &error) { _, outStatus in
            if supplied {
                outStatus.pointee = .endOfStream
                return nil
            }
            supplied = true
            outStatus.pointee = .haveData
            return inBuf
        }
        if let error = error {
            logErr("converter error: \(error.localizedDescription)")
            return nil
        }
        if status == .error { return nil }
        let frames = Int(outBuf.frameLength)
        guard frames > 0, let chPtr = outBuf.floatChannelData?[0] else { return [] }
        return Array(UnsafeBufferPointer(start: chPtr, count: frames))
    }
}

// MARK: - Mic capture

final class MicCapturer {
    let engine = AVAudioEngine()
    let onSamples: ([Float]) -> Void
    private var resampler: Resampler?

    init(onSamples: @escaping ([Float]) -> Void) {
        self.onSamples = onSamples
    }

    var rawCallbacks = 0
    var rawFramesIn = 0

    func start() throws {
        let input = engine.inputNode
        let hwFormat = input.outputFormat(forBus: 0)
        logErr("mic: hw format \(hwFormat)")
        resampler = try Resampler(inputFormat: hwFormat)
        input.installTap(onBus: 0, bufferSize: 1024, format: hwFormat) { [weak self] buf, _ in
            guard let self = self else { return }
            self.rawCallbacks += 1
            self.rawFramesIn += Int(buf.frameLength)
            if let samples = self.resampler?.convert(buf), !samples.isEmpty {
                self.onSamples(samples)
            }
        }
        engine.prepare()
        try engine.start()
        logErr("mic: engine started")
    }

    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }
}

// MARK: - System audio capture (ScreenCaptureKit)

final class SystemCapturer: NSObject, SCStreamDelegate, SCStreamOutput {
    let onSamples: ([Float]) -> Void
    private var stream: SCStream?
    private var resampler: Resampler?

    init(onSamples: @escaping ([Float]) -> Void) {
        self.onSamples = onSamples
    }

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(
            false, onScreenWindowsOnly: false
        )
        guard let display = content.displays.first else {
            throw NSError(domain: "uxie-audio-tap", code: 3,
                          userInfo: [NSLocalizedDescriptionKey: "no displays available — Screen Recording permission may not be granted"])
        }

        // SCStream requires SOME video output even when we only want audio.
        // 2×2 @ 1fps is the smallest config it accepts; we never read the
        // frames, so cost is microscopic.
        let cfg = SCStreamConfiguration()
        cfg.capturesAudio = true
        cfg.sampleRate = 48_000
        cfg.channelCount = 1
        cfg.excludesCurrentProcessAudio = true  // don't echo Uxie's own output
        cfg.width = 2
        cfg.height = 2
        cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        cfg.showsCursor = false

        let filter = SCContentFilter(display: display, excludingWindows: [])
        let stream = SCStream(filter: filter, configuration: cfg, delegate: self)
        // Audio output goes through us. We do NOT register a video output
        // — SCStream will produce frames internally and drop them.
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: nil)
        try await stream.startCapture()
        self.stream = stream
        logErr("system: stream started")
    }

    func stop() async {
        guard let s = stream else { return }
        do { try await s.stopCapture() }
        catch { logErr("system: stopCapture error: \(error.localizedDescription)") }
        stream = nil
    }

    // SCStreamDelegate
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        logErr("system: stopped with error \(error.localizedDescription)")
    }

    // SCStreamOutput
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio else { return }
        guard let formatDesc = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(formatDesc) else {
            return
        }
        guard let avFormat = AVAudioFormat(streamDescription: asbdPtr) else {
            return
        }

        // CMSampleBuffer → AVAudioPCMBuffer roundtrip.
        let numSamples = CMSampleBufferGetNumSamples(sampleBuffer)
        guard numSamples > 0,
              let pcmBuf = AVAudioPCMBuffer(pcmFormat: avFormat,
                                            frameCapacity: AVAudioFrameCount(numSamples)) else {
            return
        }
        pcmBuf.frameLength = AVAudioFrameCount(numSamples)

        var blockBuffer: CMBlockBuffer?
        var audioBufferList = AudioBufferList(
            mNumberBuffers: 1,
            mBuffers: AudioBuffer(mNumberChannels: 0, mDataByteSize: 0, mData: nil)
        )
        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: nil,
            bufferListOut: &audioBufferList,
            bufferListSize: MemoryLayout<AudioBufferList>.size,
            blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil,
            flags: 0,
            blockBufferOut: &blockBuffer
        )
        if status != noErr { return }

        // We requested mono Float32 at 48k from SCStream — copy that into
        // our AVAudioPCMBuffer so the Resampler can normalize to 16 kHz.
        let abl = UnsafeMutableAudioBufferListPointer(&audioBufferList)
        if abl.count == 0 { return }
        let srcBytes = abl[0].mData
        let srcSize = Int(abl[0].mDataByteSize)
        if srcSize > 0, let srcBytes = srcBytes,
           let dstFloats = pcmBuf.floatChannelData?[0] {
            memcpy(dstFloats, srcBytes, srcSize)
        }

        if resampler == nil {
            // Lazy-init so we use the actual SCStream-delivered format.
            do { resampler = try Resampler(inputFormat: avFormat) }
            catch {
                logErr("system: resampler init failed: \(error.localizedDescription)")
                return
            }
        }
        if let samples = resampler?.convert(pcmBuf), !samples.isEmpty {
            onSamples(samples)
        }
    }
}

// MARK: - Main

/// Drives input callbacks (mic + system) directly into the mixer. No timer
/// loop — emission rate equals input callback rate. The mic tap callback
/// fires every ~21 ms (1024 frames @ 48 kHz), which after resampling is
/// ~341 samples @ 16 kHz — comfortably above one FRAME_SAMPLES per call.
final class Tap {
    // 5 seconds of headroom — far more than the mixer needs but small
    // enough to discard cleanly if the consumer stalls.
    let micRing = FloatRing(capacityFrames: Int(OUTPUT_SAMPLE_RATE * 5))
    let sysRing = FloatRing(capacityFrames: Int(OUTPUT_SAMPLE_RATE * 5))
    let stdoutLock = NSLock()
    var mic: MicCapturer?
    var sys: SystemCapturer?
    var stopped = false

    // Diagnostic counters — periodically logged so we can tell from the
    // engine log whether mic/system callbacks are firing in production.
    var micCallbacks = 0
    var sysCallbacks = 0
    var framesEmitted = 0
    var bytesEmitted = 0
    // Retained references so dispatch sources / timers don't dealloc when
    // the function they were created in returns.
    var heartbeatSource: DispatchSourceTimer?
    var sigtermSource: DispatchSourceSignal?

    func setUp() async {
        // Mic — synchronous startup.
        mic = MicCapturer { [weak self] samples in
            guard let self = self else { return }
            self.micCallbacks += 1
            samples.withUnsafeBufferPointer { self.micRing.append($0) }
            self.drainAndEmit()
        }
        do { try mic?.start() }
        catch {
            logErr("mic start failed: \(error.localizedDescription)")
        }

        // System audio — async startup.
        sys = SystemCapturer { [weak self] samples in
            guard let self = self else { return }
            self.sysCallbacks += 1
            samples.withUnsafeBufferPointer { self.sysRing.append($0) }
            self.drainAndEmit()
        }
        do { try await sys?.start() }
        catch {
            logErr("system start failed: \(error.localizedDescription)")
        }

        // Heartbeat: log counters every 5 seconds so we can see from
        // production logs whether the pipeline is moving data. Retain
        // the timer on self so it doesn't dealloc when setUp() returns.
        let heartbeat = DispatchSource.makeTimerSource(queue: .global())
        heartbeat.schedule(deadline: .now() + 5, repeating: 5)
        heartbeat.setEventHandler { [weak self] in
            guard let self = self else { return }
            let raw = self.mic?.rawCallbacks ?? 0
            let rawF = self.mic?.rawFramesIn ?? 0
            logErr("hb: mic_raw_cb=\(raw) mic_raw_frames=\(rawF) mic_post_resample=\(self.micCallbacks) sys_cb=\(self.sysCallbacks) emitted=\(self.framesEmitted)f/\(self.bytesEmitted)b")
        }
        heartbeat.resume()
        heartbeatSource = heartbeat

        // Watch stdin on a background queue — parent closes the pipe
        // (SIGTERM from Python) and we exit cleanly.
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let stdin = FileHandle.standardInput
            while true {
                let chunk = stdin.availableData
                if chunk.isEmpty {
                    logErr("stdin EOF — exiting")
                    self?.shutdown()
                    return
                }
            }
        }

        // SIGTERM handler — Python sends this on stop_capture(). Don't
        // block on the source; install + activate so the dispatch queue
        // picks up events asynchronously. Retain on self so it lives
        // beyond setUp().
        let sigterm = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
        sigterm.setEventHandler { [weak self] in
            logErr("SIGTERM — exiting")
            self?.shutdown()
        }
        sigterm.resume()
        signal(SIGTERM, SIG_IGN)
        sigtermSource = sigterm
    }

    /// Called from input-callback queues. Emits as many FRAME_SAMPLES-sized
    /// chunks as both rings collectively have data for. Pads the lagging
    /// source with silence so a denied Screen Recording permission doesn't
    /// stall the whole pipeline.
    func drainAndEmit() {
        // Loop in case multiple frames are ready (input bursts).
        while !stopped {
            let micCount = micRing.count
            let sysCount = sysRing.count
            // Need at least ONE source with a full frame to make progress.
            if micCount < FRAME_SAMPLES && sysCount < FRAME_SAMPLES { return }

            let micSamples = micRing.drain(FRAME_SAMPLES)
            let sysSamples = sysRing.drain(FRAME_SAMPLES)
            if micSamples.isEmpty && sysSamples.isEmpty { return }

            var mixed = [Int16](repeating: 0, count: FRAME_SAMPLES)
            for i in 0..<FRAME_SAMPLES {
                let m = i < micSamples.count ? micSamples[i] : 0
                let s = i < sysSamples.count ? sysSamples[i] : 0
                // Sum then clip — with both sources at unit gain the worst
                // case is 2.0; clamp before Int16 to avoid wrap.
                var sum = m + s
                if sum >  1.0 { sum =  1.0 }
                if sum < -1.0 { sum = -1.0 }
                mixed[i] = Int16(sum * 32767.0)
            }

            let data = mixed.withUnsafeBufferPointer { Data(buffer: $0) }
            stdoutLock.lock()
            FileHandle.standardOutput.write(data)
            framesEmitted += 1
            bytesEmitted += data.count
            stdoutLock.unlock()
        }
    }

    func shutdown() {
        if stopped { return }
        stopped = true
        mic?.stop()
        // sys.stop is async; fire-and-forget — we're exiting anyway.
        if let s = sys { Task.detached { await s.stop() } }
        try? FileHandle.standardOutput.synchronize()
        exit(0)
    }
}

// Start everything, then park the main thread on the dispatch main queue.
// AVAudioEngine + ScreenCaptureKit deliver buffers via internal queues, but
// rely on the main thread being available to handle their housekeeping.
//
// `dispatchMain()` is the canonical CLI-tool answer. Crucial: we spawn
// setUp() in a *detached* Task so it doesn't make the top-level script a
// "main task" that the Swift runtime treats as the program's lifetime —
// if it were the main task, dispatchMain() would be considered the task's
// continuation and the runtime would exit when it "returned" (which it
// never does, but the runtime can't tell). Detached Task + dispatchMain
// keeps the process parked forever.
let tap = Tap()
Task.detached { await tap.setUp() }
dispatchMain()
