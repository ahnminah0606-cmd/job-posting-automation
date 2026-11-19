import Foundation
import Vision
import ImageIO

struct Line: Codable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

do {
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["ko-KR", "en-US"]
    request.usesLanguageCorrection = true
    request.minimumTextHeight = 0.002
    try VNImageRequestHandler(url: url, options: [:]).perform([request])
    let lines = (request.results ?? []).compactMap { observation -> Line? in
        guard let result = observation.topCandidates(1).first else { return nil }
        let box = observation.boundingBox
        return Line(text: result.string, confidence: result.confidence,
                    x: box.minX, y: 1 - box.maxY, width: box.width, height: box.height)
    }
    let output = try JSONEncoder().encode(lines)
    FileHandle.standardOutput.write(output)
} catch {
    FileHandle.standardError.write(Data("OCR failed: \(error)\n".utf8))
    exit(1)
}
