#!/usr/bin/env python3
"""
Скрипт-воркер для транскрипции из GUI
"""
import sys
import os
import logging
import argparse

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from whisper_transcriber import WhisperTranscriber

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('audio_path', help='Путь к аудиофайлу')
    parser.add_argument('--model', default='tiny', help='Модель whisper')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        stream=sys.stdout
    )
    
    transcriber = WhisperTranscriber(model_name=args.model)
    result = transcriber.transcribe(args.audio_path)
    
    print("===RESULT_START===")
    print(result)
    print("===RESULT_END===")

if __name__ == '__main__':
    main()