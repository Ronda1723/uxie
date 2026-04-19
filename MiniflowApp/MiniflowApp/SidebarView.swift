import SwiftUI

struct SidebarView: View {
    @ObservedObject var vm: AgentViewModel
    @Binding var selectedTab: String
    var onSettings: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {

            // Logo
            Text("MINIFLOW")
                .font(.custom("Georgia-Bold", size: 15))
                .foregroundStyle(Color.accentBrown)
                .padding(.horizontal, 18)
                .padding(.top, 24)
                .padding(.bottom, 20)

            // Listening status pill
            if vm.isListening {
                HStack(spacing: 6) {
                    Circle()
                        .fill(.red)
                        .frame(width: 7, height: 7)
                    Text("Listening")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.red)
                }
                .padding(.horizontal, 18)
                .padding(.bottom, 12)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }

            // Nav items
            navItem(tab: "home",       label: "Home",       icon: "house.fill")
            navItem(tab: "dictionary", label: "Dictionary", icon: "character.book.closed.fill")
            navItem(tab: "snippets",   label: "Snippets",   icon: "text.badge.plus")

            Spacer()

            Divider()
                .padding(.horizontal, 12)
                .padding(.bottom, 8)

            // Settings button
            Button(action: onSettings) {
                HStack(spacing: 8) {
                    Image(systemName: "gearshape")
                        .font(.system(size: 13))
                    Text("Settings")
                        .font(.system(size: 13))
                }
                .foregroundStyle(Color.black)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 6)
            .padding(.bottom, 16)
        }
        .frame(width: 200)
        .background(Color.bgWarm)
        .animation(.easeInOut(duration: 0.2), value: vm.isListening)
    }

    // MARK: - Nav Item

    private func navItem(tab: String, label: String, icon: String) -> some View {
        Button {
            selectedTab = tab
        } label: {
            HStack(spacing: 10) {
                Image(systemName: icon)
                    .font(.system(size: 13))
                    .frame(width: 18)
                Text(label)
                    .font(.system(size: 13))
                Spacer()
            }
            .foregroundStyle(Color.black)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(selectedTab == tab ? Color.navActive : .clear)
            )
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 8)
        .padding(.vertical, 2)
    }
}
