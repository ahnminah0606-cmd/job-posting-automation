#import <Foundation/Foundation.h>
#import <Vision/Vision.h>

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 1;
        NSURL *url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[1]]];
        VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc] init];
        request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
        request.recognitionLanguages = @[@"ko-KR", @"en-US"];
        request.usesLanguageCorrection = YES;
        request.minimumTextHeight = 0.002;
        VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithURL:url options:@{}];
        NSError *error = nil;
        if (![handler performRequests:@[request] error:&error]) {
            fprintf(stderr, "Vision OCR failed\n");
            return 1;
        }
        NSMutableArray *lines = [NSMutableArray array];
        for (VNRecognizedTextObservation *observation in request.results) {
            VNRecognizedText *candidate = [[observation topCandidates:1] firstObject];
            if (!candidate) continue;
            CGRect box = observation.boundingBox;
            [lines addObject:@{@"text": candidate.string, @"confidence": @(candidate.confidence),
                @"x": @(CGRectGetMinX(box)), @"y": @(1 - CGRectGetMaxY(box)),
                @"width": @(box.size.width), @"height": @(box.size.height)}];
        }
        NSData *data = [NSJSONSerialization dataWithJSONObject:lines options:0 error:&error];
        if (!data) return 1;
        fwrite(data.bytes, 1, data.length, stdout);
    }
    return 0;
}
