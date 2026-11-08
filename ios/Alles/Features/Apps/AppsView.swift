import SwiftUI
import WebKit

/// the specialist apps. docs is native; the rest open alles's own pages, signed in.
struct AppsView: View {
    struct SpecialistApp: Identifiable, Hashable {
        let name: String
        let symbol: String
        /// the web app's id in static/js/subdomain.js: its path (/files) or subdomain (files.)
        let sub: String
        var id: String { sub }
    }

    static let web: [SpecialistApp] = [
        .init(name: "inbox", symbol: "tray", sub: "inbox"),
        .init(name: "files", symbol: "folder", sub: "files"),
        .init(name: "library", symbol: "books.vertical", sub: "library"),
        .init(name: "health", symbol: "heart", sub: "health"),
        .init(name: "finance", symbol: "creditcard", sub: "finance"),
        .init(name: "vault", symbol: "lock", sub: "passwords"),
        .init(name: "server", symbol: "server.rack", sub: "server"),
    ]

    var body: some View {
        NavigationStack {
            List {
                NavigationLink {
                    DocsView()
                } label: {
                    row("docs", "doc.text")
                }
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)
                ForEach(Self.web) { app in
                    NavigationLink(value: app) { row(app.name, app.symbol) }
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .pageBackground()
            .navigationTitle("apps")
            .navigationDestination(for: SpecialistApp.self) { app in
                WebAppView(app: app)
            }
        }
    }

    private func row(_ name: String, _ symbol: String) -> some View {
        Label {
            Text(name).foregroundStyle(Color.ink)
        } icon: {
            Image(systemName: symbol).foregroundStyle(Color.inkSoft)
        }
        .frame(minHeight: 44)
    }
}

struct WebAppView: View {
    @Environment(Session.self) private var session
    let app: AppsView.SpecialistApp
    @State private var page = WebPage()

    var body: some View {
        WebView(page)
            .ignoresSafeArea(edges: .bottom)
            .pageBackground()
            .navigationTitle(app.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar(.hidden, for: .tabBar)
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button { page.reload() } label: { Label("reload", systemImage: "arrow.clockwise") }
                }
            }
            .task { await open() }
    }

    private func open() async {
        guard let base = session.server else { return }
        let me: ShellAddress? = try? await API(base: base, token: nil).get("/api/auth/me")
        let url = WebAppView.address(app.sub, base: base, appUrls: me?.appUrls ?? "", baseDomain: me?.baseDomain ?? "")
        if let value = session.cookie, let host = url.host() {
            let props: [HTTPCookiePropertyKey: Any] = [
                .name: "aide_session", .value: value, .domain: host, .path: "/",
                .expires: Date.now.addingTimeInterval(30 * 86400),
            ]
            if let cookie = HTTPCookie(properties: props) {
                await WKWebsiteDataStore.default().httpCookieStore.setCookie(cookie)
            }
        }
        page.load(URLRequest(url: url))
    }

    /// the same rule as singleHost() in static/js/subdomain.js: one address (an ip, a plain
    /// name, or app_urls "path") puts each app on a path, otherwise each app has a subdomain
    static func address(_ sub: String, base: URL, appUrls: String, baseDomain: String) -> URL {
        let host = base.host() ?? ""
        let isIP = { (h: String) in h.contains(":") || h.split(separator: ".").count == 4 && h.allSatisfy { $0.isNumber || $0 == "." } }
        let localhost = host == "localhost" || host.hasSuffix(".localhost")
        let underDomain = baseDomain != "localhost" && baseDomain.contains(".") && !isIP(baseDomain)
            && (host == baseDomain || host.hasSuffix("." + baseDomain))
        let oneAddress = appUrls == "path" || !(localhost || underDomain)
        var parts = URLComponents(url: base, resolvingAgainstBaseURL: false)!
        if oneAddress {
            parts.path = "/" + sub
        } else {
            parts.host = sub + "." + (localhost ? "localhost" : baseDomain)
            parts.path = "/"
        }
        return parts.url ?? base
    }
}

nonisolated private struct ShellAddress: Decodable {
    let baseDomain: String?
    let appUrls: String?

    enum CodingKeys: String, CodingKey {
        case baseDomain = "base_domain"
        case appUrls = "app_urls"
    }
}
