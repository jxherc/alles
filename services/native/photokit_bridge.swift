import Foundation
import Photos
import UniformTypeIdentifiers

private struct StatusPayload: Codable {
    let authorization: String
}

private struct ResourcePayload: Codable {
    let source_id: String
    let asset_id: String
    let kind: String
    let original_name: String
    let taken_at: String?
    let modified_at: String?
    let favorite: Bool
    let hidden: Bool
    let width: Int
    let height: Int
    let lat: Double?
    let lon: Double?
    let live_photo: Bool
}

private struct ExportRequest: Codable {
    let asset_id: String
    let kind: String
    let destination: String
    let timeout: Double
}

private struct ExportResponse: Codable {
    let ok: Bool
    let error: String?
}

private func authorizationName(_ status: PHAuthorizationStatus) -> String {
    switch status {
    case .notDetermined: return "not_determined"
    case .restricted: return "restricted"
    case .denied: return "denied"
    case .authorized: return "authorized"
    case .limited: return "limited"
    @unknown default: return "unknown"
    }
}

private func writeJSON<T: Encodable>(_ value: T) throws {
    let encoder = JSONEncoder()
    let data = try encoder.encode(value)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([0x0A]))
}

private func fail(_ message: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(code)
}

private func waitFor(_ semaphore: DispatchSemaphore, timeout: TimeInterval) -> Bool {
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
        if semaphore.wait(timeout: .now()) == .success { return true }
        RunLoop.current.run(until: Date().addingTimeInterval(0.025))
    }
    return false
}

private func authorization(request: Bool) -> PHAuthorizationStatus {
    var current = PHPhotoLibrary.authorizationStatus(for: .readWrite)
    guard request && current == .notDetermined else { return current }
    let semaphore = DispatchSemaphore(value: 0)
    PHPhotoLibrary.requestAuthorization(for: .readWrite) { status in
        current = status
        semaphore.signal()
    }
    guard waitFor(semaphore, timeout: 60) else { fail("authorization timed out", code: 3) }
    return current
}

private func isReady(_ status: PHAuthorizationStatus) -> Bool {
    status == .authorized || status == .limited
}

private func selectedResources(for asset: PHAsset) -> [(String, PHAssetResource)] {
    let resources = PHAssetResource.assetResources(for: asset)
    var byType: [Int: PHAssetResource] = [:]
    for resource in resources where byType[resource.type.rawValue] == nil {
        byType[resource.type.rawValue] = resource
    }
    func first(_ types: [Int]) -> PHAssetResource? {
        for type in types {
            if let resource = byType[type] { return resource }
        }
        return nil
    }

    if asset.mediaType == .image {
        var selected: [(String, PHAssetResource)] = []
        // fullSizePhoto is the current nondestructive edit; photo is the original.
        if let photo = first([5, 1, 8, 4, 19]) { selected.append(("photo", photo)) }
        if let motion = first([10, 9, 11]) { selected.append(("paired_video", motion)) }
        return selected
    }
    if asset.mediaType == .video, let video = first([6, 2, 12]) {
        return [("video", video)]
    }
    return []
}

private func safeFilename(_ resource: PHAssetResource, kind: String) -> String {
    let raw = (resource.originalFilename as NSString).lastPathComponent
    if !(raw as NSString).pathExtension.isEmpty { return raw }
    let fallback = kind == "photo" ? "jpg" : "mov"
    let ext = UTType(resource.uniformTypeIdentifier)?.preferredFilenameExtension ?? fallback
    let stem = raw.isEmpty ? (kind == "photo" ? "IMG" : "VIDEO") : raw
    return "\(stem).\(ext)"
}

private let isoFormatter: ISO8601DateFormatter = {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter
}()

private func listResources() -> [ResourcePayload] {
    let options = PHFetchOptions()
    options.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
    options.includeHiddenAssets = false
    let assets = PHAsset.fetchAssets(with: options)
    var records: [ResourcePayload] = []
    records.reserveCapacity(assets.count)
    assets.enumerateObjects { asset, _, _ in
        let location = asset.location?.coordinate
        let live = asset.mediaSubtypes.contains(.photoLive)
        for (kind, resource) in selectedResources(for: asset) {
            records.append(ResourcePayload(
                source_id: "\(asset.localIdentifier):\(kind)",
                asset_id: asset.localIdentifier,
                kind: kind,
                original_name: safeFilename(resource, kind: kind),
                taken_at: asset.creationDate.map { isoFormatter.string(from: $0) },
                modified_at: asset.modificationDate.map { isoFormatter.string(from: $0) },
                favorite: asset.isFavorite,
                hidden: asset.isHidden,
                width: asset.pixelWidth,
                height: asset.pixelHeight,
                lat: location?.latitude,
                lon: location?.longitude,
                live_photo: live
            ))
        }
    }
    return records
}

private func value(after flag: String) -> String? {
    guard let index = CommandLine.arguments.firstIndex(of: flag) else { return nil }
    let next = CommandLine.arguments.index(after: index)
    return next < CommandLine.arguments.endIndex ? CommandLine.arguments[next] : nil
}

private enum ExportFailure: Error {
    case missingResource
    case timeout
    case failed
}

private func exportResource(
    assetID: String, kind: String, destination: String, timeout: Double
) throws {
    let fetched = PHAsset.fetchAssets(withLocalIdentifiers: [assetID], options: nil)
    guard let asset = fetched.firstObject,
          let resource = selectedResources(for: asset).first(where: { $0.0 == kind })?.1 else {
        throw ExportFailure.missingResource
    }
    let url = URL(fileURLWithPath: destination)
    try? FileManager.default.removeItem(at: url)
    guard FileManager.default.createFile(atPath: destination, contents: nil),
          let handle = try? FileHandle(forWritingTo: url) else {
        throw ExportFailure.failed
    }
    let options = PHAssetResourceRequestOptions()
    options.isNetworkAccessAllowed = true
    let semaphore = DispatchSemaphore(value: 0)
    let lock = NSLock()
    var completionError: Error?
    var writeError: Error?
    var stopped = false
    let manager = PHAssetResourceManager.default()
    let requestID = manager.requestData(
        for: resource,
        options: options,
        dataReceivedHandler: { data in
            lock.lock()
            defer { lock.unlock() }
            guard !stopped, writeError == nil else { return }
            do {
                try handle.write(contentsOf: data)
            } catch {
                writeError = error
            }
        },
        completionHandler: { error in
            lock.lock()
            completionError = error
            lock.unlock()
            semaphore.signal()
        })
    guard waitFor(semaphore, timeout: timeout) else {
        manager.cancelDataRequest(requestID)
        _ = waitFor(semaphore, timeout: 5)
        lock.lock()
        stopped = true
        try? handle.close()
        lock.unlock()
        try? FileManager.default.removeItem(at: url)
        throw ExportFailure.timeout
    }
    lock.lock()
    stopped = true
    let exportError = completionError ?? writeError
    try? handle.close()
    lock.unlock()
    guard exportError == nil, FileManager.default.fileExists(atPath: destination) else {
        try? FileManager.default.removeItem(at: url)
        throw ExportFailure.failed
    }
}

private func exportFromArguments() throws {
    guard let assetID = value(after: "--asset-id"),
          let kind = value(after: "--kind"),
          let destination = value(after: "--destination") else {
        fail("missing export arguments", code: 2)
    }
    let timeout = Double(value(after: "--timeout") ?? "1800") ?? 1800
    try exportResource(assetID: assetID, kind: kind, destination: destination, timeout: timeout)
}

private func serveExports() {
    let decoder = JSONDecoder()
    while let line = readLine() {
        autoreleasepool {
            do {
                let request = try decoder.decode(ExportRequest.self, from: Data(line.utf8))
                try exportResource(
                    assetID: request.asset_id,
                    kind: request.kind,
                    destination: request.destination,
                    timeout: request.timeout)
                try writeJSON(ExportResponse(ok: true, error: nil))
            } catch let failure as ExportFailure {
                let reason: String
                switch failure {
                case .timeout: reason = "timeout"
                default: reason = "export"
                }
                try? writeJSON(ExportResponse(ok: false, error: reason))
            } catch {
                try? writeJSON(ExportResponse(ok: false, error: "export"))
            }
        }
    }
}

autoreleasepool {
    do {
        let command = CommandLine.arguments.dropFirst().first ?? "status"
        switch command {
        case "status":
            try writeJSON(StatusPayload(
                authorization: authorizationName(authorization(request: false))))
        case "authorize":
            try writeJSON(StatusPayload(
                authorization: authorizationName(authorization(request: true))))
        case "list":
            let status = authorization(request: false)
            guard isReady(status) else { fail("Photos permission is not granted", code: 6) }
            try writeJSON(listResources())
        case "export":
            let status = authorization(request: false)
            guard isReady(status) else { fail("Photos permission is not granted", code: 6) }
            try exportFromArguments()
            try writeJSON(["ok": true])
        case "serve":
            let status = authorization(request: false)
            guard isReady(status) else { fail("Photos permission is not granted", code: 6) }
            serveExports()
        default:
            fail("unknown command", code: 2)
        }
    } catch {
        fail("PhotoKit bridge failed")
    }
}
