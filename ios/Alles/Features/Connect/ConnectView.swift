import SwiftUI

struct ConnectView: View {
    @Environment(Session.self) private var session
    @State private var address = UserDefaults.standard.string(forKey: "server") ?? ""
    @State private var password = ""
    @State private var server: URL?
    @State private var busy = false
    @State private var problem: String?
    @FocusState private var focus: Field?

    private enum Field { case address, password }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Space.xl) {
                VStack(alignment: .leading, spacing: Space.l) {
                    AllesDot(size: 28, working: busy)
                    Text("alles")
                        .font(.system(size: 40, weight: .semibold))
                        .foregroundStyle(Color.ink)
                }
                .padding(.top, 72)

                VStack(alignment: .leading, spacing: Space.l) {
                    field("address", text: $address, prompt: "alles.example.com or 100.64.0.3:6769")
                        .focused($focus, equals: .address)
                        .textContentType(.URL)
                        .keyboardType(.URL)
                        .submitLabel(.next)
                        .disabled(server != nil)
                        .onSubmit { Task { await next() } }

                    if server != nil {
                        SecureField("password", text: $password)
                            .textContentType(.password)
                            .focused($focus, equals: .password)
                            .submitLabel(.go)
                            .onSubmit { Task { await next() } }
                            .modifier(FieldLook(label: "password"))
                            .transition(.move(edge: .top).combined(with: .opacity))
                    }

                    if let text = problem ?? session.notice {
                        Text(text)
                            .font(.subheadline)
                            .foregroundStyle(Color.danger)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                HStack(spacing: Space.s) {
                    if server != nil {
                        Button("change address") {
                            withAnimation { server = nil; password = ""; problem = nil }
                            focus = .address
                        }
                        .buttonStyle(.glass)
                        .controlSize(.large)
                    }
                    Spacer(minLength: 0)
                    Button {
                        Task { await next() }
                    } label: {
                        Text(server == nil ? "continue" : "sign in")
                            .foregroundStyle(Color.onActive)
                            .frame(minWidth: 96)
                    }
                    .buttonStyle(.glassProminent)
                    .controlSize(.large)
                    .disabled(busy || address.trimmingCharacters(in: .whitespaces).isEmpty || (server != nil && password.isEmpty))
                }
            }
            .padding(.horizontal, Space.xl)
            .frame(maxWidth: 460)
            .frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
        .pageBackground()
        .onAppear { focus = server == nil ? .address : .password }
    }

    private func field(_ label: String, text: Binding<String>, prompt: String) -> some View {
        TextField("", text: text, prompt: Text(prompt).foregroundStyle(Color.inkMuted))
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .modifier(FieldLook(label: label))
    }

    private func next() async {
        guard !busy else { return }
        busy = true
        problem = nil
        defer { busy = false }
        do {
            if let server {
                try await session.signIn(server, password: password)
                return
            }
            guard let url = Session.normalize(address) else {
                problem = "that doesn't look like an address."
                return
            }
            if try await session.check(url) {
                withAnimation { server = url }
                focus = .password
            } else {
                try await session.signIn(url, password: nil)
            }
        } catch {
            problem = error.localizedDescription
        }
    }
}

/// a labelled field: label above, soft fill with its own edge (design-system 0041)
private struct FieldLook: ViewModifier {
    let label: String

    func body(content: Content) -> some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text(label)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(Color.inkSoft)
            content
                .font(.body)
                .foregroundStyle(Color.ink)
                .padding(.horizontal, Space.l)
                .frame(minHeight: 50)
                .background(Color.ink.opacity(0.05), in: .rect(cornerRadius: 14))
                .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Color.ink.opacity(0.12)))
        }
    }
}
