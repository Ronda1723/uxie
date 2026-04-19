import AVFoundation
import Foundation

final class AudioCaptureService {

    static let shared = AudioCaptureService()

    private let engine = AVAudioEngine()
    private var isRunning = false

    private init() {
        // When the user changes audio device (plug/unplug headphones, switch input),
        // AVAudioEngine stops automatically. Restart capture so audio keeps flowing.
        NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange,
            object: engine,
            queue: .main
        ) { [weak self] _ in
            guard let self, self.isRunning else { return }
            self.isRunning = false
            self.engine.inputNode.removeTap(onBus: 0)
            try? self.startCapture()
        }
    }

    private let format = AVAudioFormat(
        commonFormat: .pcmFormatInt16,
        sampleRate: 16_000,
        channels: 1,
        interleaved: true
    )!

    // MARK: - Permission

    func requestPermission() async -> Bool {
        await AVCaptureDevice.requestAccess(for: .audio)
    }

    // MARK: - Capture lifecycle

    func startCapture() throws {
        guard !isRunning else { return }

        let input = engine.inputNode
        let native = input.inputFormat(forBus: 0)
        let bufferSize = AVAudioFrameCount(native.sampleRate * 0.1) // ~100ms at native rate

        input.installTap(onBus: 0, bufferSize: bufferSize, format: native) { [weak self] buffer, _ in
            self?.handle(buffer: buffer, nativeFormat: native)
        }

        engine.prepare()
        try engine.start()
        isRunning = true
    }

    func stopCapture() {
        guard isRunning else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        isRunning = false
    }

    // MARK: - Buffer processing

    private func handle(buffer: AVAudioPCMBuffer, nativeFormat: AVAudioFormat) {
        guard let converted = convert(buffer, from: nativeFormat, to: format) else { return }
        guard let data = pcmData(from: converted) else { return }
        let base64 = data.base64EncodedString()
        Task { @MainActor in
            try? await APIClient.shared.invokeVoid("send_audio_chunk", body: ["chunk": base64])
        }
    }

    // MARK: - Helpers

    private func convert(
        _ buffer: AVAudioPCMBuffer,
        from src: AVAudioFormat,
        to dst: AVAudioFormat
    ) -> AVAudioPCMBuffer? {
        guard let converter = AVAudioConverter(from: src, to: dst) else { return nil }
        let ratio = dst.sampleRate / src.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio)
        guard let out = AVAudioPCMBuffer(pcmFormat: dst, frameCapacity: capacity) else { return nil }
        var error: NSError?
        var consumed = false
        converter.convert(to: out, error: &error) { _, outStatus in
            if consumed {
                outStatus.pointee = .noDataNow
                return nil
            }
            outStatus.pointee = .haveData
            consumed = true
            return buffer
        }
        return error == nil ? out : nil
    }

    private func pcmData(from buffer: AVAudioPCMBuffer) -> Data? {
        guard let channelData = buffer.int16ChannelData else { return nil }
        let byteCount = Int(buffer.frameLength) * MemoryLayout<Int16>.size
        return Data(bytes: channelData[0], count: byteCount)
    }
}
