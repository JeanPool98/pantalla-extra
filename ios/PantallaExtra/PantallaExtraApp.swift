import SwiftUI
import AVFoundation

@main
struct PantallaExtraApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

struct ContentView: View {
    @StateObject private var model = DisplayModel()

    var body: some View {
        ZStack {
            Color.black
            DisplayLayerView(displayLayer: model.displayLayer)
            if !model.connected {
                VStack(spacing: 14) {
                    Image(systemName: "cable.connector")
                        .font(.system(size: 44))
                    Text("Pantalla Extra")
                        .font(.largeTitle.bold())
                    Text(model.status)
                        .font(.title3)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.white.opacity(0.75))
                }
                .foregroundStyle(.white)
                .padding(40)
            }
        }
        .ignoresSafeArea()
        .statusBarHidden(true)
        .persistentSystemOverlays(.hidden)
        .onAppear {
            UIApplication.shared.isIdleTimerDisabled = true
            model.start()
        }
    }
}

/// Une el receptor por cable con el decodificador y la capa de video.
@MainActor
final class DisplayModel: ObservableObject {
    @Published var connected = false
    @Published var status = "Conecta el iPad a la laptop con el cable USB-C\ny abre Pantalla Extra en Windows."

    let displayLayer = AVSampleBufferDisplayLayer()
    private var server: StreamServer?
    private var decoder: FrameDecoder?

    func start() {
        guard server == nil else { return }
        displayLayer.videoGravity = .resizeAspect
        displayLayer.backgroundColor = UIColor.black.cgColor

        let decoder = FrameDecoder(layer: displayLayer)
        let server = StreamServer(port: 7100)
        server.onFrame = { frame in decoder.decode(accessUnit: frame) }
        server.onStatus = { [weak self] isConnected, text in
            // Corre en la misma cola que decode(), así no hay carreras.
            if !isConnected { decoder.reset() }
            Task { @MainActor in
                guard let self else { return }
                self.connected = isConnected
                self.status = text
            }
        }
        server.start()
        self.decoder = decoder
        self.server = server
    }
}

/// Vista que contiene la capa de video y la ajusta al tamaño de la pantalla.
struct DisplayLayerView: UIViewRepresentable {
    let displayLayer: AVSampleBufferDisplayLayer

    func makeUIView(context: Context) -> LayerHostView {
        let view = LayerHostView()
        view.backgroundColor = .black
        view.hosted = displayLayer
        view.layer.addSublayer(displayLayer)
        return view
    }

    func updateUIView(_ uiView: LayerHostView, context: Context) {}

    final class LayerHostView: UIView {
        var hosted: CALayer?
        override func layoutSubviews() {
            super.layoutSubviews()
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            hosted?.frame = bounds
            CATransaction.commit()
        }
    }
}
