import SwiftUI
import ServiceManagement

struct SettingsView: View {
    @StateObject private var vm = SettingsViewModel()
    @State private var selectedTab = "keys"

    var body: some View {
        TabView(selection: $selectedTab) {
            APIKeysTab(vm: vm)
                .tabItem { Label("API Keys", systemImage: "key.fill") }
                .tag("keys")

            ConnectorsTab(vm: vm)
                .tabItem { Label("Connectors", systemImage: "link") }
                .tag("connectors")

            ProfileTab(vm: vm)
                .tabItem { Label("Profile", systemImage: "person.fill") }
                .tag("profile")

            StylesTab(vm: vm)
                .tabItem { Label("Styles", systemImage: "paintbrush.fill") }
                .tag("styles")

            AdvancedTab(vm: vm)
                .tabItem { Label("Advanced", systemImage: "slider.horizontal.3") }
                .tag("advanced")

            if #available(macOS 13, *) {
                GeneralTab()
                    .tabItem { Label("General", systemImage: "gearshape") }
                    .tag("general")
            }
        }
        .frame(width: 560, height: 440)
        .task { await vm.load() }
    }
}

// MARK: - API Keys

private struct APIKeysTab: View {
    @ObservedObject var vm: SettingsViewModel
    @State private var openAISaveState: SaveState = .idle
    @State private var smallestSaveState: SaveState = .idle

    enum SaveState { case idle, saving, saved, error }

    var body: some View {
        Form {
            Section {
                HStack {
                    SecureField("OpenAI API Key", text: $vm.openAIKey)
                        .textFieldStyle(.roundedBorder)
                        .onChange(of: vm.openAIKey) { _ in openAISaveState = .idle }
                    saveButton(state: openAISaveState, disabled: vm.openAIKey.isEmpty) {
                        openAISaveState = .saving
                        let ok = await vm.saveOpenAIKey()
                        openAISaveState = ok ? .saved : .error
                    }
                }
                saveHint(state: openAISaveState, hint: "Used for the GPT-4o agent loop.")
            } header: { Text("OpenAI") }

            Section {
                HStack {
                    SecureField("Smallest AI API Key", text: $vm.smallestKey)
                        .textFieldStyle(.roundedBorder)
                        .onChange(of: vm.smallestKey) { _ in smallestSaveState = .idle }
                    saveButton(state: smallestSaveState, disabled: vm.smallestKey.isEmpty) {
                        smallestSaveState = .saving
                        let ok = await vm.saveSmallestKey()
                        smallestSaveState = ok ? .saved : .error
                    }
                }
                saveHint(state: smallestSaveState, hint: "Used for real-time speech-to-text.")
            } header: { Text("Smallest AI") }
        }
        .formStyle(.grouped)
        .padding()
    }

    @ViewBuilder
    private func saveButton(state: SaveState, disabled: Bool, action: @escaping () async -> Void) -> some View {
        Button {
            Task { await action() }
        } label: {
            switch state {
            case .saving: ProgressView().controlSize(.small)
            case .saved:  Label("Saved", systemImage: "checkmark").foregroundStyle(.green)
            case .error:  Label("Error", systemImage: "xmark.circle").foregroundStyle(.red)
            case .idle:   Text("Save")
            }
        }
        .disabled(disabled || state == .saving)
        .frame(minWidth: 64)
    }

    @ViewBuilder
    private func saveHint(state: SaveState, hint: String) -> some View {
        switch state {
        case .error:
            Text("Could not save — is the MiniFlow engine running?")
                .font(.caption).foregroundStyle(.red)
        default:
            Text(hint).font(.caption).foregroundStyle(.secondary)
        }
    }
}

// MARK: - Connectors

private struct ConnectorsTab: View {
    @ObservedObject var vm: SettingsViewModel

    private let connectors: [(id: String, name: String, icon: String)] = [
        ("google",  "Gmail / Calendar / Drive", "envelope.fill"),
        ("slack",   "Slack",                    "message.fill"),
        ("github",  "GitHub",                   "chevron.left.forwardslash.chevron.right"),
        ("spotify", "Spotify",                  "music.note"),
        ("notion",  "Notion",                   "doc.fill"),
        ("linear",  "Linear",                   "square.and.pencil"),
        ("jira",    "Jira",                     "list.bullet.clipboard"),
        ("discord", "Discord",                  "bubble.left.fill"),
    ]

    var body: some View {
        List {
            ForEach(connectors, id: \.id) { connector in
                HStack(spacing: 12) {
                    Image(systemName: connector.icon)
                        .font(.system(size: 14))
                        .frame(width: 22)
                        .foregroundStyle(.secondary)
                    Text(connector.name)
                        .font(.system(size: 13))
                    Spacer()
                    if vm.connectedProviders.contains(connector.id) {
                        Label("Connected", systemImage: "checkmark.circle.fill")
                            .font(.system(size: 11))
                            .foregroundStyle(.green)
                            .labelStyle(.titleAndIcon)
                        Button("Disconnect") {
                            Task { await vm.disconnectProvider(connector.id) }
                        }
                        .buttonStyle(.borderless)
                        .foregroundStyle(.red)
                        .font(.system(size: 12))
                    } else {
                        Button("Connect") {
                            Task { await vm.connectProvider(connector.id) }
                        }
                        .buttonStyle(.borderless)
                        .foregroundColor(.accentColor)
                        .font(.system(size: 12, weight: .medium))
                    }
                }
                .padding(.vertical, 3)
            }
        }
    }
}

// MARK: - Profile

private struct ProfileTab: View {
    @ObservedObject var vm: SettingsViewModel

    var body: some View {
        Form {
            Section {
                HStack {
                    TextField("Your name", text: $vm.userName)
                        .textFieldStyle(.roundedBorder)
                    Button("Save") {
                        Task { await vm.saveUserName() }
                    }
                    .disabled(vm.userName.isEmpty)
                }
                Text("Used to personalise emails and messages.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } header: { Text("Display Name") }

            if let status = vm.saveStatus {
                Text(status).foregroundStyle(.green).font(.caption)
            }
        }
        .formStyle(.grouped)
        .padding()
    }
}

// MARK: - Styles

private struct StylesTab: View {
    @ObservedObject var vm: SettingsViewModel

    private let categories: [(id: String, label: String)] = [
        ("messaging", "Messaging (Slack, Discord)"),
        ("email",     "Email (Gmail)"),
        ("code",      "Code editors"),
        ("other",     "Everything else"),
    ]

    private let tones = ["casual", "professional", "formal", "concise", "detailed"]

    var body: some View {
        Form {
            Section {
                ForEach(categories, id: \.id) { cat in
                    HStack {
                        Text(cat.label)
                            .font(.system(size: 13))
                        Spacer()
                        Picker("", selection: Binding(
                            get: { vm.stylePreferences[cat.id] ?? "casual" },
                            set: { tone in Task { await vm.saveStyle(category: cat.id, tone: tone) } }
                        )) {
                            ForEach(tones, id: \.self) { tone in
                                Text(tone.capitalized).tag(tone)
                            }
                        }
                        .pickerStyle(.menu)
                        .frame(width: 130)
                    }
                }
            } header: {
                Text("Tone per context")
            } footer: {
                Text("MiniFlow adjusts the writing style based on where you're dictating.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding()
    }
}

// MARK: - Advanced

private struct AdvancedTab: View {
    @ObservedObject var vm: SettingsViewModel

    var body: some View {
        Form {
            Section {
                Toggle("Filler Word Removal", isOn: Binding(
                    get: { vm.fillerRemoval },
                    set: { v in vm.fillerRemoval = v; Task { await vm.saveAdvancedSetting(key: "filler_removal", value: v) } }
                ))
                Text("Removes 'um', 'uh', 'like' etc. from your dictation.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Toggle("Whisper Mode", isOn: Binding(
                    get: { vm.whisperMode },
                    set: { v in vm.whisperMode = v; Task { await vm.saveAdvancedSetting(key: "whisper_mode", value: v) } }
                ))
                Text("Amplifies mic input 3× for quiet environments.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Toggle("Developer Mode", isOn: Binding(
                    get: { vm.developerMode },
                    set: { v in vm.developerMode = v; Task { await vm.saveAdvancedSetting(key: "developer_mode", value: v) } }
                ))
                Text("Formats output as camelCase when dictating in code editors.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } header: { Text("Behaviour") }
        }
        .formStyle(.grouped)
        .padding()
    }
}

// MARK: - General

@available(macOS 13, *)
private struct GeneralTab: View {

    var body: some View {
        Form {
            Section {
                Toggle(
                    "Launch at Login",
                    isOn: Binding<Bool>(
                        get: { SMAppService.mainApp.status == .enabled },
                        set: { enabled in
                            if enabled { try? SMAppService.mainApp.register() }
                            else       { try? SMAppService.mainApp.unregister() }
                        }
                    )
                )
                Text("MiniFlow will start automatically when you log in.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } header: { Text("Startup") }

            Section {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Accessibility Permission")
                            .font(.system(size: 13))
                        Text("Required for MiniFlow to type text into other apps. After granting, you may need to restart MiniFlow.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Open Settings") {
                        NSWorkspace.shared.open(
                            URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!
                        )
                    }
                    .buttonStyle(.borderless)
                    .foregroundColor(.accentColor)
                    .font(.system(size: 12, weight: .medium))
                }
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Fn Key Setting")
                            .font(.system(size: 13))
                        Text("Set 'Press Fn key to' -> 'Do Nothing' in Keyboard settings.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Keyboard Settings") {
                        NSWorkspace.shared.open(
                            URL(string: "x-apple.systempreferences:com.apple.preference.keyboard")!
                        )
                    }
                    .buttonStyle(.borderless)
                    .foregroundColor(.accentColor)
                    .font(.system(size: 12, weight: .medium))
                }
            } header: { Text("Permissions") }
        }
        .formStyle(.grouped)
        .padding()
    }
}
