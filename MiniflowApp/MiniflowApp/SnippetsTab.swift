import SwiftUI

// MARK: - ViewModel

@MainActor
final class SnippetsViewModel: ObservableObject {
    @Published var entries: [(trigger: String, expansion: String)] = []
    @Published var isLoading = false
    private let api = APIClient.shared

    func load() async {
        isLoading = true
        defer { isLoading = false }
        if let dict: [String: String] = try? await api.invoke("get_snippets") {
            entries = dict.map { (trigger: $0.key, expansion: $0.value) }
                         .sorted { $0.trigger < $1.trigger }
        }
    }

    func add(trigger: String, expansion: String) async {
        try? await api.invokeVoid("add_snippet", body: ["trigger": trigger, "expansion": expansion])
        await load()
    }

    func remove(trigger: String) async {
        try? await api.invokeVoid("remove_snippet", body: ["trigger": trigger])
        entries.removeAll { $0.trigger == trigger }
    }
}

// MARK: - View

struct SnippetsTab: View {
    @StateObject private var vm = SnippetsViewModel()
    @State private var trigger = ""
    @State private var expansion = ""
    @State private var hoveredTrigger: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {

            Text("Snippets")
                .font(.custom("Georgia-Bold", size: 22))
                .foregroundStyle(Color.black)

            Text("Say a trigger phrase to expand into full text")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "8E8E93"))

            // Add row
            HStack(spacing: 10) {
                TextField("Trigger phrase...", text: $trigger)
                    .textFieldStyle(.roundedBorder)
                TextField("Expands to...", text: $expansion)
                    .textFieldStyle(.roundedBorder)
                Button("Add") {
                    let t = trigger.trimmingCharacters(in: .whitespaces)
                    let e = expansion.trimmingCharacters(in: .whitespaces)
                    guard !t.isEmpty, !e.isEmpty else { return }
                    trigger = ""; expansion = ""
                    Task { await vm.add(trigger: t, expansion: e) }
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
                    ForEach(vm.entries, id: \.trigger) { entry in
                        HStack(alignment: .top, spacing: 10) {
                            Text(entry.trigger)
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(Color.black)
                                .padding(.horizontal, 7)
                                .padding(.vertical, 3)
                                .background(Color.fnCardBorder.opacity(0.6))
                                .clipShape(RoundedRectangle(cornerRadius: 5))

                            Text(entry.expansion)
                                .font(.system(size: 12))
                                .foregroundStyle(Color(hex: "8E8E93"))
                                .lineLimit(2)

                            Spacer()

                            if hoveredTrigger == entry.trigger {
                                Button {
                                    Task { await vm.remove(trigger: entry.trigger) }
                                } label: {
                                    Image(systemName: "trash")
                                        .font(.system(size: 12))
                                        .foregroundStyle(.red)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(.vertical, 2)
                        .onHover { hoveredTrigger = $0 ? entry.trigger : nil }
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
            Text("No snippets yet")
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(Color(hex: "8E8E93"))
            Text("Add trigger phrases to expand when spoken")
                .font(.system(size: 12))
                .foregroundStyle(Color(hex: "C7C7CC"))
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 48)
    }
}
