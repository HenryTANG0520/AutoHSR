import unittest

from autohsr.theme import Painter


class PainterTests(unittest.TestCase):
    def test_subpixel_viewport_remainder_draws_nothing(self):
        for scale in (1., 1.25, 1.5, 2.):
            with self.subTest(scale=scale):
                painter = Painter(100, 100, scale, "white")
                edge = painter.height
                with painter.clip((0, edge-.001, painter.width, edge)):
                    painter.box((0, 0, painter.width, edge), "red")
                self.assertEqual(set(painter.finish().getdata()), {(255, 255, 255, 255)})
                painter.box((0, 0, 10, 10), "blue")
                self.assertEqual(painter.finish().getpixel((2, 2)), (0, 0, 255, 255))

    def test_empty_nested_clip_preserves_exception_and_outer_drawing(self):
        painter = Painter(100, 100, 1.25, "white")
        with painter.clip((0, 0, 40, 40)):
            with self.assertRaisesRegex(RuntimeError, "original failure"):
                with painter.clip((0, 39.999, 40, 40)):
                    raise RuntimeError("original failure")
            painter.box((0, 0, 10, 10), "blue")
        self.assertEqual(painter.finish().getpixel((2, 2)), (0, 0, 255, 255))
        self.assertEqual(painter.finish().getpixel((90, 90)), (255, 255, 255, 255))

    def test_light_glow_does_not_darken_its_surround(self):
        painter = Painter(100, 100, 1., (100, 100, 100, 255))
        painter.glow((50, 50), 10, (100, 160, 240, 155), 8)
        pixels = list(painter.finish().getdata())
        self.assertTrue(all(red == 100 and green >= 100 and blue >= 100 for red, green, blue, _ in pixels))
        self.assertGreater(painter.finish().getpixel((50, 50))[2], 100)


if __name__ == "__main__":
    unittest.main()
