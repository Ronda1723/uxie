import SwiftUI

// MARK: - ViewModel

@MainActor
final class DictionaryViewModel: ObservableObject {
    @Published var entries: [(from: String, to: String)] = []
    @Published var isLoading = false
    private let api = APIClient.shared

    func load() async {
        isLoading = true
        defer { isLoading = false }
        if let dict: [String: String] = try? await api.invoke("get_dictionary") {
            entries = dict.map { (from: $0.key, to: $0.value) }
                         .sorted { $0.from < $1.from }
        }
    }

    func add(from: String, to: String) async {
        try? await api.invokeVoid("add_dictionary_word", body: ["from": from, "to": to])
        await load()
    }

    func remove(from: String) async {
        try? await api.invokeVoid("remove_dictionary_word", body: ["from": from])
        entries.removeAll { $0.from == from }
    }
}

// MARK: - View

struct DictionaryTab: View {
    @StateObject private var vm = DictionaryViewModel()
    @State private var fromWord = ""
    @State private var toWord = ""
    @State private var hoveredFrom: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {

            Text("Dictionary")
                .font(.custom("Georgia-Bold", size: 22))
                .foregroundStyle(Color.black)

            Text("Replace spoken words with custom text")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "8E8E93"))

            // Add row
            HStack(spacing: 10) {
                TextField("Say this...", text: $fromWord)
                    .textFieldStyle(.roundedBorder)
                TextField("Replace with...", text: $toWord)
                    .textFieldStyle(.roundedBorder)
                Button("Add") {
                    let f = fromWord.trimmingCharacters(in: .whitespaces)
                    let t = toWord.trimmingCharacters(in: .whitespaces)
                    guard !f.isEmpty, !t.isEmpty else { return }
                    fromWord = ""; toWord = ""
                    Task { await vm.add(from: f, to: t) }
                }
                .buttonStyle(.plain)
                .foregroundStyle(.white)
                .padding(.horizontal, 16)
                .padding(.vertical, 7)
                .background(Color(hex: "1C1C1E"))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }

            if vm.isLoading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if vm.entries.isEmpty {
                emptyState
            } else {
                List {
                    ForEach(vm.entries, id: \.from) { entry in
                        HStack {
                            Text(entry.from)
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color.black)
                            Image(systemName: "arrow.right")
                                .font(.system(size: 11))
                                .foregroundStyle(Color(hex: "8E8E93"))
                            Text(entry.to)
                                .font(.system(size: 13))
                                .foregroundStyle(Color(hex: "8E8E93"))
                            Spacer()
                            if hoveredFrom == entry.from {
                                Button {
                                    Task { await vm.remove(from: entry.from) }
                                } label: {
                                    Image(systemName: "trash")
                                        .font(.system(size: 12))
                                        .foregroundStyle(.red)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(.vertical, 2)
                        .onHover { hoveredFrom = $0 ? entry.from : nil }
                    }
                }
                .listStyle(.plain)
            }
        }
        .padding(24)
        .task { await vm.load() }
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Text("No dictionary entries")
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(Color(hex: "8E8E93"))
            Text("Add words above to customize transcription")
                .font(.system(size: 12))
                .foregroundStyle(Color(hex: "C7C7CC"))
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 48)
    }
}
