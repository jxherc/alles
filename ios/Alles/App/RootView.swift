import SwiftUI

enum AppTab: Hashable { case home, aide, plan, apps, search }

/// the tab bar is the system's liquid glass bar: at the bottom on iphone (it shrinks while you
/// scroll), floating at the top on ipad. tab-bar-only on purpose: no app sidebar (decision 0064).
struct RootView: View {
    @Environment(Session.self) private var session
    @State private var aide = AideStore()
    @State private var search = SearchStore()
    @State private var tab: AppTab = .home

    var body: some View {
        TabView(selection: $tab) {
            Tab("home", systemImage: "house", value: AppTab.home) {
                HomeView(openAide: { tab = .aide })
            }
            Tab("aide", systemImage: "bubble.left", value: AppTab.aide) {
                AideView()
            }
            Tab("plan", systemImage: "calendar", value: AppTab.plan) {
                PlanView()
            }
            Tab("apps", systemImage: "square.grid.2x2", value: AppTab.apps) {
                AppsView()
            }
            Tab("andromeda", systemImage: "magnifyingglass", value: AppTab.search, role: .search) {
                AndromedaView()
            }
        }
        .tabViewStyle(.tabBarOnly)
        .tabBarMinimizeBehavior(.onScrollDown)
        .modifier(TabBarSearch(store: search, session: session))
        .tabViewBottomAccessory(isEnabled: aide.replying && tab != .aide) {
            LiveReplyAccessory { tab = .aide }
        }
        .environment(aide)
        .environment(search)
    }
}

/// on iphone the search tab turns the tab bar into the glass search field. that needs
/// .searchable on the tab view, which on ipad would put a search button on every tab, so ipad
/// keeps its field inside andromeda (AndromedaView)
private struct TabBarSearch: ViewModifier {
    @Bindable var store: SearchStore
    let session: Session

    func body(content: Content) -> some View {
        if UIDevice.current.userInterfaceIdiom == .phone {
            content
                .searchable(text: $store.query, prompt: "search the web")
                .tabViewSearchActivation(.searchTabSelection)
                .onSubmit(of: .search) { Task { await store.search(session) } }
        } else {
            content
        }
    }
}

/// done or not: a ring that fills. 44pt to tap, the visible ring stays small
struct CheckCircle: View {
    let done: Bool
    var tint: Color = .active
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle()
                    .strokeBorder(done ? tint : Color.inkMuted.opacity(0.7), lineWidth: 1.6)
                    .background(Circle().fill(done ? tint : .clear))
                    .frame(width: 22, height: 22)
                if done {
                    Image(systemName: "checkmark")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(Color.page)
                }
            }
            .frame(width: 44, height: 44)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .sensoryFeedback(.success, trigger: done) { _, now in now }
        .accessibilityLabel(label)
        .accessibilityValue(done ? "done" : "not done")
    }
}
