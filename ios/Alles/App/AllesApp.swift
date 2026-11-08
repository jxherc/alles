import SwiftUI

@main
struct AllesApp: App {
    @State private var session = Session()

    var body: some Scene {
        WindowGroup {
            Group {
                switch session.phase {
                case .starting:
                    Color.page.ignoresSafeArea()
                case .signedOut:
                    ConnectView()
                case .signedIn:
                    RootView()
                }
            }
            .environment(session)
            .tint(.active)
            .task { await session.restore() }
        }
    }
}
