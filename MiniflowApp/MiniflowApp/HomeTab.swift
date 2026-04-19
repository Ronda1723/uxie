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
                    .font(.custom("Georgia-Bold", size: 22))
                    .foregroundStyle(Color.black)

                // Fn card
                fnCard

                // Command bar
                commandBar

                // History or empty state
                if vm.history.isEmpty {
                    emptyState
                } else {
                    historySection
                }
            }
            .padding(24)
        }
    }

    // MARK: - Fn Card

    private var fnCard: some View {
        DictationWidget(vm: vm)
            .background(Color.fnCardBg)
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .stroke(Color.fnCardBorder, lineWidth: 1)
            )
    }

    // MARK: - Command Bar

    private var commandBar: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(Color(hex: "C7C7CC"))
                .font(.system(size: 13))
            TextField("Type a command or ask AI...", text: $commandText)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .foregroundStyle(Color.black)
                .onSubmit { sendCommand() }
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
                .background(commandText.trimmingCharacters(in: .whitespaces).isEmpty
                            ? Color(hex: "1C1C1E").opacity(0.4)
                            : Color(hex: "1C1C1E"))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
            .buttonStyle(.plain)
            .disabled(commandText.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(.white)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.navActive, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.05), radius: 3, y: 1)
    }

    // MARK: - Empty State

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "mic")
                .font(.system(size: 28))
                .foregroundStyle(Color(hex: "C7C7CC"))
                .padding(.bottom, 2)
            Text("No activity yet")
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(Color(hex: "8E8E93"))
            Text("Hold Fn to start dictating")
                .font(.system(size: 12))
                .foregroundStyle(Color(hex: "C7C7CC"))
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 48)
    }

    // MARK: - History

    private var historySection: some View {
        VStack(alignment: .leading, spacing: 10) {
            let groups = groupedHistory
            let sortedKeys = groups.keys.sorted { groupOrder($0) < groupOrder($1) }

            ForEach(sortedKeys, id: \.self) { key in
                Text(key)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Color.black)
                    .padding(.top, 6)

                ForEach(groups[key] ?? []) { entry in
                    HistoryCard(entry: entry)
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
                let fmt = DateFormatter(); fmt.dateStyle = .medium
                key = fmt.string(from: date)
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

// MARK: - History Card

private struct HistoryCard: View {
    let entry: HistoryEntry

    var body: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(entry.success ? Color.green.opacity(0.55) : Color.red.opacity(0.55))
                .frame(width: 8, height: 8)

            VStack(alignment: .leading, spacing: 4) {
                Text(entry.transcript)
                    .font(.system(size: 13))
                    .foregroundStyle(Color.black)
                    .lineLimit(1)

                if !entry.actions.isEmpty {
                    HStack(spacing: 4) {
                        ForEach(entry.actions.prefix(3), id: \.action) { action in
                            Text(action.action.replacingOccurrences(of: "_", with: " "))
                                .font(.system(size: 10))
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(
                                    RoundedRectangle(cornerRadius: 4)
                                        .fill(action.success
                                              ? Color.green.opacity(0.12)
                                              : Color.red.opacity(0.12))
                                )
                                .foregroundStyle(action.success ? Color.successGreen : Color.errorRed)
                        }
                        if entry.actions.count > 3 {
                            Text("+\(entry.actions.count - 3)")
                                .font(.system(size: 10))
                                .foregroundStyle(Color(hex: "8E8E93"))
                        }
                    }
                }
            }

            Spacer()

            Text(relativeTime(entry.timestamp))
                .font(.system(size: 10))
                .foregroundStyle(Color(hex: "8E8E93"))
        }
        .padding(10)
        .background(.white)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.navActive, lineWidth: 1)
        )
    }

    private func relativeTime(_ timestamp: String) -> String {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = iso.date(from: timestamp) else { return "" }
        let diff = Date().timeIntervalSince(date)
        if diff < 60    { return "Just now" }
        if diff < 3600  { return "\(Int(diff / 60))m ago" }
        if diff < 86400 { return "\(Int(diff / 3600))h ago" }
        return "\(Int(diff / 86400))d ago"
    }
}
