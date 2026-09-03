import unittest
from tests.test_queue_app import QueueAppTestCase

class DebugTest(QueueAppTestCase):
    def run_debug(self):
        self.setUpClass()
        self.setUp()
        self.reset_queue_db()
        
        print("Initial self.ami_commands:", self.ami_commands)
        
        # Login Bob
        import rcm_queue_db
        rcm_queue_db.db_agent_login("5002", "6500", "Bob", "DYNAMIC")
        print("After login, self.ami_commands:", self.ami_commands)
        
        # Leave
        leave_response = self.client.post("/queues/6500/agents/leave", data={"agent": "5002"})
        print("Leave response:", leave_response.status_code, leave_response.get_json())
        print("After leave, self.ami_commands:", self.ami_commands)
        
        # Pause
        pause_response = self.client.post(
            "/call-center/supervisor/control",
            json={"command": "pause", "agent": "5002", "queue": "6500", "reason": "Break"},
        )
        print("Pause response:", pause_response.status_code, pause_response.get_json())
        print("After pause, self.ami_commands:", self.ami_commands)
        
        # Unpause
        unpause_response = self.client.post(
            "/call-center/supervisor/control",
            json={"command": "unpause", "agent": "5002", "queue": "6500"},
        )
        print("Unpause response:", unpause_response.status_code, unpause_response.get_json())
        print("After unpause, self.ami_commands:", self.ami_commands)
        
        self.tearDown()
        self.tearDownClass()

if __name__ == "__main__":
    d = DebugTest()
    d.run_debug()
