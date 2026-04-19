import SwiftUI

struct HomeTab: View {
    @ObservedObject var vm: AgentViewModel
    @State private var commandText = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {

                // Welcome header
                Text(vm.userName.isEmpty
                     ? "Welcome back"
                     : "Welcome back, \(vm.userName)")
                    .font(.custom("Georgia-Bold", size: 26))
                    .foregroundStyle(Color.black)
                    .padding(.bottom, 2)

                // Stats row
                statsRow

                // Fn card
                fnCard

                // Command bar
                commandBar

                // History
                if !vm.history.isEmpty {
                    historySection
                }
            }
            .padding(28)
        }
    }

    // MARK: - Stats Row

    private var statsRow: some View {
        HStack(spacing: 0) {
            statCell(icon: "🔥", value: "0", label: "day streak")
            Divider().frame(height: 32)
            statCell(icon: "🚀", value: "0", label: "words spoken")
            Divider().frame(height: 32)
            statCell(icon: "🏆", value: "—", label: "WPM")
        }
        .background(.white)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color(hex: "E5E5EA"), lineWidth: 1))
    }

    private func statCell(icon: String, value: String, label: String) -> some View {
        HStack(spacing: 6) {
            Text(icon).font(.system(size: 14))
            VStack(alignment: .leading, spacing: 1) {
                Text(value)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color.black)
                Text(label)
                    .font(.system(size: 10))
                    .foregroundStyle(Color.black)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 10)
        .padding(.horizontal, 8)
    }

    // MARK: - Fn Card

    private var fnCard: some View {
        VStack(alignment: .leading, spacing: 0) {
            DictationWidget(vm: vm)

            // CTA button when idle
            if !vm.isListening && !vm.isProcessing {
                Divider().padding(.horizontal, 16)
                Button {
                    Task { await vm.startListening() }
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "mic.fill")
                            .font(.system(size: 11))
                        Text("Start dictating")
                            .font(.system(size: 12, weight: .semibold))
                    }
                    .foregroundStyle(.white)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                    .background(Color(hex: "1C1C1E"))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }
                .buttonStyle(.plain)
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            }
        }
        .background(Color.fnCardBg)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .stroke(Color.fnCardBorder, lineWidth: 1)
        )
    }

    // MARK: - Command Bar

    private var commandBar: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(Color.black)
                .font(.system(size: 13))
            TextField("Type a command or ask AI...", text: $commandText)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .foregroundStyle(Color.black)
                .onSubmit { sendCommand() }
            if !commandText.isEmpty {
                Button(action: sendCommand) {
                    HStack(spacing: 5) {
                        Image(systemName: "paperplane.fill")
                            .font(.system(size: 11))
                        Text("Execute")
                            .font(.system(size: 12, weight: .semibold))
                    }
                    .foregroundStyle(.white)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 7)
                    .background(Color(hex: "1C1C1E"))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
        .background(.white)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color(hex: "E5E5EA"), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.04), radius: 3, y: 1)
    }

    // MARK: - History (table style)

    private var historySection: some View {
        VStack(alignment: .leading, spacing: 16) {
            let groups = groupedHistory
            let sortedKeys = groups.keys.sorted { groupOrder($0) < groupOrder($1) }

            ForEach(sortedKeys, id: \.self) { key in
                VStack(alignment: .leading, spacing: 0) {
                    // Date header
                    HStack {
                        Text(key.uppercased())
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(Color.black)
                        Spacer()
                        if key == "Today" {
                            Button("Clear all") {
                                Task { try? await APIClient.shared.invokeVoid("clear_history")
                                      await vm.loadHistory() }
                            }
                            .buttonStyle(.plain)
                            .font(.system(size: 10))
                            .foregroundStyle(Color.black)
                        }
                    }
                    .padding(.bottom, 6)

                    // Table
                    VStack(spacing: 0) {
                        ForEach(Array((groups[key] ?? []).enumerated()), id: \.element.id) { idx, entry in
                            HistoryRow(entry: entry)
                            if idx < (groups[key]?.count ?? 0) - 1 {
                                Divider().padding(.leading, 70)
                            }
                        }
                    }
                    .background(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                    .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color(hex: "E5E5EA"), lineWidth: 1))
                }
            }
        }
    }

    private var groupedHistory: [String: [HistoryEntry]] {
        var result: [String: [HistoryEntry]] = [:]
        let cal = Calendar.current
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        for entry in vm.history {
            guard let date = iso.date(from: entry.timestamp) else { continue }
            let key: String
            if cal.isDateInToday(date)          { key = "Today" }
            else if cal.isDateInYesterday(date) { key = "Yesterday" }
            else {
                let fmt = DateFormatter()
                fmt.dateFormat = "MMMM d"
                key = fmt.string(from: date).uppercased()
            }
            result[key, default: []].append(entry)
        }
        return result
    }

    private func groupOrder(_ key: String) -> Int {
        switch key {
        case "Today":     return 0
        case "Yesterday": return 1
        default:          return 2
        }
    }

    private func sendCommand() {
        let text = commandText.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        commandText = ""
        Task { await vm.executeCommand(text) }
    }
}

// MARK: - History Row (table style)

private struct HistoryRow: View {
    let entry: HistoryEntry

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            // Time column
            Text(formattedTime(entry.timestamp))
                .font(.system(size: 11))
                .foregroundStyle(Color.black)
                .frame(width: 58, alignment: .leading)
                .padding(.top, 1)

            // Command text
            Text(entry.transcript)
                .font(.system(size: 13))
                .foregroundStyle(Color.black)
                .lineLimit(1)

            Spacer()

            // Success indicator
            Image(systemName: entry.actions.allSatisfy({ $0.success }) ? "checkmark.circle.fill" : "xmark.circle.fill")
                .font(.system(size: 12))
                .foregroundStyle(entry.actions.allSatisfy({ $0.success }) ? Color(hex: "34C759") : Color(hex: "FF3B30"))
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }

    private func formattedTime(_ timestamp: String) -> String {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = iso.date(from: timestamp) else { return "" }
        let fmt = DateFormatter()
        fmt.dateFormat = "hh:mm a"
        return fmt.string(from: date)
    }
}
