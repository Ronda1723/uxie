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
    ///
    /// IMPORTANT: we signal `.noDataNow` (NOT `.endOfStream`) after handing
    /// the single buffer to the converter. AVAudioConverter treats
    /// `.endOfStream` as "this stream is finished forever" — once seen, it
    /// refuses to accept further input on subsequent `convert()` calls.
    /// `.noDataNow` keeps the converter in streaming mode.
    func convert(_ inBuf: AVAudioPCMBuffer) -> [Float]? {
        let inFrames = inBuf.frameLength
        let ratio = outFormat.sampleRate / inBuf.format.sampleRate
        let outCapacity = AVAudioFrameCount(Double(inFrames) * ratio + 64)
        guard let outBuf = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: outCapacity) else {
            return nil
        }
        var error: NSError?
        var supplied = false
        let status = converter.convert(to: outBuf, error: &error) { _, outStatus in
            if supplied {
                outStatus.pointee = .noDataNow
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
//
// AVCaptureSession path. We tried AVAudioEngine first; it only delivered one
// buffer per session when running outside an NSApplication context. AVCapture
// is the canonical idiom for long-form streaming audio capture in macOS CLI
// tools and helper binaries — works headlessly as long as TCC mic permission
// is granted to either this binary or its parent process.

final class MicCapturer: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate {
    let onSamples: ([Float]) -> Void
    private let session = AVCaptureSession()
    private var resampler: Resampler?
    private let outputQueue = DispatchQueue(label: "ai.uxie.audio-tap.mic", qos: .userInitiated)

    var rawCallbacks = 0
    var rawFramesIn = 0

    init(onSamples: @escaping ([Float]) -> Void) {
        self.onSamples = onSamples
    }

    func start() throws {
        guard let device = AVCaptureDevice.default(for: .audio) else {
            throw NSError(domain: "uxie-audio-tap", code: 10,
                          userInfo: [NSLocalizedDescriptionKey: "no default audio capture device"])
        }
        let input = try AVCaptureDeviceInput(device: device)
        if !session.canAddInput(input) {
            throw NSError(domain: "uxie-audio-tap", code: 11,
                          userInfo: [NSLocalizedDescriptionKey: "cannot add mic input to session"])
        }
        session.addInput(input)

        let output = AVCaptureAudioDataOutput()
        // 16 kHz mono Float32 at the source — saves a resampling step in
        // most cases. AVCaptureAudioDataOutput honours these settings on
        // macOS 13+; older versions may renegotiate.
        output.audioSettings = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 48_000.0,  // hardware-native; we resample below
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 32,
            AVLinearPCMIsFloatKey: true,
            AVLinearPCMIsNonInterleaved: false,
        ]
        if !session.canAddOutput(output) {
            throw NSError(domain: "uxie-audio-tap", code: 12,
                          userInfo: [NSLocalizedDescriptionKey: "cannot add audio output to session"])
        }
        session.addOutput(output)
        output.setSampleBufferDelegate(self, queue: outputQueue)

        session.startRunning()
        logErr("mic: AVCaptureSession started (device=\(device.localizedName))")
    }

    func stop() {
        session.stopRunning()
        for input in session.inputs { session.removeInput(input) }
        for output in session.outputs { session.removeOutput(output) }
    }

    // AVCaptureAudioDataOutputSampleBufferDelegate
    func captureOutput(_ output: AVCaptureOutput,
                       didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        rawCallbacks += 1
        rawFramesIn += Int(CMSampleBufferGetNumSamples(sampleBuffer))

        guard let formatDesc = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(formatDesc),
              let inFormat = AVAudioFormat(streamDescription: asbdPtr) else {
            return
        }

        let numFrames = CMSampleBufferGetNumSamples(sampleBuffer)
        guard numFrames > 0,
              let pcmBuf = AVAudioPCMBuffer(pcmFormat: inFormat,
                                            frameCapacity: AVAudioFrameCount(numFrames)) else {
            return
        }
        pcmBuf.frameLength = AVAudioFrameCount(numFrames)

        // Copy CMSampleBuffer data into the AVAudioPCMBuffer so the converter
        // (which only speaks AVAudioPCMBuffer) can process it.
        var ablPtr: AudioBufferList = AudioBufferList(
            mNumberBuffers: 1,
            mBuffers: AudioBuffer(mNumberChannels: 0, mDataByteSize: 0, mData: nil)
        )
        var blockBuffer: CMBlockBuffer?
        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: nil,
            bufferListOut: &ablPtr,
            bufferListSize: MemoryLayout<AudioBufferList>.size,
            blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil,
            flags: 0,
            blockBufferOut: &blockBuffer
        )
        guard status == noErr else { return }

        let abl = UnsafeMutableAudioBufferListPointer(&ablPtr)
        if abl.count == 0 { return }
        let srcBytes = abl[0].mData
        let srcSize = Int(abl[0].mDataByteSize)
        if srcSize > 0, let srcBytes = srcBytes,
           let dstFloats = pcmBuf.floatChannelData?[0] {
            memcpy(dstFloats, srcBytes, srcSize)
        }

        if resampler == nil {
            do { resampler = try Resampler(inputFormat: inFormat) }
            catch {
                logErr("mic: resampler init failed: \(error.localizedDescription)")
                return
            }
        }
        if let samples = resampler?.convert(pcmBuf), !samples.isEmpty {
            onSamples(samples)
        }
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
        // Mic is the master clock. Every mic-resampler output triggers
        // an emit: we take that many samples from the system-audio ring
        // and mix them in. The output rate equals the mic's real-time
        // rate (16 kHz), so Deepgram receives audio that matches wall
        // clock — no "fast-forward" effect.
        mic = MicCapturer { [weak self] samples in
            guard let self = self else { return }
            self.micCallbacks += 1
            self.mixAndEmit(micSamples: samples)
        }
        do { try mic?.start() }
        catch {
            logErr("mic start failed: \(error.localizedDescription)")
        }

        // System audio — feeds the sys ring; mic callback drains it.
        sys = SystemCapturer { [weak self] samples in
            guard let self = self else { return }
            self.sysCallbacks += 1
            samples.withUnsafeBufferPointer { self.sysRing.append($0) }
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

    /// Driven by every mic-resampler output. Mic samples are passed in
    /// directly; we drain the same count from the system-audio ring (or
    /// pad with zero if the system stream isn't flowing yet / was denied).
    /// Mix sample-by-sample, clip, emit Int16 LE.
    func mixAndEmit(micSamples: [Float]) {
        if stopped || micSamples.isEmpty { return }
        let n = micSamples.count
        let sysSamples = sysRing.drain(n)

        var mixed = [Int16](repeating: 0, count: n)
        for i in 0..<n {
            let m = micSamples[i]
            let s = i < sysSamples.count ? sysSamples[i] : 0
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

// MARK: - Watcher mode
//
// Polls `SCShareableContent` on a long interval and emits JSON events to
// stdout when a known meeting-app window appears or disappears. The
// engine's meeting_watcher.py spawns this in a separate process and
// translates events into native macOS notifications + DB rows.
//
// Detected meeting-app patterns:
//   Slack huddle:    bundleID com.tinyspeck.slackmacgap, title contains "Huddle"
//   Zoom meeting:    bundleID us.zoom.xos, title starts with "Zoom Meeting"
//   Teams meeting:   bundleID com.microsoft.teams2 (or com.microsoft.teams), title contains "Meeting"
//   Meet (Chrome):   bundleID com.google.Chrome, title contains "Meet"
//   Webex:           bundleID com.cisco.webexmeetingsapp
//
// We DO NOT actually capture any audio in watch mode — this is a pure
// window-presence detector. SCShareableContent does require the parent
// app to have Screen Recording permission; the .app sub-bundle's
// NSScreenCaptureDescription handles the TCC consent prompt.

final class Watcher {
    private var knownActiveIds: Set<String> = []
    private var stopFlag = false
    private var sigtermSource: DispatchSourceSignal?

    func emit(_ kind: String, _ payload: [String: Any]) {
        var event = payload
        event["event"] = kind
        guard let data = try? JSONSerialization.data(withJSONObject: event, options: []),
              let line = String(data: data, encoding: .utf8) else { return }
        FileHandle.standardOutput.write((line + "\n").data(using: .utf8)!)
    }

    /// Emit a single event with a leading newline so receivers can dedupe
    /// partial lines across reads. Receivers should split on newline.

    struct MeetingMatch {
        let appBundleId: String
        let appName: String
        let title: String
        let detectorKey: String       // stable per-meeting-instance id

        var asDict: [String: Any] {
            return [
                "app_bundle_id": appBundleId,
                "app_name": appName,
                "title": title,
                "detector_key": detectorKey,
            ]
        }
    }

    // All bundle IDs we know about — used both for classification AND
    // for diagnostic logging so the user's log shows the exact app +
    // title strings their Slack/Zoom/Teams version is exposing.
    static let MEETING_APP_BUNDLE_IDS: Set<String> = [
        "com.tinyspeck.slackmacgap", "com.tinyspeck.slack",
        "us.zoom.xos", "us.zoom.ZoomClips",
        "com.microsoft.teams2", "com.microsoft.teams",
        "com.cisco.webexmeetingsapp", "com.webex.meetingmanager",
        "com.google.Chrome", "com.google.Chrome.canary",
        "com.brave.Browser", "com.microsoft.edgemac",
        "com.apple.Safari",
        "com.hnc.Discord",
        "com.electron.discord",
    ]

    /// Decide whether a given SCWindow looks like an active meeting.
    /// Returns a MeetingMatch if yes, nil otherwise.
    ///
    /// Rules are intentionally permissive — false positives produce a
    /// notification that the user can dismiss, false negatives mean the
    /// feature didn't work at all. We bias toward firing.
    func classify(_ w: SCWindow) -> MeetingMatch? {
        guard let app = w.owningApplication else { return nil }
        let bundleId = app.bundleIdentifier
        let appName = app.applicationName
        let title = (w.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let lowered = title.lowercased()
        let frame = w.frame
        let w_px = frame.width
        let h_px = frame.height

        // Per-instance stability key. Uses windowID so reopening a huddle
        // generates a new key → new detection.
        let key = "\(bundleId)#\(w.windowID)"

        switch bundleId {
        case "com.tinyspeck.slackmacgap", "com.tinyspeck.slack":
            // Slack's main window is ~888×767 — well within any "small"
            // heuristic, so we can't lean on frame size. Title is the
            // only reliable signal. Slack huddle window titles always
            // contain one of these tokens when a huddle is active.
            //
            // Diagnostic log keeps showing every Slack window (matched
            // or not) so we can extend this list if a Slack version
            // ships a new title format.
            let huddleTokens = ["huddle", "slack call", "call with", "audio call", "video call"]
            if huddleTokens.contains(where: { lowered.contains($0) }) {
                let pretty = title.isEmpty ? "Slack huddle" : "Slack: \(title)"
                return MeetingMatch(appBundleId: bundleId, appName: appName,
                                    title: pretty, detectorKey: key)
            }
        case "us.zoom.xos", "us.zoom.ZoomClips":
            if lowered.hasPrefix("zoom meeting")
                || lowered.contains("zoom webinar")
                || lowered.contains("zoom meeting") {
                return MeetingMatch(appBundleId: bundleId, appName: appName,
                                    title: title, detectorKey: key)
            }
        case "com.microsoft.teams2", "com.microsoft.teams":
            if lowered.contains("meeting") || lowered.contains("call with") {
                return MeetingMatch(appBundleId: bundleId, appName: appName,
                                    title: "Teams: \(title)", detectorKey: key)
            }
        case "com.cisco.webexmeetingsapp", "com.webex.meetingmanager":
            if !title.isEmpty {
                return MeetingMatch(appBundleId: bundleId, appName: appName,
                                    title: "Webex: \(title)", detectorKey: key)
            }
        case "com.google.Chrome", "com.google.Chrome.canary",
             "com.brave.Browser", "com.microsoft.edgemac",
             "com.apple.Safari":
            if lowered.contains("meet.google.com")
                || lowered.contains("google meet")
                || lowered.contains("- meet")
                || lowered.contains("- google meet") {
                return MeetingMatch(appBundleId: bundleId, appName: appName,
                                    title: "Meet: \(title)", detectorKey: key)
            }
        case "com.hnc.Discord", "com.electron.discord":
            // Discord voice / video calls — the call window's title
            // typically contains "Voice Connected" or the channel name.
            if lowered.contains("voice")
                || lowered.contains("call")
                || lowered.contains("video call") {
                return MeetingMatch(appBundleId: bundleId, appName: appName,
                                    title: "Discord: \(title)", detectorKey: key)
            }
        default:
            return nil
        }
        return nil
    }

    func pollOnce() async {
        let content: SCShareableContent
        do {
            content = try await SCShareableContent.excludingDesktopWindows(
                false, onScreenWindowsOnly: true
            )
        } catch {
            logErr("watch: SCShareableContent fetch failed: \(error.localizedDescription)")
            return
        }

        // Diagnostic: log every visible window from a known meeting-app
        // bundle id (even if we don't classify it as a meeting). This is
        // how we discover Slack's actual huddle title on a user's
        // machine when our heuristic missed it — they share the log line,
        // we update the rules.
        var candidateCount = 0
        for w in content.windows {
            guard let app = w.owningApplication,
                  Watcher.MEETING_APP_BUNDLE_IDS.contains(app.bundleIdentifier) else { continue }
            candidateCount += 1
            let titleSnippet = String((w.title ?? "(no title)").prefix(80))
            logErr("watch: candidate app=\(app.bundleIdentifier) w=\(Int(w.frame.width))x\(Int(w.frame.height)) title=\(titleSnippet)")
        }
        if candidateCount == 0 {
            logErr("watch: poll — \(content.windows.count) windows, 0 from known meeting apps")
        }

        var current: [String: MeetingMatch] = [:]
        for w in content.windows {
            if let m = classify(w) {
                current[m.detectorKey] = m
            }
        }
        let currentIds = Set(current.keys)

        // New meetings: in current but not in known.
        for newKey in currentIds.subtracting(knownActiveIds) {
            guard let m = current[newKey] else { continue }
            emit("meeting-window-appeared", m.asDict)
        }
        // Ended meetings: in known but not in current.
        for goneKey in knownActiveIds.subtracting(currentIds) {
            emit("meeting-window-disappeared", ["detector_key": goneKey])
        }
        knownActiveIds = currentIds
    }

    func run() async {
        logErr("watch: starting (poll interval 5s)")
        emit("watcher-ready", [:])

        // SIGTERM handler — engine sends this when toggling auto-detect off.
        let sigterm = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
        sigterm.setEventHandler { [weak self] in
            logErr("watch: SIGTERM — exiting")
            self?.stopFlag = true
            try? FileHandle.standardOutput.synchronize()
            exit(0)
        }
        sigterm.resume()
        signal(SIGTERM, SIG_IGN)
        sigtermSource = sigterm

        // Stdin EOF → parent died → exit. Backgrounded for the same reason
        // as the recording mode.
        DispatchQueue.global(qos: .utility).async { [weak self] in
            while true {
                let chunk = FileHandle.standardInput.availableData
                if chunk.isEmpty {
                    logErr("watch: stdin EOF — exiting")
                    self?.stopFlag = true
                    try? FileHandle.standardOutput.synchronize()
                    exit(0)
                }
            }
        }

        while !stopFlag {
            await pollOnce()
            try? await Task.sleep(nanoseconds: 5_000_000_000)
        }
    }
}

// MARK: - Entry point
//
// Two modes:
//   default (no flag) → audio capture for active recording
//   --watch           → meeting-window presence detector
//
// `dispatchMain()` is the canonical CLI-tool answer to "park the main
// thread forever." Crucial: we spawn setUp() in a *detached* Task so it
// doesn't make the top-level script a "main task" that the Swift runtime
// treats as the program's lifetime — if it were the main task,
// dispatchMain() would be considered the task's continuation and the
// runtime would exit when it "returned" (which it never does, but the
// runtime can't tell). Detached Task + dispatchMain keeps the process
// parked forever.

if CommandLine.arguments.contains("--watch") {
    let w = Watcher()
    Task.detached { await w.run() }
    dispatchMain()
} else {
    let tap = Tap()
    Task.detached { await tap.setUp() }
    dispatchMain()
}
