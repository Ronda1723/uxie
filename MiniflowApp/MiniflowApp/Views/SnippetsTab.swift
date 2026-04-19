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

            // Add section
            VStack(alignment: .leading, spacing: 8) {
                TextField("Trigger (e.g. /sig)", text: $trigger)
                    .textFieldStyle(.roundedBorder)

                ZStack(alignment: .topLeading) {
                    if expansion.isEmpty {
                        Text("Expansion text...")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 5)
                            .padding(.vertical, 8)
                    }
                    TextEditor(text: $expansion)
                        .font(.system(size: 12))
                        .frame(height: 64)
                        .scrollContentBackground(.hidden)
                        .background(.clear)
                }
                .padding(4)
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color(hex: "D1D1D6"), lineWidth: 1)
                )

                HStack {
                    Spacer()
                    Button("Add Snippet") {
                        let t = trigger.trimmingCharacters(in: .whitespaces)
                        let e = expansion.trimmingCharacters(in: .whitespaces)
                        guard !t.isEmpty, !e.isEmpty else { return }
                        trigger = ""; expansion = ""
                        Task { await vm.add(trigger: t, expansion: e) }
                    }
                    .disabled(trigger.trimmingCharacters(in: .whitespaces).isEmpty
                              || expansion.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }

            Divider()

            if vm.isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if vm.entries.isEmpty {
                emptyState
            } else {
                List {
                    ForEach(vm.entries, id: \.trigger) { entry in
                        HStack(alignment: .top, spacing: 10) {
                            Text(entry.trigger)
                                .font(.system(size: 11, weight: .medium))
                                .padding(.horizontal, 7)
                                .padding(.vertical, 3)
                                .background(Color.fnCardBorder.opacity(0.6))
                                .clipShape(RoundedRectangle(cornerRadius: 5))

                            Text(entry.expansion)
                                .font(.system(size: 12))
                                .foregroundStyle(.secondary)
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
        VStack(spacing: 12) {
            Image(systemName: "text.badge.plus")
                .font(.system(size: 36))
                .foregroundStyle(.secondary)
            Text("No snippets yet")
                .font(.system(size: 14))
                .foregroundStyle(.secondary)
            Text("Add a trigger and expansion text above.")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
