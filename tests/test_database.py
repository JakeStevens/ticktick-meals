import unittest
import os
import sqlite3
import database

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_standalone.db"
        database.DB_FILE = self.test_db
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        database.init_db()

    def tearDown(self):
        # We need to close the connection in the current thread before removing the file
        if hasattr(database._local, "conn"):
            database._local.conn.close()
            del database._local.conn
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except PermissionError:
                pass

    def test_init_db(self):
        conn = sqlite3.connect(self.test_db)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
        self.assertIsNotNone(c.fetchone())
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='logs'")
        self.assertIsNotNone(c.fetchone())
        conn.close()

    def test_create_session(self):
        session_id = database.create_session()
        self.assertTrue(len(session_id) > 0)

        conn = sqlite3.connect(self.test_db)
        c = conn.cursor()
        c.execute("SELECT id FROM sessions WHERE id=?", (session_id,))
        self.assertEqual(c.fetchone()[0], session_id)
        conn.close()

    def test_log_event(self):
        session_id = database.create_session()
        database.log_event(session_id, "test_event", {"key": "value"})

        conn = sqlite3.connect(self.test_db)
        c = conn.cursor()
        c.execute("SELECT event_type, data FROM logs WHERE session_id=?", (session_id,))
        row = c.fetchone()
        self.assertEqual(row[0], "test_event")
        self.assertEqual(row[1], '{"key": "value"}')
        conn.close()

    def test_complete_session(self):
        session_id = database.create_session()
        database.complete_session(session_id)

        conn = sqlite3.connect(self.test_db)
        c = conn.cursor()
        c.execute("SELECT is_complete FROM sessions WHERE id=?", (session_id,))
        self.assertEqual(c.fetchone()[0], 1)
        conn.close()

if __name__ == '__main__':
    unittest.main()
