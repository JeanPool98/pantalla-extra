import Foundation
import Network

/// Escucha en el iPad la conexión que llega por el cable USB (túnel usbmux).
/// Protocolo: cada cuadro llega como [4 bytes de longitud, big-endian][cuadro H.264 Annex-B].
final class StreamServer {
    var onFrame: ((Data) -> Void)?
    var onStatus: ((Bool, String) -> Void)?

    private let port: UInt16
    private let queue = DispatchQueue(label: "pantalla.stream", qos: .userInteractive)
    private var listener: NWListener?
    private var connection: NWConnection?
    private var buffer = Data()

    init(port: UInt16) {
        self.port = port
    }

    func start() {
        queue.async { self.startListener() }
    }

    private func startListener() {
        let tcp = NWProtocolTCP.Options()
        tcp.noDelay = true
        let params = NWParameters(tls: nil, tcp: tcp)
        params.allowLocalEndpointReuse = true
        // Las conexiones del cable llegan por la interfaz local del iPad.
        params.requiredInterfaceType = .loopback

        guard let nwPort = NWEndpoint.Port(rawValue: port),
              let listener = try? NWListener(using: params, on: nwPort) else {
            onStatus?(false, "No pude abrir el puerto \(port).")
            return
        }
        listener.newConnectionHandler = { [weak self] conn in
            self?.accept(conn)
        }
        listener.stateUpdateHandler = { [weak self] state in
            if case .failed(let error) = state {
                self?.onStatus?(false, "Error del receptor: \(error.localizedDescription)\nReintentando...")
                listener.cancel()
                self?.queue.asyncAfter(deadline: .now() + 1) { self?.startListener() }
            }
        }
        listener.start(queue: queue)
        self.listener = listener
    }

    private func accept(_ conn: NWConnection) {
        connection?.cancel()
        buffer.removeAll(keepingCapacity: true)
        connection = conn
        conn.stateUpdateHandler = { [weak self] state in
            guard let self else { return }
            switch state {
            case .ready:
                self.onStatus?(true, "Conectado")
            case .failed, .cancelled:
                if self.connection === conn {
                    self.connection = nil
                    self.onStatus?(false, "Se desconectó la laptop.\nEsperando de nuevo...")
                }
            default:
                break
            }
        }
        conn.start(queue: queue)
        receive(on: conn)
    }

    private func receive(on conn: NWConnection) {
        conn.receive(minimumIncompleteLength: 1, maximumLength: 1 << 20) { [weak self] data, _, isComplete, error in
            guard let self, self.connection === conn else { return }
            if let data, !data.isEmpty {
                self.buffer.append(data)
                self.drain()
            }
            if isComplete || error != nil {
                conn.cancel()
                return
            }
            self.receive(on: conn)
        }
    }

    private func drain() {
        var offset = 0
        let total = buffer.count
        buffer.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            let bytes = raw.bindMemory(to: UInt8.self)
            while total - offset >= 4 {
                let length = Int(bytes[offset]) << 24 | Int(bytes[offset + 1]) << 16
                    | Int(bytes[offset + 2]) << 8 | Int(bytes[offset + 3])
                guard length > 0, length < (64 << 20) else {
                    offset = total   // datos corruptos: descartar todo
                    return
                }
                guard total - offset - 4 >= length else { return }
                let start = offset + 4
                onFrame?(Data(bytes: raw.baseAddress!.advanced(by: start), count: length))
                offset = start + length
            }
        }
        if offset > 0 {
            buffer.removeSubrange(buffer.startIndex ..< buffer.startIndex + offset)
        }
    }
}
