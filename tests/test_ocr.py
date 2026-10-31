"""OCR matching tests using representative Tesseract word data, not a desktop."""

import unittest
from unittest.mock import Mock, patch

from hyprland_mcp import ocr


def word(text, x, *, y=20, width=30, height=12, conf=90,
         page=1, block=1, paragraph=1, line=1, order=1):
    return dict(text=text, left=x, top=y, width=width, height=height,
                conf=conf, page_num=page, block_num=block,
                par_num=paragraph, line_num=line, word_num=order)


def extract(*words, scale=1.0):
    data = {key: [item[key] for item in words] for key in words[0]}
    with patch.object(ocr, "_check_tesseract"), patch.object(
        ocr.PILImage, "open"
    ), patch.object(ocr, "_preprocess_for_ocr"), patch.object(
        ocr.pytesseract, "image_to_data", return_value=data
    ):
        return ocr.extract_boxes(b"image", scale=scale)


class OCRTests(unittest.TestCase):
    def test_phrase_and_scaled_coordinates(self):
        boxes = extract(word("Save", 20, width=60),
                        word("changes", 90, width=100, order=2), scale=2)
        matches = ocr.find_text(boxes, "save changes")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0], dict(text="Save changes", x=10, y=10,
                                          w=85, h=6, conf=90))
        self.assertEqual(boxes[0]["conf"], 90)
        self.assertEqual(boxes[0]["line_id"], (1, 1, 1, 1))
        self.assertEqual([box["word_num"] for box in boxes], [1, 2])
        self.assertEqual(ocr.find_text(boxes, "Save changes", case_sensitive=True), matches)
        self.assertEqual(ocr.find_text(boxes, "save changes", case_sensitive=True), [])

    def test_distant_columns_or_different_lines_do_not_form_a_phrase(self):
        cases = [word("changes", 1500, order=2),
                 word("changes", 45, block=2, order=2),
                 word("changes", 45, line=2, order=2)]
        for second in cases:
            with self.subTest(second=second):
                boxes = extract(word("Save", 10), second)
                self.assertEqual(ocr.find_text(boxes, "Save changes"), [])

    def test_filtered_word_must_not_join_its_neighbors(self):
        boxes = extract(word("Save", 10), word("all", 45, conf=20, order=2),
                        word("changes", 80, order=3))
        self.assertEqual([box["text"] for box in boxes], ["Save", "changes"])
        self.assertEqual(ocr.find_text(boxes, "Save changes"), [])

    def test_phrase_with_spaced_words(self):
        boxes = extract(word("Save", 10), word("changes", 70, order=2))
        match, = ocr.find_text(boxes, "Save changes")
        self.assertEqual((match["x"], match["w"]), (10, 90))

    def test_reverse_spatial_order_encloses_both_words(self):
        boxes = extract(word("Save", 45), word("changes", 10, order=2))
        match, = ocr.find_text(boxes, "Save changes")
        self.assertEqual((match["x"], match["w"]), (10, 65))

    def test_single_word_and_legacy_boxes(self):
        boxes = [dict(text="Save", x=10, y=20, w=30, h=12, conf=90),
                 dict(text="changes", x=45, y=20, w=30, h=12, conf=80)]
        self.assertEqual(ocr.find_text(boxes, "ave"), [boxes[0]])
        self.assertEqual(ocr.find_text(boxes, "Save changes")[0]["w"], 65)

    def test_preprocessing_uses_exact_histogram_mean(self):
        for pixels, inverted in [([0, 254], True), ([1, 255], False)]:
            with self.subTest(pixels=pixels):
                image, gray = Mock(), Mock()
                image.convert.return_value = gray
                gray.histogram.return_value = [pixels.count(i) for i in range(256)]
                gray.getdata.return_value = pixels
                with patch.object(ocr.ImageOps, "invert", return_value=gray) as invert:
                    ocr._preprocess_for_ocr(image)
                self.assertEqual(invert.called, inverted)
                gray.getdata.assert_not_called()
                gray.histogram.assert_called_once()


if __name__ == "__main__":
    unittest.main()
