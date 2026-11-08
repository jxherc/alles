import SwiftUI
import UIKit

private struct AuthMe: Decodable {
    let enabled: Bool
    let authenticated: Bool
}

private struct LoginBody: Encodable { let password: String }
private struct TokenBody: Encodable {
    let name: String
    let scopes: [String]
}
private struct TokenReply: Decodable { let token: String? }

/// who the app talks to. signing in mints an api token, because alles keeps login sessions in
/// memory only (core/auth.py) and a server restart would sign the phone out.
@Observable
final class Session {
    enum Phase { case starting, signedOut, signedIn }

    var phase: Phase = .starting
    var server: URL?
    var token: String?
    /// the browser session cookie, for the apps that open as web pages
    var cookie: String?
    var notice: String?

    var api: API { API(base: server ?? URL(string: "http://localhost")!, token: token) }

    func restore() async {
        guard phase == .starting else { return }
        if let saved = UserDefaults.standard.string(forKey: "server"), let url = URL(string: saved) {
            server = url
            token = Keychain.get("token")
            cookie = Keychain.get("cookie")
            phase = .signedIn
        } else {
            phase = .signedOut
        }
    }

    /// "alles.example.com", "100.64.0.3:6769" or a full url
    static func normalize(_ typed: String) -> URL? {
        var text = typed.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        if !text.contains("://") {
            let host = text.split(separator: "/").first.map(String.init) ?? text
            let looksLocal = host.first?.isNumber == true || host.hasPrefix("localhost") || host.contains(":")
            text = (looksLocal ? "http://" : "https://") + text
        }
        guard var parts = URLComponents(string: text), parts.host?.isEmpty == false else { return nil }
        parts.path = ""
        parts.query = nil
        return parts.url
    }

    /// step 1: is there an alles at this address, and does it want a password
    func check(_ url: URL) async throws -> Bool {
        let probe = API(base: url, token: nil)
        let health: OK = try await probe.get("/health")
        guard health.ok == true else { throw APIError(status: 0, message: "that address isn't an alles server.") }
        let me: AuthMe = try await probe.get("/api/auth/me")
        return me.enabled && !me.authenticated
    }

    /// step 2: sign in with the owner password and keep a token for this device
    func signIn(_ url: URL, password: String?) async throws {
        let probe = API(base: url, token: nil)
        var minted: String?
        var sessionCookie: String?
        if let password {
            var req = probe.request("POST", "/api/auth/login", json: try JSONEncoder().encode(LoginBody(password: password)))
            req.httpShouldHandleCookies = true
            _ = try await probe.raw(req)
            sessionCookie = HTTPCookieStorage.shared.cookies(for: url)?.first { $0.name == "aide_session" }?.value
            let device = UIDevice.current.userInterfaceIdiom == .pad ? "ipad" : "iphone"
            let reply: TokenReply = try await probe.send(
                "POST", "/api/tokens",
                TokenBody(name: "alles app on \(device)", scopes: ["read", "write", "models"])
            )
            minted = reply.token
            guard minted != nil else { throw APIError(status: 0, message: "alles didn't hand out a token.") }
        }
        server = url
        token = minted
        cookie = sessionCookie
        UserDefaults.standard.set(url.absoluteString, forKey: "server")
        Keychain.set(minted, for: "token")
        Keychain.set(sessionCookie, for: "cookie")
        notice = nil
        withAnimation { phase = .signedIn }
    }

    func signOut(_ reason: String? = nil) {
        token = nil
        cookie = nil
        Keychain.set(nil, for: "token")
        Keychain.set(nil, for: "cookie")
        notice = reason
        withAnimation { phase = .signedOut }
    }

    /// any 401 means the token was revoked in alles settings › tokens
    func handle(_ error: Error) -> String {
        if let e = error as? APIError, e.status == 401 {
            signOut("this device's token stopped working. sign in again.")
        }
        return error.localizedDescription
    }
}
