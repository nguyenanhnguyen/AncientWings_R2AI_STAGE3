"""Regressions for the Bạch Mai DOM observed in ids_2583_12583 diagnostics."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from lxml import html

spec = importlib.util.spec_from_file_location('bachmai_crawler', Path(__file__).parents[1] / 'src/vibiomir/crawl/crawler.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class BachmaiParserTests(unittest.TestCase):
    def extract(self, article):
        # Generic metadata picked a related story's date in the actual diagnostics.
        metadata = json.dumps({'title': 'Bài chính', 'date': '2026-10-02', 'text': 'Generic text'})
        with patch.object(c.trafilatura, 'extract', return_value=metadata):
            return c.extract(article.encode('utf-8'), 'text/html; charset=utf-8',
                             'https://bachmai.gov.vn/bai-viet/example')

    def test_date_comes_from_current_article_despite_related_dates(self):
        body = '''<html><body><div class="post-date">02/10/2026</div>
        <div id="content-post"><div id="title-print"><span>Ngày đăng: <!-- -->19/03/2009</span></div>
        <div class="content-editor-post"><p>Nội dung bài.</p></div></div>
        <div class="post-detail__same-category-content">02/10/2026</div></body></html>'''
        self.assertEqual(self.extract(body)['published_at'], '2009-03-19')

    def test_missing_invalid_or_ambiguous_article_date_is_null(self):
        for header in ['', '<span>Ngày đăng: 31/02/2009</span>', '<span>02/10/2026</span>',
                       '<span>Ngày đăng: 19/03/2009</span><span>Ngày đăng: 02/10/2026</span>']:
            with self.subTest(header=header):
                body = f'''<html><body><div id="content-post"><div id="title-print">{header}</div>
                <div class="content-editor-post"><p>Bài chính.</p></div></div>
                <div class="post-date">02/10/2026</div></body></html>'''
                self.assertIsNone(self.extract(body)['published_at'])
        duplicate = '''<html><body><div id="content-post"><div id="title-print">Ngày đăng: 19/03/2009</div></div>
        <div id="content-post"><div id="title-print">Ngày đăng: 02/10/2026</div></div></body></html>'''
        self.assertIsNone(self.extract(duplicate)['published_at'])

    def test_embedded_related_story_is_removed_without_losing_article_text(self):
        body = '''<html><body><div class="content-excerpt">Mở đầu.</div><div class="content-editor-post">
        <p>Liều <b>0,5</b> mg/kg; đọc <a href="https://example.org/study">nghiên cứu gốc</a>.</p>
        <article class="story story--left clearfix"><a class="thumb"><img src="related.jpg"></a>
        <header><h4 class="label">TIN LIÊN QUAN</h4>
        <a class="title" href="https://example.org/related">Ngăn ngừa ung thư từ phòng ngủ</a></header></article>Đoạn ngay sau widget.
        <figure><img src="main.jpg"><figcaption>Caption của bài.</figcaption></figure>
        <table><tr><td>12</td><td>5 mg</td></tr></table>
        <p>TIN LIÊN QUAN là nhãn được thảo luận trong bài.</p>
        <article class="story"><header><h4 class="label">Ví dụ y khoa</h4>
        <a class="title" href="https://example.org/case">Ca bệnh cần giữ.</a></header></article>
        <div class="post-detail__same-category-content">Widget cùng chuyên mục.</div>Đoạn cuối.
        </div></body></html>'''
        doc = self.extract(body)
        self.assertNotIn('Ngăn ngừa ung thư từ phòng ngủ', doc['text'])
        self.assertNotIn('Widget cùng chuyên mục', doc['text'])
        for text in ['Mở đầu.', '0,5 mg/kg', 'nghiên cứu gốc', 'Đoạn ngay sau widget.',
                     'Caption của bài.', '12 | 5 mg |', 'TIN LIÊN QUAN là nhãn', 'Ca bệnh cần giữ.', 'Đoạn cuối.']:
            self.assertIn(text, doc['text'])
        self.assertEqual(doc['source_images'], [{'url': 'main.jpg', 'alt': None}])
        tree = html.fromstring(body)
        original = html.tostring(tree)
        c.bachmai_article_body(tree.xpath('//div[@class="content-editor-post"]')[0])
        self.assertEqual(html.tostring(tree), original)

    def test_other_domains_keep_generic_metadata(self):
        with patch.object(c.trafilatura, 'extract', return_value=json.dumps({'date': '2020-05-01'})):
            doc = c.extract(b'<html><body>Article</body></html>', 'text/html', 'https://example.org/article')
        self.assertEqual(doc['published_at'], '2020-05-01')

    def test_image_only_article_still_requires_review_with_v2(self):
        body = '<html><body><div class="content-excerpt">' + 'Phần giới thiệu. ' * 30 + '''</div>
        <div class="content-editor-post"><img src="scan.jpg"></div></body></html>'''
        doc = self.extract(body)
        quality = c.quality(doc)
        self.assertEqual(quality['quality_status'], 'review')
        self.assertIn('short_article_body', quality['quality_flags'])
        self.assertIn('image_text_requires_ocr_review', quality['quality_flags'])


if __name__ == '__main__':
    unittest.main()
