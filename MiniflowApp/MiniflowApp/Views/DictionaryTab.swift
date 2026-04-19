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

            // Add row
            HStack(spacing: 10) {
                TextField("Say this...", text: $fromWord)
                    .textFieldStyle(.roundedBorder)
                Image(systemName: "arrow.right")
                    .foregroundStyle(.secondary)
                    .font(.system(size: 11))
                TextField("Replace with...", text: $toWord)
                    .textFieldStyle(.roundedBorder)
                Button("Add") {
                    let f = fromWord.trimmingCharacters(in: .whitespaces)
                    let t = toWord.trimmingCharacters(in: .whitespaces)
                    guard !f.isEmpty, !t.isEmpty else { return }
                    fromWord = ""; toWord = ""
                    Task { await vm.add(from: f, to: t) }
                }
                .disabled(fromWord.trimmingCharacters(in: .whitespaces).isEmpty
                          || toWord.trimmingCharacters(in: .whitespaces).isEmpty)
            }

            Divider()

            if vm.isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if vm.entries.isEmpty {
                emptyState
            } else {
                List {
                    ForEach(vm.entries, id: \.from) { entry in
                        HStack {
                            Text(entry.from)
                                .font(.system(size: 13, weight: .medium))
                            Image(systemName: "arrow.right")
                                .font(.system(size: 11))
                                .foregroundStyle(.secondary)
                            Text(entry.to)
                                .font(.system(size: 13))
                                .foregroundStyle(.secondary)
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
        VStack(spacing: 12) {
            Image(systemName: "character.book.closed")
                .font(.system(size: 36))
                .foregroundStyle(.secondary)
            Text("No replacements yet")
                .font(.system(size: 14))
                .foregroundStyle(.secondary)
            Text("Add words above to auto-replace during dictation.")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
