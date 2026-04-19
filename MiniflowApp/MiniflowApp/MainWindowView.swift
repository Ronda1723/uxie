import SwiftUI

struct MainWindowView: View {
    @ObservedObject var vm: AgentViewModel
    @State private var selectedTab = "home"
    @State private var showSettings = false
    var onSettings: () -> Void

    var body: some View {
        HStack(spacing: 0) {

            // Left sidebar (200pt fixed)
            SidebarView(vm: vm, selectedTab: $selectedTab, onSettings: onSettings)

            // Main content area (white card)
            ZStack(alignment: .topLeading) {
                Color.white

                Group {
                    switch selectedTab {
                    case "dictionary":
                        DictionaryTab()
                    case "snippets":
                        SnippetsTab()
                    default:
                        HomeTab(vm: vm)
                    }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 20))
            .padding(12)

            // Right action feed (slides in when actions exist)
            if !vm.actions.isEmpty || vm.isProcessing {
                ActionFeedPanel(vm: vm)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            }
        }
        .frame(width: 860, height: 600)
        .background(Color.bgWarm)
        .animation(.easeInOut(duration: 0.2), value: vm.actions.isEmpty && !vm.isProcessing)
    }
}
