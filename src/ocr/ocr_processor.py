import pytesseract
from PIL import Image
from io import BytesIO
import logging
import re

logger = logging.getLogger(__name__)


class OcrProcessor:
    def __init__(self, language: str = "pol"):
        self.language = language

    def process_image(self, image_bytes: bytes, psm: int = 6) -> list[str]:
        """Przetwarza obraz i zwraca listę rozpoznanych linii"""
        try:
            image = Image.open(BytesIO(image_bytes))
            logger.info(f"Obraz: {image.size}, tryb: {image.mode}")

            ocr_config = f"--psm {psm} --oem 3"

            data = pytesseract.image_to_data(
                image,
                lang=self.language,
                output_type=pytesseract.Output.DICT,
                config=ocr_config,
            )

            words_data = []
            for i, word in enumerate(data["text"]):
                word = word.strip()
                if not word or not data['conf'][i] or int(data['conf'][i]) < 0:
                    continue

                words_data.append({
                    'text': word,
                    'left': data['left'][i],
                    'top': data['top'][i],
                    'width': data['width'][i],
                    'height': data['height'][i],
                    'conf': int(data['conf'][i])
                })

            logger.info(f"Znaleziono {len(words_data)} słów (psm={psm})")

            # Grupuj po wierszach
            rows = []
            current_row = []
            current_y = None
            row_tolerance = 30

            for word in sorted(words_data, key=lambda x: (x['top'], x['left'])):
                if current_y is None:
                    current_y = word['top']
                    current_row = [word]
                elif abs(word['top'] - current_y) <= row_tolerance:
                    current_row.append(word)
                else:
                    if current_row:
                        rows.append(current_row)
                    current_row = [word]
                    current_y = word['top']

            if current_row:
                rows.append(current_row)

            # Dla każdego wiersza sortuj kolumny od lewej do prawej
            recognized_lines = []
            for row_idx, row in enumerate(rows):
                row_sorted = sorted(row, key=lambda x: x['left'])
                line_text = ' '.join(word['text'] for word in row_sorted)
                if line_text.strip():
                    recognized_lines.append(line_text.strip())
                    logger.debug(f"Wiersz {row_idx}: {line_text}")

            return recognized_lines

        except Exception as exc:
            logger.error(f"Błąd OCR: {exc}")
            return []
