import unittest
import os
import sys

# Make sure the project root is on the path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

import database
from email_sender import render_email


class TestMextSender(unittest.TestCase):

    def setUp(self):
        # Use a temp DB so tests never touch professors.db
        database.DB_PATH = os.path.join(PROJECT_ROOT, "test_professors.db")
        if os.path.exists(database.DB_PATH):
            os.remove(database.DB_PATH)
        database.init_db()

        # Ensure render_email can find template.txt and config.yaml
        # by making the project root the working directory for every test
        self._orig_cwd = os.getcwd()
        os.chdir(PROJECT_ROOT)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        if os.path.exists(database.DB_PATH):
            os.remove(database.DB_PATH)

    # ── database tests ────────────────────────────────────────────────────────

    def test_database_deduplication(self):
        data = self._sample_prof()
        self.assertTrue(database.add_professor(data))
        self.assertFalse(database.add_professor(data), "Duplicate email must be rejected")

    def test_database_queue(self):
        database.add_professor(self._sample_prof())
        pending = database.get_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['email'], 'test@example.com')

        database.update_status('test@example.com', 'sent')
        self.assertEqual(len(database.get_pending()), 0)

    def test_database_stats(self):
        database.add_professor(self._sample_prof())
        database.update_status('test@example.com', 'sent')
        stats = database.get_stats()
        self.assertEqual(stats.get('sent', 0), 1)

    def test_increment_fail(self):
        database.add_professor(self._sample_prof())
        count = database.increment_fail('test@example.com')
        self.assertEqual(count, 1)
        count = database.increment_fail('test@example.com')
        self.assertEqual(count, 2)

    # ── email rendering tests ─────────────────────────────────────────────────

    def test_template_rendering(self):
        data = {
            'name': 'Taro Maruyama',
            'email': 'maruyama@example.jp',
            'university': 'University of Tokyo',
            'department': 'CS',
            'lab_url': 'https://example.jp',
            'focus_en': 'Deep Learning Applications',
            'focus_ja': 'ディープラーニング応用',
            'source_url': 'https://example.jp/research',
        }
        rendered = render_email(data)
        self.assertIn("Dear Professor Maruyama", rendered)
        self.assertIn("University of Tokyo", rendered)
        self.assertIn("Deep Learning Applications", rendered)

    def test_template_last_name_extraction(self):
        """Single-name professors should not crash."""
        data = self._sample_prof()
        data['name'] = 'Yamamoto'
        rendered = render_email(data)
        self.assertIn("Dear Professor Yamamoto", rendered)

    # ── helper ────────────────────────────────────────────────────────────────

    @staticmethod
    def _sample_prof():
        return {
            'name': 'Test User',
            'email': 'test@example.com',
            'university': 'Test University',
            'department': 'CS',
            'lab_url': 'https://example.com',
            'focus_en': 'Neural Networks for Mobile',
            'focus_ja': 'モバイル向けニューラルネットワーク',
            'source_url': 'https://example.com/source',
        }


if __name__ == '__main__':
    unittest.main()
