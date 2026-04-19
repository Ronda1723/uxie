import Foundation
import Combine
import AppKit

@MainActor
final class SettingsViewModel: ObservableObject {

    @Published var openAIKey = ""
    @Published var smallestKey = ""
    @Published var userName = ""
    @Published var connectedProviders: [String] = []
    @Published var isLoading = false
    @Published var saveStatus: String?

    // Styles: category → tone (e.g. "messaging" → "casual")
    @Published var stylePreferences: [String: String] = [:]

    // Advanced toggles
    @Published var fillerRemoval = false
    @Published var whisperMode = false
    @Published var developerMode = false

    private let api = APIClient.shared
    private var cancellables = Set<AnyCancellable>()

    init() {
        // Auto-reload connected providers when an OAuth flow completes
        EventStream.shared.$lastOAuthProvider
            .compactMap { $0 }
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                Task { await self?.load() }
            }
            .store(in: &cancellables)
    }

    // MARK: - Load

    func load() async {
        isLoading = true
        defer { isLoading = false }

        if let keys: ApiKeysResponse = try? await api.invoke("has_api_keys") {
            openAIKey = keys.openai ?? ""
            smallestKey = keys.smallest ?? ""
        }
        if let name: String = try? await api.invoke("get_user_name") {
            userName = name
        }
        if let providers: [String] = try? await api.invoke("get_connected_providers") {
            connectedProviders = providers
        }
        await loadStyles()
        await loadAdvancedSettings()
    }

    // MARK: - Save API Keys / Profile

    func saveOpenAIKey() async -> Bool {
        do {
            try await api.invokeVoid("save_api_key", body: ["service": "openai", "key": openAIKey])
            return true
        } catch {
            return false
        }
    }

    func saveSmallestKey() async -> Bool {
        do {
            try await api.invokeVoid("save_api_key", body: ["service": "smallest", "key": smallestKey])
            return true
        } catch {
            return false
        }
    }

    func saveUserName() async {
        try? await api.invokeVoid("save_user_name", body: ["name": userName])
        flashStatus("Saved")
    }

    // MARK: - OAuth

    func connectProvider(_ provider: String) async {
        guard let urlStr: String = try? await api.invoke("start_oauth", body: ["provider": provider]),
              let url = URL(string: urlStr)
        else { return }
        NSWorkspace.shared.open(url)
    }

    func disconnectProvider(_ provider: String) async {
        try? await api.invokeVoid("disconnect_provider", body: ["provider": provider])
        await load()
    }

    // MARK: - Styles

    func loadStyles() async {
        if let prefs: [String: String] = try? await api.invoke("get_style_preferences") {
            stylePreferences = prefs
        }
    }

    func saveStyle(category: String, tone: String) async {
        stylePreferences[category] = tone
        try? await api.invokeVoid("save_style_preference", body: ["category": category, "tone": tone])
    }

    // MARK: - Advanced Settings

    func loadAdvancedSettings() async {
        if let settings: [String: Bool] = try? await api.invoke("get_advanced_settings") {
            fillerRemoval = settings["filler_removal"] ?? false
            whisperMode   = settings["whisper_mode"]   ?? false
            developerMode = settings["developer_mode"] ?? false
        }
    }

    func saveAdvancedSetting(key: String, value: Bool) async {
        try? await api.invokeVoid("save_advanced_setting", body: ["key": key, "value": value])
    }

    // MARK: - Helpers

    private func flashStatus(_ message: String) {
        saveStatus = message
        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            saveStatus = nil
        }
    }

    private struct ApiKeysResponse: Decodable {
        let openai: String?
        let smallest: String?
    }
}
