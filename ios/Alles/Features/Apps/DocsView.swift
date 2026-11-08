import SwiftUI

/// docs reads the markdown vault (/api/vault-md), the same files the web docs app edits
struct DocsView: View {
    @Environment(Session.self) private var session
    @State private var items: [DocNode] = []
    @State private var problem: String?

    var body: some View {
        List {
            if let problem {
                Text(problem).foregroundStyle(Color.danger).listRowBackground(Color.clear)
            }
            OutlineGroup(items.filter(\.isShown), children: \.folderChildren) { node in
                if node.isFolder {
                    Label(node.name, systemImage: "folder")
                        .foregroundStyle(Color.inkSoft)
                        .frame(minHeight: 40)
                } else {
                    NavigationLink {
                        DocView(path: node.path)
                    } label: {
                        Label(node.name, systemImage: "doc.text")
                            .foregroundStyle(Color.ink)
                            .frame(minHeight: 40)
                    }
                }
            }
            .listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .pageBackground()
        .navigationTitle("docs")
        .refreshable { await load() }
        .task { await load() }
    }

    private func load() async {
        do {
            let tree: DocTree = try await session.api.get("/api/vault-md/tree")
            items = tree.items
            problem = nil
        } catch {
            problem = session.handle(error)
        }
    }
}

extension DocNode {
    /// the tree's names have no extension; only markdown opens here (path ends in .md)
    var isShown: Bool { isFolder || path.hasSuffix(".md") }

    /// folders open, files don't (an empty list would still draw a disclosure arrow)
    var folderChildren: [DocNode]? {
        guard isFolder else { return nil }
        return (children ?? []).filter(\.isShown)
    }
}

struct DocView: View {
    @Environment(Session.self) private var session
    let path: String
    @State private var file: DocFile?
    @State private var draft = ""
    @State private var editing = false
    @State private var saving = false
    @State private var problem: String?

    var body: some View {
        Group {
            if editing {
                TextEditor(text: $draft)
                    .font(.system(.body, design: .monospaced))
                    .scrollContentBackground(.hidden)
                    .padding(.horizontal, Space.m)
                    .readableWidth(760, alignment: .center)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: Space.l) {
                        if let problem {
                            Text(problem).font(.subheadline).foregroundStyle(Color.danger)
                        }
                        if let file {
                            MarkdownText(source: file.content)
                                .textSelection(.enabled)
                        } else if problem == nil {
                            ProgressView().frame(maxWidth: .infinity).padding(.top, Space.xxl)
                        }
                    }
                    .padding(.horizontal, Space.l)
                    .padding(.vertical, Space.l)
                    .readableWidth(720, alignment: .center)
                }
            }
        }
        .pageBackground()
        .navigationTitle((path as NSString).lastPathComponent.replacingOccurrences(of: ".md", with: ""))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if file?.editable != false {
                ToolbarItem(placement: .primaryAction) {
                    if editing {
                        Button { Task { await save() } } label: {
                            Text("save").foregroundStyle(Color.onActive)
                        }
                        .buttonStyle(.glassProminent)
                            .disabled(saving || draft == file?.content)
                    } else {
                        Button("edit") {
                            draft = file?.content ?? ""
                            withAnimation { editing = true }
                        }
                        .disabled(file == nil)
                    }
                }
            }
            if editing {
                ToolbarItem(placement: .cancellationAction) {
                    Button("cancel", role: .cancel) { withAnimation { editing = false } }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        do {
            file = try await session.api.get("/api/vault-md/file", query: ["path": path])
            problem = nil
        } catch {
            problem = session.handle(error)
        }
    }

    private func save() async {
        guard let file else { return }
        saving = true
        defer { saving = false }
        do {
            let saved: DocSaved = try await session.api.send(
                "POST", "/api/vault-md/safety/save", DocSave(path: path, content: draft, expectedHash: file.hash)
            )
            self.file = DocFile(path: path, content: draft, hash: saved.hash, editable: file.editable)
            problem = nil
            withAnimation { editing = false }
        } catch let e as APIError where e.code == "document_conflict" {
            problem = "this doc changed somewhere else since you opened it. copy your edit, then reload."
        } catch {
            problem = session.handle(error)
        }
    }
}
