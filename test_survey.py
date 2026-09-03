import unittest
import sqlite3
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import db

class TestSurveySystem(unittest.TestCase):
    def setUp(self):
        # We will use the existing DB helper but wrap it or assume it's running
        pass

    def test_survey_db_functions(self):
        # Insert a survey
        recordings = ["custom/surveys/test1.wav", "custom/surveys/test2.wav"]
        survey_id = db.add_survey("Test Survey 123", recordings)
        self.assertIsNotNone(survey_id)
        
        # Get the survey
        survey = db.get_survey(survey_id)
        self.assertEqual(survey["name"], "Test Survey 123")
        self.assertEqual(len(survey["questions"]), 2)
        
        # Update survey
        new_recordings = ["custom/surveys/test_new.wav"]
        db.update_survey(survey_id, "Test Survey Updated", new_recordings)
        
        updated = db.get_survey(survey_id)
        self.assertEqual(updated["name"], "Test Survey Updated")
        self.assertEqual(len(updated["questions"]), 1)
        self.assertEqual(updated["questions"][0]["recording_path"], "custom/surveys/test_new.wav")
        
        # Save a response
        db.save_survey_response(survey_id, "AgentSmith", "5551234", "6500", [
            {"question_number": 1, "rating": 5, "reason": ""}
        ])
        
        conn = db.get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM survey_responses WHERE survey_id = ?", (survey_id,))
        resp = c.fetchall()
        self.assertEqual(len(resp), 1)
        
        # Clean up
        db.delete_survey(survey_id)
        survey_after = db.get_survey(survey_id)
        self.assertIsNone(survey_after)

if __name__ == '__main__':
    unittest.main()
