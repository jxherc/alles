import SafariServices
import SwiftUI

/// the search lives on the tab view (that's what puts the glass field in the tab bar),
/// so its state sits above the tabs too
@Observable
final class SearchStore {
    var query = ""
    var result: SearchResponse?
    var busy = false
    var problem: String?

    func search(_ session: Session) async {
        let text = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        busy = true
        problem = nil
        defer { busy = false }
        do {
            result = try await session.api.send("POST", "/api/andromeda/search", SearchRequest(query: text, overview: false))
        } catch {
            problem = session.handle(error)
        }
    }
}

struct AndromedaView: View {
    @Environment(Session.self) private var session
    @Environment(SearchStore.self) private var store
    @State private var reading: URL?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Space.xl) {
                    if store.busy {
                        ProgressView().frame(maxWidth: .infinity).padding(.top, Space.xxl)
                    } else if let problem = store.problem {
                        Text(problem).font(.subheadline).foregroundStyle(Color.danger)
                    } else if let result = store.result {
                        if let typed = result.correctedFrom {
                            Text("showing results for **\(result.query)**, not \(typed)")
                                .font(.subheadline)
                                .foregroundStyle(Color.inkMuted)
                        }
                        if result.results.isEmpty {
                            QuietNote(text: result.error?.isEmpty == false ? result.error! : "no results")
                        }
                        ForEach(result.results) { row in
                            Button { reading = URL(string: row.url) } label: { ResultRow(row: row) }
                                .buttonStyle(.plain)
                        }
                    }
                }
                .readableWidth(680)
                .pageGutter()
                .padding(.bottom, Space.xxl)
            }
            .pageBackground()
            .navigationTitle("andromeda")
            .modifier(PadSearch(store: store, session: session))
            .sheet(item: $reading) { url in
                SafariView(url: url).ignoresSafeArea()
            }
        }
    }
}

private struct PadSearch: ViewModifier {
    @Bindable var store: SearchStore
    let session: Session

    func body(content: Content) -> some View {
        if UIDevice.current.userInterfaceIdiom == .phone {
            content
        } else {
            content
                .searchable(text: $store.query, placement: .navigationBarDrawer(displayMode: .always), prompt: "search the web")
                .onSubmit(of: .search) { Task { await store.search(session) } }
        }
    }
}

private struct ResultRow: View {
    let row: SearchResult

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            Text(row.publisher ?? URL(string: row.url)?.host() ?? row.url)
                .font(.footnote)
                .foregroundStyle(Color.inkMuted)
                .lineLimit(1)
            Text(row.title)
                .font(.headline.weight(.medium))
                .foregroundStyle(Color.linkText)
                .multilineTextAlignment(.leading)
            if let snippet = row.snippet, !snippet.isEmpty {
                Text(snippet)
                    .font(.subheadline)
                    .foregroundStyle(Color.inkSoft)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(.rect)
    }
}

extension URL: @retroactive Identifiable {
    public var id: String { absoluteString }
}

struct SafariView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        let vc = SFSafariViewController(url: url)
        vc.preferredControlTintColor = UIColor(named: "AccentColor")
        return vc
    }

    func updateUIViewController(_ vc: SFSafariViewController, context: Context) {}
}
