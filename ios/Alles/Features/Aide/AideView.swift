import SwiftUI

struct AideView: View {
    @Environment(Session.self) private var session
    @Environment(AideStore.self) private var aide
    @State private var column: NavigationSplitViewColumn = .detail

    var body: some View {
        NavigationSplitView(preferredCompactColumn: $column) {
            ChatList(column: $column)
                .navigationSplitViewColumnWidth(min: 260, ideal: 300, max: 360)
        } detail: {
            ChatThread()
        }
        .task {
            if aide.current == nil { await aide.open(nil, session.api) }
            await aide.loadSessions(session.api)
        }
    }
}

private struct ChatList: View {
    @Environment(Session.self) private var session
    @Environment(AideStore.self) private var aide
    @Binding var column: NavigationSplitViewColumn

    var body: some View {
        List {
            ForEach(aide.sessions) { chat in
                Button {
                    Task { await aide.open(chat, session.api) }
                    column = .detail
                } label: {
                    HStack(spacing: Space.m) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(chat.primary == true ? "aide" : chat.name)
                                .font(.body.weight(chat.id == aide.current?.id ? .semibold : .regular))
                                .foregroundStyle(Color.ink)
                                .lineLimit(1)
                            if let when = chat.lastMessageAt.flatMap(Day.utc) {
                                Text(when, format: .relative(presentation: .named))
                                    .font(.footnote)
                                    .foregroundStyle(Color.inkMuted)
                            }
                        }
                        Spacer()
                        if chat.id == aide.current?.id && aide.replying {
                            AllesDot(size: 8, working: true)
                        }
                    }
                    .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .listRowBackground(chat.id == aide.current?.id ? Color.ink.opacity(0.08) : Color.clear)
                .listRowSeparator(.hidden)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .pageBackground()
        .navigationTitle("chats")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await aide.newChat(session.api) }
                    column = .detail
                } label: {
                    Label("new chat", systemImage: "square.and.pencil")
                }
                .disabled(aide.replying)
            }
        }
        .refreshable { await aide.loadSessions(session.api) }
    }
}

private struct ChatThread: View {
    @Environment(Session.self) private var session
    @Environment(AideStore.self) private var aide
    @State private var draft = ""
    @State private var position = ScrollPosition(edge: .bottom)
    @State private var awayFromBottom = false
    @FocusState private var typing: Bool

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: Space.xl) {
                if aide.messages.isEmpty && !aide.waiting {
                    VStack(alignment: .leading, spacing: Space.m) {
                        AllesDot(size: 14)
                        Text("ask aide anything")
                            .font(.title3.weight(.medium))
                            .foregroundStyle(Color.inkSoft)
                    }
                    .padding(.top, 120)
                }
                ForEach(aide.messages) { message in
                    MessageRow(message: message, read: message.id == aide.readID && aide.messages.last?.id == message.id)
                        .id(message.id)
                }
                if aide.waiting {
                    TypingDots()
                        .padding(.vertical, Space.s)
                        .transition(.opacity)
                }
                if let problem = aide.problem {
                    Text(problem)
                        .font(.subheadline)
                        .foregroundStyle(Color.danger)
                }
            }
            .padding(.horizontal, Space.l)
            .padding(.vertical, Space.l)
            .readableWidth(720, alignment: .center)
        }
        .accessibilityIdentifier("aide.thread")
        .scrollPosition($position)
        .defaultScrollAnchor(.bottom)
        .defaultScrollAnchor(.bottom, for: .sizeChanges)
        // scrolling back to read puts the keyboard away, so the tab bar is one tap off
        .scrollDismissesKeyboard(.immediately)
        .onScrollGeometryChange(for: Bool.self) { geo in
            geo.contentSize.height - geo.visibleRect.maxY > 240
        } action: { _, away in
            withAnimation(.snappy) { awayFromBottom = away }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            composer
        }
        // back from another tab: show the newest, like a messages app does
        .onAppear { position.scrollTo(edge: .bottom) }
        .onChange(of: typing) { _, now in
            guard now, !awayFromBottom else { return }
            Task {
                try? await Task.sleep(for: .milliseconds(350))
                withAnimation(.snappy) { position.scrollTo(edge: .bottom) }
            }
        }
        .pageBackground()
        .navigationTitle(aide.current.map { $0.primary == true ? "aide" : $0.name } ?? "aide")
        .navigationBarTitleDisplayMode(.inline)
        .animation(.snappy, value: aide.waiting)
    }

    private var composer: some View {
        VStack(spacing: Space.s) {
            if awayFromBottom {
                GlassCircleButton(systemImage: "arrow.down", label: "jump to latest", size: 40) {
                    withAnimation(.snappy) { position.scrollTo(edge: .bottom) }
                }
                .transition(.scale(scale: 0.6).combined(with: .opacity))
            }
            Composer(draft: $draft, typing: $typing)
        }
        .padding(.horizontal, Space.m)
        .padding(.bottom, Space.s)
        .readableWidth(760, alignment: .center)
    }
}

private struct MessageRow: View {
    let message: ChatMessage
    let read: Bool

    var body: some View {
        if message.role == "user" {
            VStack(alignment: .trailing, spacing: Space.xs) {
                Text(message.content)
                    .font(.body)
                    .foregroundStyle(Color.ink)
                    .textSelection(.enabled)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(Color.ink.opacity(0.08), in: .rect(cornerRadius: 20))
                if read {
                    Text("read")
                        .font(.caption)
                        .foregroundStyle(Color.inkMuted)
                        .padding(.trailing, Space.s)
                        .transition(.opacity)
                }
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
            .padding(.leading, 48)
        } else {
            MarkdownText(source: message.content)
                .textSelection(.enabled)
        }
    }
}

/// the floating glass entry: field and send share one glass container, so send melts into
/// stop while a reply runs
private struct Composer: View {
    @Environment(Session.self) private var session
    @Environment(AideStore.self) private var aide
    @Binding var draft: String
    var typing: FocusState<Bool>.Binding
    @Namespace private var glass

    private var canSend: Bool { !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && aide.current != nil }

    var body: some View {
        // container spacing under the gap: the two shapes stay apart at rest and only melt
        // into each other while send turns into stop
        GlassEffectContainer(spacing: Space.xs) {
            HStack(alignment: .bottom, spacing: Space.m) {
                TextField("message aide", text: $draft, axis: .vertical)
                    .lineLimit(1...6)
                    .font(.body)
                    .foregroundStyle(Color.ink)
                    .focused(typing)
                    .submitLabel(.send)
                    .onSubmit(send)
                    .padding(.horizontal, Space.l)
                    .padding(.vertical, 12)
                    .frame(minHeight: 48)
                    .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 24))
                    .glassEffectID("field", in: glass)

                if aide.replying {
                    button("stop.fill", label: "stop") { aide.stop(session.api) }
                        .glassEffectID("action", in: glass)
                        .accessibilityIdentifier("composer.stop")
                } else if canSend {
                    button("arrow.up", label: "send", action: send)
                        .glassEffectID("action", in: glass)
                        .accessibilityIdentifier("composer.send")
                }
            }
            .animation(.smooth(duration: 0.3), value: aide.replying)
            .animation(.smooth(duration: 0.3), value: canSend)
        }
    }

    private func button(_ symbol: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Color.onActive)
                .frame(width: 48, height: 48)
                .contentShape(.circle)
        }
        .buttonStyle(.plain)
        .glassEffect(.regular.tint(.active).interactive(), in: .circle)
        .accessibilityLabel(label)
    }

    private func send() {
        guard canSend, !aide.replying else { return }
        let text = draft
        draft = ""
        aide.send(text, session.api)
    }
}

/// the live reply under the tab bar while you're somewhere else: tap to go back to it
struct LiveReplyAccessory: View {
    @Environment(AideStore.self) private var aide
    let open: () -> Void

    var body: some View {
        Button(action: open) {
            HStack(spacing: Space.m) {
                AllesDot(size: 10, working: true)
                Text(aide.liveText.isEmpty ? "aide is typing" : preview)
                    .font(.subheadline)
                    .foregroundStyle(Color.ink)
                    .lineLimit(1)
                    .truncationMode(.head)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, Space.l)
            .frame(maxHeight: .infinity)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("aide is replying. open aide")
    }

    /// one line of the reply as plain words: list marks and bold stars dropped
    private var preview: String {
        aide.liveText
            .replacingOccurrences(of: "**", with: "")
            .replacingOccurrences(of: "\n- ", with: " · ")
            .replacingOccurrences(of: "\n", with: " ")
    }
}
