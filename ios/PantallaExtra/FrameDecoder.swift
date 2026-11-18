import AVFoundation
import CoreMedia

/// Convierte cada cuadro H.264 (Annex-B) en una muestra que el iPad decodifica
/// por hardware y muestra de inmediato, sin cola de reproducción.
final class FrameDecoder {
    private let layer: AVSampleBufferDisplayLayer
    private var sps: [UInt8]?
    private var pps: [UInt8]?
    private var format: CMVideoFormatDescription?
    private var waitingForKeyframe = true

    init(layer: AVSampleBufferDisplayLayer) {
        self.layer = layer
    }

    /// Se llama al desconectar: el próximo video empieza en un cuadro clave.
    func reset() {
        waitingForKeyframe = true
        layer.sampleBufferRenderer.flush()
    }

    func decode(accessUnit: Data) {
        let bytes = [UInt8](accessUnit)
        var slices: [[UInt8]] = []
        var isKeyframe = false

        for nal in FrameDecoder.splitAnnexB(bytes) {
            switch nal[0] & 0x1F {
            case 7:
                if sps != nal { sps = nal; format = nil }
            case 8:
                if pps != nal { pps = nal; format = nil }
            case 5:
                isKeyframe = true
                slices.append(nal)
            case 1:
                slices.append(nal)
            default:
                break   // SEI, delimitadores, etc.
            }
        }

        if format == nil, let sps, let pps {
            format = FrameDecoder.makeFormat(sps: sps, pps: pps)
            waitingForKeyframe = true
        }
        guard let format, !slices.isEmpty else { return }

        let renderer = layer.sampleBufferRenderer
        if renderer.status == .failed {
            renderer.flush()
            waitingForKeyframe = true
        }
        if waitingForKeyframe {
            guard isKeyframe else { return }
            waitingForKeyframe = false
        }

        guard let sample = FrameDecoder.makeSample(slices: slices, format: format) else { return }
        renderer.enqueue(sample)
    }

    // MARK: - Utilidades H.264

    /// Separa un cuadro Annex-B (00 00 01 / 00 00 00 01) en unidades NAL.
    static func splitAnnexB(_ b: [UInt8]) -> [[UInt8]] {
        var starts: [Int] = []     // primer byte de cada NAL
        var codeStarts: [Int] = [] // dónde empieza cada código de inicio
        var i = 0
        let n = b.count
        while i + 2 < n {
            if b[i] == 0 && b[i + 1] == 0 && b[i + 2] == 1 {
                codeStarts.append(i > 0 && b[i - 1] == 0 ? i - 1 : i)
                starts.append(i + 3)
                i += 3
            } else {
                i += 1
            }
        }
        var nals: [[UInt8]] = []
        for k in 0..<starts.count {
            let end = k + 1 < starts.count ? codeStarts[k + 1] : n
            if end > starts[k] {
                nals.append(Array(b[starts[k]..<end]))
            }
        }
        return nals
    }

    static func makeFormat(sps: [UInt8], pps: [UInt8]) -> CMVideoFormatDescription? {
        var format: CMFormatDescription?
        let status: OSStatus = sps.withUnsafeBufferPointer { spsPtr in
            pps.withUnsafeBufferPointer { ppsPtr in
                let pointers: [UnsafePointer<UInt8>] = [spsPtr.baseAddress!, ppsPtr.baseAddress!]
                let sizes: [Int] = [spsPtr.count, ppsPtr.count]
                return CMVideoFormatDescriptionCreateFromH264ParameterSets(
                    allocator: kCFAllocatorDefault,
                    parameterSetCount: 2,
                    parameterSetPointers: pointers,
                    parameterSetSizes: sizes,
                    nalUnitHeaderLength: 4,
                    formatDescriptionOut: &format)
            }
        }
        return status == noErr ? format : nil
    }

    /// Junta los slices del cuadro en formato AVCC (longitud de 4 bytes + NAL).
    static func makeSample(slices: [[UInt8]], format: CMVideoFormatDescription) -> CMSampleBuffer? {
        var avcc = [UInt8]()
        avcc.reserveCapacity(slices.reduce(0) { $0 + $1.count + 4 })
        for nal in slices {
            let len = UInt32(nal.count)
            avcc.append(UInt8((len >> 24) & 0xFF))
            avcc.append(UInt8((len >> 16) & 0xFF))
            avcc.append(UInt8((len >> 8) & 0xFF))
            avcc.append(UInt8(len & 0xFF))
            avcc.append(contentsOf: nal)
        }
        let count = avcc.count

        var block: CMBlockBuffer?
        var status = CMBlockBufferCreateWithMemoryBlock(
            allocator: kCFAllocatorDefault,
            memoryBlock: nil,
            blockLength: count,
            blockAllocator: kCFAllocatorDefault,
            customBlockSource: nil,
            offsetToData: 0,
            dataLength: count,
            flags: 0,
            blockBufferOut: &block)
        guard status == kCMBlockBufferNoErr, let block else { return nil }

        status = avcc.withUnsafeBytes { raw in
            CMBlockBufferReplaceDataBytes(
                with: raw.baseAddress!,
                blockBuffer: block,
                offsetIntoDestination: 0,
                dataLength: count)
        }
        guard status == kCMBlockBufferNoErr else { return nil }

        var sample: CMSampleBuffer?
        var sampleSize = count
        status = CMSampleBufferCreateReady(
            allocator: kCFAllocatorDefault,
            dataBuffer: block,
            formatDescription: format,
            sampleCount: 1,
            sampleTimingEntryCount: 0,
            sampleTimingArray: nil,
            sampleSizeEntryCount: 1,
            sampleSizeArray: &sampleSize,
            sampleBufferOut: &sample)
        guard status == noErr, let sample else { return nil }

        // Mostrar apenas se decodifique, sin esperar a ningún reloj.
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: true),
           CFArrayGetCount(attachments) > 0 {
            let dict = unsafeBitCast(CFArrayGetValueAtIndex(attachments, 0), to: CFMutableDictionary.self)
            CFDictionarySetValue(
                dict,
                Unmanaged.passUnretained(kCMSampleAttachmentKey_DisplayImmediately).toOpaque(),
                Unmanaged.passUnretained(kCFBooleanTrue).toOpaque())
        }
        return sample
    }
}
