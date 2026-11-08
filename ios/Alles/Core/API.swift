import Foundation

nonisolated struct APIError: LocalizedError {
    let status: Int
    let message: String
    var code: String = ""

    var errorDescription: String? { message }

    static let offline = APIError(status: 0, message: "can't reach your alles. check the address and that it's running.")
}

nonisolated private struct ServerError: Decodable {
    let detail: String?
    let code: String?
}

/// one alles server. every call carries the api token and the phone's time zone.
nonisolated struct API: Sendable {
    let base: URL
    let token: String?

    private static let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.waitsForConnectivity = false
        return URLSession(configuration: config)
    }()

    func url(_ path: String, query: [String: String] = [:]) -> URL {
        var parts = URLComponents(url: base, resolvingAgainstBaseURL: false)!
        parts.path = (parts.path.hasSuffix("/") ? String(parts.path.dropLast()) : parts.path) + path
        if !query.isEmpty {
            parts.queryItems = query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        return parts.url!
    }

    func request(_ method: String, _ path: String, query: [String: String] = [:], json: Data? = nil) -> URLRequest {
        var req = URLRequest(url: url(path, query: query))
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "accept")
        req.setValue(TimeZone.current.identifier, forHTTPHeaderField: "x-alles-time-zone")
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "authorization") }
        if let json {
            req.httpBody = json
            req.setValue("application/json", forHTTPHeaderField: "content-type")
        }
        return req
    }

    func get<T: Decodable>(_ path: String, query: [String: String] = [:]) async throws -> T {
        try await run(request("GET", path, query: query))
    }

    func send<T: Decodable>(_ method: String, _ path: String, _ body: some Encodable) async throws -> T {
        try await run(request(method, path, json: try JSONEncoder().encode(body)))
    }

    func run<T: Decodable>(_ req: URLRequest) async throws -> T {
        let data = try await raw(req)
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw APIError(status: 200, message: "alles answered in a shape this app doesn't know (\(req.url?.path ?? "")).")
        }
    }

    func raw(_ req: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await Self.session.data(for: req)
        } catch {
            throw APIError.offline
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else { throw Self.error(status, data) }
        return data
    }

    static func error(_ status: Int, _ data: Data) -> APIError {
        let parsed = try? JSONDecoder().decode(ServerError.self, from: data)
        let fallback = status == 401 ? "signed out. sign in again." : "alles said no (\(status))."
        return APIError(status: status, message: parsed?.detail ?? fallback, code: parsed?.code ?? "")
    }

    /// server-sent events: each `data:` line is one json object, `[DONE]` ends it
    func events<E: Decodable & Sendable>(_ path: String, _ body: some Encodable, as: E.Type) throws -> AsyncThrowingStream<E, Error> {
        var req = request("POST", path, json: try JSONEncoder().encode(body))
        req.setValue("text/event-stream", forHTTPHeaderField: "accept")
        req.timeoutInterval = 600
        let sent = req
        return AsyncThrowingStream { continuation in
            let task = Task { [sent] in
                do {
                    let (bytes, response) = try await Self.session.bytes(for: sent)
                    let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                    guard (200..<300).contains(status) else {
                        var body = Data()
                        for try await b in bytes { body.append(b) }
                        throw Self.error(status, body)
                    }
                    let decoder = JSONDecoder()
                    for try await line in bytes.lines {
                        guard line.hasPrefix("data:") else { continue }
                        let payload = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
                        if payload == "[DONE]" { break }
                        if let event = try? decoder.decode(E.self, from: Data(payload.utf8)) {
                            continuation.yield(event)
                        }
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch let e as APIError {
                    continuation.finish(throwing: e)
                } catch {
                    continuation.finish(throwing: (error as? URLError)?.code == .cancelled ? CancellationError() : APIError.offline)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

nonisolated struct Empty: Codable {}
nonisolated struct OK: Decodable { let ok: Bool? }

nonisolated enum Day {
    static func key(_ date: Date = .now) -> String {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: date)
    }

    static func date(_ key: String) -> Date? {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: String(key.prefix(10)))
    }

    /// event times are the owner's wall clock ("2026-11-08T10:30:00")
    static func local(_ stamp: String) -> Date? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.date(from: String(stamp.prefix(19)))
    }

    /// message stamps are stored in utc without a zone (core/schema/base.py)
    static func utc(_ stamp: String) -> Date? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.date(from: String(stamp.prefix(19)))
    }

    /// "10:30" from the today feed, shown in the phone's own 12 or 24 hour style
    static func clock(_ hhmm: String) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "HH:mm"
        guard let d = f.date(from: hhmm) else { return hhmm }
        return d.formatted(date: .omitted, time: .shortened).lowercased()
    }
}
