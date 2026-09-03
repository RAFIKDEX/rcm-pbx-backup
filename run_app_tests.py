import unittest
import sys
sys.path.insert(0, '/root/RCM_7021')
from tests.test_queue_app import QueueAppTestCase

suite = unittest.defaultTestLoader.loadTestsFromTestCase(QueueAppTestCase)
with open('/root/RCM_7021/scratch/test_app_results.txt', 'w') as f:
    runner = unittest.TextTestRunner(stream=f, verbosity=2)
    runner.run(suite)
print("Done running tests!")
