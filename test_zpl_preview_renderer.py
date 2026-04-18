from __future__ import annotations

from unittest import TestCase, main

from test_scan_print_flow import load_app_module, make_app


class ZplPreviewRendererTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_app_module()

    def test_preview_payload_fills_template_placeholders(self):
        app = make_app(self.module)
        template = """^XA
^PW{width_dots}
^LL{height_dots}
^FO20,20^FDPC:{PC}^FS
^BY2,2,80
^FO20,60^BCN,80,Y,N,N^FD{Barc}^FS
^XZ"""

        rendered, context, width_mm, height_mm = app._build_zpl_preview_payload(template)

        self.assertIn("^PW", rendered)
        self.assertIn("PC:P-100", rendered)
        self.assertIn("BARC-100", rendered)
        self.assertEqual(context["barcode_text"], "SAMPLE123456")
        self.assertGreater(width_mm, 0)
        self.assertGreater(height_mm, 0)

    def test_renderer_creates_nonblank_label_image(self):
        app = make_app(self.module)
        zpl = """^XA
^PW400
^LL260
^CF0,30
^FO20,20^FDHello Preview^FS
^FO20,65^GB320,3,3^FS
^BY2,2,90
^FO20,90^BCN,90,Y,N,N^FDABC123^FS
^XZ"""

        image, notes = app._render_zpl_preview_image(zpl, 50, 30)
        colors = image.getcolors(maxcolors=1000000)
        nonwhite_pixels = sum(count for count, color in colors if color != (255, 255, 255))

        self.assertEqual(image.size, (400, 260))
        self.assertGreater(nonwhite_pixels, 1000)
        self.assertEqual(notes, [])


if __name__ == "__main__":
    main()
