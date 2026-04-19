import SwiftUI

struct SidebarView: View {
    @ObservedObject var vm: AgentViewModel
    @Binding var selectedTab: String
    var onSettings: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {

            // Traffic lights (decorative macOS chrome)
            HStack(spacing: 6) {
                Circle().fill(Color(hex: "FF5F57")).frame(width: 10, height: 10)
                Circle().fill(Color(hex: "FEBC2E")).frame(width: 10, height: 10)
                Circle().fill(Color(hex: "28C840")).frame(width: 10, height: 10)
            }
            .padding(.horizontal, 16)
            .padding(.top, 18)
            .padding(.bottom, 16)

            // Logo row
            HStack(alignment: .center, spacing: 8) {
                Image(systemName: "waveform")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Color.accentBrown)
                Text("Miniflow")
                    .font(.custom("Georgia-Bold", size: 15))
                    .foregroundStyle(Color.accentBrown)
                Spacer()
                Text("Basic")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(Color.accentBrown.opacity(0.8))
                    .padding(.horizontal, 5)
                    .padding(.vertical, 2)
                    .background(Color.fnCardBorder)
                    .clipShape(RoundedRectangle(cornerRadius: 4))
            }
            .padding(.horizontal, 14)
            .padding(.bottom, 18)

            // Listening status pill
            if vm.isListening {
                HStack(spacing: 6) {
                    Circle()
                        .fill(.red)
                        .frame(width: 6, height: 6)
                    Text("Listening")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.red)
                }
                .padding(.horizontal, 14)
                .padding(.bottom, 10)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }

            // Nav items
            navItem(tab: "home",       label: "Home",       icon: "house.fill")
            navItem(tab: "dictionary", label: "Dictionary", icon: "character.book.closed.fill")
            navItem(tab: "snippets",   label: "Snippets",   icon: "text.badge.plus")

            Spacer()

            // Pro upgrade card
            proCard

            Divider()
                .padding(.horizontal, 10)
                .padding(.vertical, 6)

            // Bottom nav
            Button(action: onSettings) {
                HStack(spacing: 8) {
                    Image(systemName: "gearshape")
                        .font(.system(size: 12))
                    Text("Settings")
                        .font(.system(size: 12))
                }
                .foregroundStyle(Color.black)
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 4)

            Button {} label: {
                HStack(spacing: 8) {
                    Image(systemName: "questionmark.circle")
                        .font(.system(size: 12))
                    Text("Help")
                        .font(.system(size: 12))
                }
                .foregroundStyle(Color.black)
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 4)
            .padding(.bottom, 12)
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
                    .font(.system(size: 12))
                    .frame(width: 16)
                Text(label)
                    .font(.system(size: 13))
                Spacer()
            }
            .foregroundStyle(Color.black)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(
                RoundedRectangle(cornerRadius: 7)
                    .fill(selectedTab == tab ? Color.navActive : .clear)
            )
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 6)
        .padding(.vertical, 1)
    }

    // MARK: - Pro Card

    private var proCard: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Upgrade to Pro")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Color.black)
                Spacer()
                Image(systemName: "sparkles")
                    .font(.system(size: 10))
                    .foregroundStyle(Color.accentBrown)
            }
            Text("Unlock all connectors, unlimited history & team features.")
                .font(.system(size: 10))
                .foregroundStyle(Color.black)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            Button {} label: {
                Text("Learn more")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(Color.accentBrown)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(Color.fnCardBorder)
                    .clipShape(RoundedRectangle(cornerRadius: 5))
            }
            .buttonStyle(.plain)
        }
        .padding(10)
        .background(Color.fnCardBg)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.fnCardBorder, lineWidth: 1))
        .padding(.horizontal, 8)
        .padding(.bottom, 10)
    }
}
