import sys
import unittest
from unittest.mock import patch, MagicMock

# Add project path
sys.path.insert(0, '/root/RCM_7021')

import app
import db
import asterisk_helper

class TestQueueValidation(unittest.TestCase):
    def setUp(self):
        # Create a Flask test client
        self.app = app.app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

    @patch('db.get_queues')
    @patch('asterisk_helper.get_live_queue_status')
    def test_queue_not_exist(self, mock_live_status, mock_get_queues):
        # Setup: empty queues in DB
        mock_get_queues.return_value = []
        
        # Test Login (join)
        r = self.client.post('/queues/9999/agents/join', data={'agent': '5001'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()['msg'], "Queue does not exist")

        # Test Logout (leave)
        r = self.client.post('/queues/9999/agents/leave', data={'agent': '5001'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()['msg'], "Queue does not exist")

        # Test Pause (disable)
        r = self.client.post('/queues/9999/agents/disable', data={'agent': '5001'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()['msg'], "Queue does not exist")

        # Test Unpause (enable)
        r = self.client.post('/queues/9999/agents/enable', data={'agent': '5001'})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()['msg'], "Queue does not exist")

    @patch('db.get_queues')
    @patch('asterisk_helper.get_live_queue_status')
    def test_duplicate_login(self, mock_live_status, mock_get_queues):
        # Setup: Queue exists, agent 5001 is already a member
        mock_get_queues.return_value = [{'queue_number': '6500', 'name': 'Support Queue'}]
        mock_live_status.return_value = {
            '6500': {
                'members': [
                    {'location': 'PJSIP/5001', 'paused': 0, 'state': 1, 'name': 'Alice Smith'}
                ]
            }
        }
        
        # Trying to login (join) again should return duplicate error
        r = self.client.post('/queues/6500/agents/join', data={'agent': '5001'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['msg'], "You are already logged in this queue")

    @patch('db.get_queues')
    @patch('asterisk_helper.get_live_queue_status')
    def test_logout_without_login(self, mock_live_status, mock_get_queues):
        # Setup: Queue exists, but agent 5001 is NOT a member
        mock_get_queues.return_value = [{'queue_number': '6500', 'name': 'Support Queue'}]
        mock_live_status.return_value = {
            '6500': {
                'members': []
            }
        }
        
        # Trying to logout (leave) should return not logged in error
        r = self.client.post('/queues/6500/agents/leave', data={'agent': '5001'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['msg'], "Agent is not logged in this queue")

    @patch('db.get_queues')
    @patch('asterisk_helper.get_live_queue_status')
    def test_duplicate_pause(self, mock_live_status, mock_get_queues):
        # Setup: Queue exists, agent is logged in and ALREADY paused
        mock_get_queues.return_value = [{'queue_number': '6500', 'name': 'Support Queue'}]
        mock_live_status.return_value = {
            '6500': {
                'members': [
                    {'location': 'PJSIP/5001', 'paused': 1, 'state': 1, 'name': 'Alice Smith'}
                ]
            }
        }
        
        # Trying to pause (disable) again should return duplicate pause error
        r = self.client.post('/queues/6500/agents/disable', data={'agent': '5001'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['msg'], "You are already paused")

    @patch('db.get_queues')
    @patch('asterisk_helper.get_live_queue_status')
    def test_unpause_not_paused(self, mock_live_status, mock_get_queues):
        # Setup: Queue exists, agent is logged in but NOT paused (paused = 0)
        mock_get_queues.return_value = [{'queue_number': '6500', 'name': 'Support Queue'}]
        mock_live_status.return_value = {
            '6500': {
                'members': [
                    {'location': 'PJSIP/5001', 'paused': 0, 'state': 1, 'name': 'Alice Smith'}
                ]
            }
        }
        
        # Trying to unpause (enable) should return not paused error
        r = self.client.post('/queues/6500/agents/enable', data={'agent': '5001'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['msg'], "Agent is not paused")


if __name__ == '__main__':
    unittest.main()
